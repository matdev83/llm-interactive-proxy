# Research & Design Decisions Template

---
**Purpose**: Capture discovery findings, architectural investigations, and rationale that inform the technical design.

**Usage**:
- Log research activities and outcomes during the discovery phase.
- Document design decision trade-offs that are too detailed for `design.md`.
- Provide references and evidence for future audits or reuse.

**Project Context**: Universal LLM Proxy - FastAPI async, DI containers, staged initialization, adapter pattern.
---

## Summary
- **Feature**: `cross-layer-typed-data-contracts`
- **Discovery Scope**: Complex Integration (brownfield extension affecting multiple cross-layer seams)
- **Key Findings**:
  - The codebase already uses Pydantic v2 `DomainModel` and immutable `ValueObject` patterns, plus typed CBOR capture dataclasses and typed streaming contracts; the primary issue is inconsistent adoption at boundaries.
  - Multiple cross-layer interfaces still expose `Any` and ad hoc `dict[str, Any]` (especially in backend completion collaborators, response processing, and “context” dictionaries), which drives repeated normalization and defensive casting.
  - `RequestContext` is extended via dynamic attributes (`domain_request`, `raw_body`, `backend`), forcing `type: ignore[attr-defined]` and making cross-layer contracts implicit rather than explicit.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - Controllers and request adapters: `src/core/app/controllers/*`, `src/core/transport/fastapi/request_adapters.py`
  - Core orchestrators: `src/core/services/request_processor_service.py`, `src/core/services/backend_request_manager_service.py`, `src/core/services/backend_completion_flow/service.py`
  - Domain contracts: `src/core/domain/chat.py`, `src/core/domain/request_context.py`, `src/core/domain/responses.py`
  - Streaming contracts and serializer: `src/core/domain/streaming/contracts.py`, `src/core/domain/streaming/streaming_content.py`, `src/core/transport/streaming/sse_serializer.py`
  - Wire capture: `src/core/domain/cbor_capture.py`, `src/core/services/cbor_wire_capture_service.py`, `src/core/simulation/capture_reader.py`
  - Boundary interfaces: `src/core/interfaces/*` (notably `backend_completion_collaborators.py`, `response_processor_interface.py`, `request_processor_interface.py`)
- **Patterns Identified**:
  - Staged init + DI with `src/core/di/container.py` and stage wiring in `src/core/app/stages/`.
  - Pydantic v2 models for many domain types; `ValueObject` uses `ConfigDict(frozen=True)` for immutability.
  - Streaming has an emerging “typed-first with fallback” pattern (`StreamingChunk` + `StreamingContent` conversions).
  - Some legacy signatures intentionally allow broad unions (`DomainModel | InternalDTO | dict[str, Any]`) for compatibility.
- **Implications**:
  - The highest-leverage improvements are at boundary seams (context, collaborators, response processing) rather than introducing entirely new domain models.
  - A design must minimize duplicated representations by selecting a “canonical” type per concept and providing compatibility adapters at explicit boundaries.

### Pydantic v2: Frozen Value Objects and JSON-serializable Value Types
- **Context**: The feature requires immutable-ish contracts and constrained extension fields.
- **Sources Consulted**:
  - Pydantic models concept docs (immutability / frozen models): https://docs.pydantic.dev/latest/concepts/models/
  - Pydantic types API (JSON value type alias): https://docs.pydantic.dev/latest/api/types/
- **Findings**:
  - Pydantic v2 supports frozen models via `ConfigDict(frozen=True)` and safe copy-on-write via `model_copy(update=...)`.
  - Pydantic provides `pydantic.types.JsonValue` as a recursive type alias for values that can be serialized to JSON, suitable for constraining “extension” payloads without using `Any`.
- **Implications**:
  - Cross-layer extension fields should standardize on `JsonValue` (or `dict[str, JsonValue]`) instead of `dict[str, Any]`.
  - Copy-on-write should be expressed using existing `ValueObject` conventions (avoid in-place mutation of domain payloads).

### Python dataclasses: Frozen and slots for internal DTOs
- **Context**: Some contracts (captures, internal envelopes) may be better represented as dataclasses.
- **Sources Consulted**:
  - Python `dataclasses` docs (frozen and slots): https://docs.python.org/3/library/dataclasses.html
- **Findings**:
  - `@dataclass(frozen=True, slots=True)` is an idiomatic approach for immutable, low-overhead internal DTOs.
- **Implications**:
  - CBOR capture models already use this pattern; additional internal, performance-sensitive contracts can follow it.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing types | Tighten current domain models and interfaces; add explicit fields to `RequestContext` | Lower conceptual overhead, preserves runtime behavior | Cross-cut change surface; requires discipline to avoid mixed-mode duplication | Viable for incremental rollout |
| New contracts layer | Introduce a fresh “canonical contracts” module and adapt all layers | Clear greenfield contracts, clean boundaries | High migration cost; duplication during transition | Risky in this brownfield codebase |
| Hybrid (recommended) | Fix highest-leverage seams first (context, collaborator interfaces, extension field typing), then converge representations | Early wins, reduces `Any` and conversion churn incrementally | Needs explicit migration plan and invariants to avoid permanent duplication | Best fit for the current architecture |

## Design Decisions

### Decision: Canonical request contract selection
- **Context**: Multiple layers pass “chat completion request” data.
- **Alternatives Considered**:
  1. Use `ChatRequest` everywhere
  2. Use `CanonicalChatRequest` everywhere
- **Selected Approach**: Prefer `CanonicalChatRequest` as the internal canonical request contract, while accepting `ChatRequest` at outer boundaries where needed.
- **Rationale**: The codebase already treats `CanonicalChatRequest` as the internal contract and many connectors assert it at runtime.
- **Trade-offs**: Some legacy signatures remain broad for compatibility; strictness is enforced by adapters and typed overloads rather than immediate signature breaks.
- **Follow-up**: Inventory remaining call sites that pass dicts to processor/connectors and define an explicit deprecation plan.

### Decision: Extension payload typing
- **Context**: `extra_body`, tools, and protocol/vendor-specific fields require flexibility but must not degrade cross-layer typing.
- **Alternatives Considered**:
  1. `dict[str, Any]` (status quo)
  2. `dict[str, pydantic.types.JsonValue]`
  3. A bespoke set of Pydantic models for each vendor/protocol extension area
- **Selected Approach**: Standardize extension values on `JsonValue` and reserve bespoke models for high-value, frequently accessed fields.
- **Rationale**: `JsonValue` provides a strong default that is serializable and mypy-friendly, while keeping design/implementation effort tractable.
- **Trade-offs**: Some semantic validation remains deferred until a field is promoted to a first-class model.
- **Follow-up**: Document an “extension promotion” process (how/when to convert loose extension keys into typed models).

### Decision: Contract file placement and ownership
- **Context**: New canonical contracts must be created consistently to avoid duplication and naming drift.
- **Alternatives Considered**:
  1. Place new contracts adjacent to their first consumer (service-local)
  2. Place new contracts in `src/core/domain/` as shared, cross-layer value objects
- **Selected Approach**: Place shared cross-layer contracts in `src/core/domain/` with explicit file placement:
  - `BackendTarget` in `src/core/domain/backend_target.py`
  - `UsageSummary` in `src/core/domain/usage_summary.py`
- **Rationale**: These contracts are exchanged across domains (routing, completion orchestration, capture, usage) and should not be owned by any single service module.
- **Trade-offs**: Requires careful rollout to avoid breaking imports; mitigated by phased adoption and compatibility façades.

### Decision: Request context enrichment strategy
- **Context**: Dynamic attributes on `RequestContext` undermine cross-layer typing and require `type: ignore`.
- **Alternatives Considered**:
  1. Keep dynamic attributes and rely on type ignores
  2. Add explicit optional fields to `RequestContext` for common cross-layer data
  3. Introduce a separate `RequestContextExtensions` object stored on `RequestContext`
- **Selected Approach**: Add explicit optional fields for frequently used cross-layer data (e.g., domain request, raw body, resolved target), keeping an extension dictionary only as a last resort.
- **Phase posture**: Phase A focuses on making `RequestContext` explicit and removing dynamic attributes first; higher-blast-radius envelope typing changes are deferred.
- **Rationale**: Eliminates attribute-defined ignores and makes boundary contracts explicit without changing control flow.
- **Trade-offs**: Requires coordinated updates to adapters and a small number of services/controllers.
- **Follow-up**: Enumerate all dynamic attributes currently used and classify them (field vs extension).

## Testing Strategy Research

### Existing Test Patterns
- Unit and integration tests exist and should remain stable for unrelated behavior.
- Streaming behavior is sensitive; typed streaming already has dedicated serializer logic.

### Coverage Requirements
- Prioritize characterization tests for:
  - Context construction and typed fields (transport adapter correctness)
  - Contract coercion (legacy dict inputs where still supported)
  - Streaming chunk canonicalization paths and done-marker handling
  - Wire capture round-trip decoding into canonical contracts (where feasible)

## Risks & Mitigations
- Risk: Broad, cross-cut change surface causes regressions in edge-case flows (especially streaming and translation).
  - Mitigation: Phase the rollout; keep compatibility façades; add characterization tests at boundaries first.
- Risk: Performance regressions from copy-on-write (`model_copy`) on large payloads.
  - Mitigation: Restrict copy-on-write to mutation points; avoid deep-copy; do not buffer streaming content.
- Risk: Capture “round-trip” expectations conflict with byte-precise capture fidelity.
  - Mitigation: Treat raw bytes as source-of-truth; decode into canonical contracts as a best-effort diagnostic path, not as a replacement for raw capture fidelity.

## Performance Considerations
- Prefer immutable value objects for payloads and `@dataclass(frozen=True, slots=True)` for internal DTOs.
- Avoid repeated conversions between dict and Pydantic models during a single request lifecycle.
- Preserve time-to-first-byte for streaming by avoiding buffering solely for typing/conversion.

## References
- Pydantic v2 models (immutability): https://docs.pydantic.dev/latest/concepts/models/
- Pydantic `JsonValue` type alias: https://docs.pydantic.dev/latest/api/types/
- Python dataclasses (frozen/slots): https://docs.python.org/3/library/dataclasses.html
- Project steering: `.kiro/steering/tech.md`, `.kiro/steering/structure.md`
- Key code anchors:
  - `src/core/domain/chat.py`
  - `src/core/domain/request_context.py`
  - `src/core/domain/streaming/contracts.py`
  - `src/core/services/backend_completion_flow/service.py`
  - `src/connectors/base.py`
