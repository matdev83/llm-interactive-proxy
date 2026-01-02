# Gap Analysis: Typed Contracts Boundary Hardening

## Executive Summary

The codebase already has strong foundations for typed cross-layer contracts (Pydantic v2 domain models, immutable `ValueObject`s, typed `RequestContext`, typed streaming contracts, and capture/replay helpers). The primary gap is that boundary hardening is only partially realized: many boundary surfaces still expose `Any` and ad hoc `dict[str, Any]`, and the current enforcement script flags widespread violations in “boundary directories”.

**Primary evidence**: Running `dev/scripts/check_boundary_types.py` against the current boundary directory set (`src/core/interfaces`, `src/core/domain`, `src/core/transport`) reports **~638 violations**, with hotspots concentrated in the translation facade, transport response adapters, and domain request/translation modules.

**Effort**: XL (architectural cross-cut)  
**Risk**: High (behavior preservation + multi-protocol streaming/usage/capture seams)

## 1. Current State Investigation

### Key assets already in place

- **Canonical request context contract** with explicit typed fields:
  - `src/core/domain/request_context.py` (`domain_request`, `raw_body`, `backend`, `effective_model`, `extensions`, provenance tracking).
- **Canonical routing contract**:
  - `src/core/domain/backend_target.py` (`BackendTarget` with `uri_params: dict[str, JsonValue]`).
- **Canonical usage contract**:
  - `src/core/domain/usage_summary.py` (`UsageSummary` with typed extensions and conversion helpers).
- **Transport-agnostic response envelopes** supporting typed usage and JSON-safe metadata:
  - `src/core/domain/responses.py` (`usage: UsageSummary | None`, `metadata: dict[str, JsonValue] | None`).
- **Capture + replay typed views**:
  - `src/core/simulation/capture_decoder.py` (best-effort decode into canonical contracts with structured diagnostics).
- **Contributor guidance + a guardrail script**:
  - `docs/development_guide/typed-data-contracts.md` (policy + rules, including `dev/scripts/check_boundary_types.py`).
  - `dev/scripts/check_boundary_types.py` (AST checker for `Any` / `dict[str, Any]` in boundary signatures).

### Active hotspots (untyped boundaries + conversion churn)

**1) Boundary guardrails currently fail at scale**

- `dev/scripts/check_boundary_types.py` scans `src/core/interfaces`, `src/core/domain`, and `src/core/transport` and currently reports ~638 signature violations.
- Largest offenders by violation count (current snapshot):
  - `src/core/domain/translation.py` (~61)
  - `src/core/transport/fastapi/adapters/streaming/content_converter.py` (~18)
  - `src/core/transport/fastapi/response_adapters.py` (~16)
  - `src/core/transport/fastapi/adapters/protocols.py` (~15)
  - `src/core/interfaces/feature_parity.py` (~15)
  - `src/core/domain/chat.py` (~13)

**2) Canonical request payload still carries multiple ad hoc dict-shaped extension fields**

- `src/core/domain/chat.py` `ChatRequest`/`CanonicalChatRequest` contains multiple `dict[str, Any]` fields (`tools`, `tool_choice`, `extra_body`, `response_format`, `reasoning`, `generation_config`, etc.). This conflicts with the “single extension container + JSON-serializable values” objective unless the policy explicitly treats these as legacy compatibility surfaces.

**3) Streaming/response adapter boundary protocols use `Any`**

- Response adapter protocols and streaming conversion code use `Any`/`dict[str, Any]` heavily:
  - `src/core/transport/fastapi/adapters/protocols.py`
  - `src/core/transport/fastapi/adapters/streaming/content_converter.py`
  - `src/core/transport/fastapi/response_adapters.py`
- A key design tension exists: streaming adapters must be flexible enough to accept provider-shaped SSE chunks while still exposing typed processed chunk contracts across cross-layer seams.

**4) Connector seam is still permissive and is not covered by the current guardrail script**

- The connector base interface remains permissive:
  - `src/connectors/base.py` `LLMBackend.chat_completions(request_data: DomainModel | InternalDTO | dict[str, Any], processed_messages: list, **kwargs: Any)`
- `dev/scripts/check_boundary_types.py` does not include `src/connectors/` in `is_boundary_module`, so it currently cannot enforce connector seam hardening.

**5) “Legacy dict context” compatibility remains in core services**

- Some core orchestration APIs still accept `RequestContext | dict[str, Any]` and perform best-effort coercion internally (e.g., `src/core/services/backend_request_manager_service.py`). This keeps legacy representations alive beyond explicit adapter boundaries.

### Existing conventions and constraints relevant to the work

- **Staged init + DI** are the preferred integration mechanisms (`src/core/app/stages/`, `src/core/di/`).
- **Mypy posture is not strict**, but untyped defs are disallowed; tightening boundary types tends to surface latent “shape drift” quickly.
- **External behavior preservation** is critical: multi-protocol translation and streaming semantics are high-risk surfaces for subtle regressions.

## 2. Requirement-to-Asset Map (with Gaps)

| Requirement | Existing Assets | Gaps / Constraints |
|------------|------------------|-------------------|
| 1. Compatibility | Existing controllers, translators, response adapters, capture tooling | Tightening types risks behavior drift in multi-protocol and streaming paths; regression coverage must be comprehensive. |
| 2. Canonical boundary contracts | `RequestContext`, `BackendTarget`, `UsageSummary`, response envelopes, typed streaming contracts exist | Many boundary interfaces still accept/return `Any` or `dict[str, Any]` (transport adapters, translation facade, command/response processing seams). |
| 3. Guardrails | `dev/scripts/check_boundary_types.py`, `docs/development_guide/typed-data-contracts.md` | Guardrail currently fails (~638 violations) and its scope (`src/core/domain`) likely includes internal modules that may need allowlisting or refactoring; connector seam not covered. |
| 4. Connector contract hardening | Some callers pass canonical requests already | `LLMBackend.chat_completions` still accepts dicts and untyped processed messages; migration + compatibility shims required. |
| 5. Explicit conversion points | Transport request adapter exists, ResponseEnvelope exists | Legacy dict coercion still occurs inside core orchestration; conversions are not fully centralized at explicit adapter boundaries. |
| 6. Typed usage/metadata boundaries | `UsageSummary` exists, some envelopes use it | Usage/metadata normalizers and adapter protocols still operate on `dict[str, Any]`; streaming usage aggregation remains a hotspot. |
| 7. Capture/replay alignment | `CaptureDecoder` best-effort decode exists | Capture collaborator seams still accept `Any`/`dict[str, Any]` in places; need clearer canonical usage/capture contracts at these seams. |
| 8. Contributor guidance | Typed contract doc exists | Guidance exists but enforcement is currently not passing; policy vs guardrail scope needs reconciliation (what counts as “boundary”). |

## 3. Implementation Approach Options

### Option A: Extend and tighten existing components in place (incremental hardening)

**Description**: Progressively replace `Any`/`dict[str, Any]` at boundary seams with canonical contracts and JSON-serializable types. Add compatibility shims only at explicitly named adapter boundaries.

**Pros**:
- Minimizes new conceptual surface area; leverages existing canonical contracts.
- Easier to preserve behavior by keeping runtime data mostly identical and limiting conversions.

**Cons**:
- Touches many files; scope can balloon if “boundary” includes broad domain modules (e.g., translation).
- Requires careful phased rollout and continuous regression testing.

### Option B: Introduce a new dedicated “contracts v2” module set + migration adapters

**Description**: Define new v2 boundary contracts (request, response, streaming chunk, connector options) and adapt existing code at boundaries, treating current contracts as legacy compatibility types.

**Pros**:
- Clear separation between “new canonical boundary types” and legacy representations.
- Potentially easier to enforce rules for v2 modules (narrow guardrail scope).

**Cons**:
- High migration/duplication cost; risk of parallel representations persisting.
- Increased cognitive load during the transition period.

### Option C: Hybrid (policy + guardrail first; then harden highest-leverage seams)

**Description**: Start by reconciling the “typed boundary policy” with the enforcement mechanism, then harden the highest-leverage seams in phases: connector seam, transport response/streaming seams, legacy dict contexts, and finally translation/command pipeline surfaces.

**Pros**:
- Early clarity on enforcement scope reduces churn and avoids “boil the ocean” refactors.
- De-risks the effort by focusing on the highest-impact seams first.

**Cons**:
- Requires disciplined scoping and explicit decisions about what remains allowlisted vs. refactored.

## 4. Implementation Complexity & Risk

- **Effort: XL (2+ weeks)** — Widespread boundary signature changes across interfaces, transport adapters, and connectors, plus follow-on refactors to reduce ad hoc dict usage and stabilize streaming/usage/capture seams.
- **Risk: High** — Streaming performance and multi-protocol translation are particularly sensitive to subtle behavior changes; connector compatibility may require a well-defined migration strategy.

## 5. Recommendations for the Design Phase (Information, not final decisions)

### Likely preferred approach

- **Option C (Hybrid)** is the most practical: align policy + enforcement first, then harden the most valuable seams with compatibility shims.

### Research Needed (carry into design)

1. **Boundary definition reconciliation**: decide which subtrees/files truly count as “boundary surfaces” for enforcement, and whether the guardrail should include `src/core/domain` broadly or only selected modules/types.
2. **Connector seam contract**: define the target `LLMBackend.chat_completions` signature (canonical request + typed processed messages + typed options), and a migration strategy that preserves existing connectors/tests.
3. **Canonical request extension strategy**: decide how to replace or constrain `ChatRequest` fields that currently use `dict[str, Any]` (tools, extra_body, response_format, etc.) while preserving client-visible API compatibility.
4. **Streaming canonicalization**: define which streaming representation is canonical at which seams (raw bytes, decoded SSE payload, typed streaming contract, `ProcessedResponse`, etc.) and where conversions are permitted.
5. **Usage/metadata convergence**: decide how to standardize usage aggregation and metadata propagation using `UsageSummary` and JSON-safe metadata without adding per-chunk overhead.
6. **Capture collaborator contracts**: determine typed contracts for capture/identity/canonical usage that remove `Any`/`dict[str, Any]` from collaborator interfaces while preserving CBOR fidelity and replay tooling.

