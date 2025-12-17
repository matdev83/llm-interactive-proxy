# Gap Analysis: Cross-Layer Typed Data Contracts

## Executive Summary

The codebase already contains several strong foundations for typed cross-layer contracts (Pydantic v2 `DomainModel`, immutable `ValueObject`, `CanonicalChatRequest`, typed streaming contracts, and CBOR capture dataclasses). The primary gap is inconsistency: many boundary interfaces still expose `Any`/ad hoc `dict` shapes, `RequestContext` is extended via dynamic attributes (`context.domain_request`, `context.raw_body`, `context.backend`), and multiple parallel representations exist for the same concepts (streaming chunks, response envelopes, usage).

This feature is feasible but broad: it touches transport adapters, request processing, backend completion flow, connectors, streaming pipeline, wire capture, and translation layers. The main integration challenge is preserving external behavior while tightening types, especially for multi-protocol translation and vendor-specific extensions.

**Effort**: XL (architectural cross-cut)

**Risk**: High (behavior preservation + many integration surfaces)

## 1. Current State Investigation

### Key assets already in place (typing + immutability)

- **Nominal model markers**
  - `src/core/interfaces/model_bases.py`: `DomainModel` (Pydantic v2) and `InternalDTO` (dataclass marker).
  - `src/core/domain/base.py`: `ValueObject` with `ConfigDict(frozen=True)` (immutable-by-default).
- **Canonical request/response concepts**
  - `src/core/domain/chat.py`: `ChatRequest`/`CanonicalChatRequest` (immutable), `ChatResponse`/`CanonicalChatResponse`, `CanonicalStreamChunk`.
- **Typed streaming contracts (already aligned with this feature’s intent)**
  - `src/core/domain/streaming/contracts.py`: `StreamingChunk`, `StreamingPayload`, `StreamingMetadata`, `StreamingUsage` (`extra="forbid"`).
  - `src/core/domain/streaming/streaming_content.py`: `StreamingContent` plus conversions to/from typed `StreamingChunk`.
  - `src/core/transport/streaming/sse_serializer.py`: typed-first SSE serialization with fallbacks.
- **Wire capture with typed entries**
  - `src/core/domain/cbor_capture.py`: frozen, slotted dataclasses (`CaptureEntry`, `CaptureMetadata`), round-trippable CBOR dictionaries.
  - `src/core/services/cbor_wire_capture_service.py`: byte-precise CBOR capture.
- **Traffic-leg framing (CTP/PTB/BTP/PTC)**
  - `src/core/domain/traffic_leg.py`: explicit cross-layer traffic segments used for observability/accounting.

### Active hotspots (untyped boundaries + conversion churn)

- **Transport ↔ Core context is not a strict contract**
  - `src/core/domain/request_context.py`: `RequestContext.state` and `.app_state` are `Any`, and controllers/services attach dynamic attributes.
  - `src/core/transport/fastapi/request_adapters.py`: builds `RequestContext` from FastAPI `Request`, but does not carry typed “domain request”/raw body fields.
  - Controllers set `ctx.domain_request` and `ctx.raw_body` via `type: ignore[attr-defined]` (e.g., `src/core/app/controllers/chat_controller.py`, `src/core/app/controllers/anthropic_controller.py`); `src/core/services/session_enricher.py` also sets `context.domain_request`.
- **Response envelopes and response processing remain weakly typed**
  - `src/core/domain/responses.py`: `ResponseEnvelope.content: Any`, `usage: dict[str, Any] | None`, `metadata: dict[str, Any] | None`.
  - `src/core/interfaces/response_processor_interface.py`: `ProcessedResponse.content: Any`, `context: dict[str, Any] | None`, streaming iterators of `Any`.
  - `src/core/transport/fastapi/response_adapters.py`: `domain_response_to_fastapi(domain_response: Any, ...)`.
- **Backend connector boundary is intentionally permissive**
  - `src/connectors/base.py`: `LLMBackend.chat_completions(request_data: DomainModel | InternalDTO | dict[str, Any], ...)`.
  - Many connectors enforce `ChatRequest` at runtime (e.g., `src/connectors/openai.py`, `src/connectors/anthropic.py`), but the shared type surface remains broad.
- **Backend completion flow collaborators expose `Any` despite typed implementations**
  - `src/core/interfaces/backend_completion_collaborators.py`: several collaborator interfaces accept/return `Any`, even though implementations use `ChatRequest`/`RequestContext` (`src/core/services/backend_completion_flow/*`).
- **Command pipeline types cause repeated normalization**
  - `src/core/domain/processed_result.py`: `modified_messages: list[Any]`, `command_results: list[Any]`.
  - `src/core/interfaces/command_processor_interface.py`: `messages: list[Any]` and returns `ProcessedResult`.
  - `src/core/services/backend_request_manager_service.py`: repeatedly normalizes `Any` messages into `ChatMessage`, converts dicts into models, and conditionally rebuilds requests via `model_copy`.
- **Extensions are primarily unstructured**
  - `src/core/domain/chat.py`: `tools: list[dict[str, Any]] | None`, `extra_body: dict[str, Any] | None`, plus multiple protocol-specific dict fields (`response_format`, `reasoning`, `generation_config`, etc.).
  - Translators often handle both dicts and models via `model_dump` fallbacks (e.g., Gemini tool translation).

### Dominant architecture patterns and constraints

- Staged initialization and DI (see `.kiro/steering/tech.md` for source-of-truth pointers).
- Cross-layer “domain envelope” idea exists (e.g., `ResponseEnvelope`, `StreamingResponseEnvelope`), but is not consistently strongly typed.
- Mypy is enabled but not strict; `disallow_untyped_defs = true` means new code must be annotated, but existing `Any`/dict shapes are common.

## 2. Requirements Feasibility Analysis

### Technical needs implied by the requirements

- A **canonical contract inventory** for cross-layer exchange: request payload, request context, backend target resolution, backend request, backend response, streaming chunk, usage/metrics, capture record.
- **Explicit boundary conversion points** (transport ↔ canonical, canonical ↔ provider payloads, canonical ↔ capture/replay/persistence).
- A **typed extension mechanism** for vendor/protocol-specific fields that must remain flexible without infecting core boundaries with `Any`.
- **Immutability and additive mutation** rules for contracts already using `ValueObject` patterns, plus a strategy for mutable per-request context.
- **Consistent, structured validation failures** mapped through the existing `LLMProxyError` hierarchy and FastAPI adapters.
- **Capture/replay contract strategy**: decide what it means to “round-trip” captured bytes into canonical contracts while preserving byte-precision.
- **Contributor guidance + enforcement** so new code does not regress to ad hoc cross-layer dicts.

### Gaps and constraints (tagged)

- **Missing**: A single, documented list of canonical contracts and allowed boundary conversions (Req 2, 4, 8).
- **Missing**: Typed `RequestContext` fields for `domain_request`, raw body, and commonly used derived attributes; current approach relies on dynamic attributes and `type: ignore` (Req 2–4).
- **Constraint**: External API shapes and connector expectations must remain stable (Req 1).
- **Constraint**: Wire capture is byte-precise; typed representations must not remove fidelity (Req 1, 7, NFR Security/Performance).
- **Unknown (Research Needed)**: Which extension fields should be promoted to first-class contracts vs left as explicit “extension” payloads (Req 2, 3, 8).
- **Unknown (Research Needed)**: How to represent “canonical response” and “canonical streaming chunk” given existing parallel models (`CanonicalStreamChunk`, `StreamingChunk`, `ProcessedResponse`, `StreamingContent`) (Req 2, 4, 5, 7).

## 3. Requirement-to-Asset Map (High Level)

| Requirement Area | Existing Asset(s) | Gap Tag | Notes |
|---|---|---:|---|
| 1. Compatibility | Controllers, transport adapters, tests, connectors | Constraint | Tightening types must not change client-visible schemas or behavior. |
| 2. Canonical contracts | `CanonicalChatRequest`, `RequestContext`, envelopes, streaming contracts, capture models | Missing | Coverage is incomplete and inconsistent; multiple parallel representations exist. |
| 3. Typed boundaries | `DomainModel`/`InternalDTO` markers, mypy enabled | Missing | Many public/protocol boundaries still use `Any`/`dict`. |
| 4. Explicit conversions | FastAPI adapters, translation service, connector payload builders | Missing | Conversions are spread and sometimes implicit (dynamic context attrs, repeated normalization). |
| 5. Immutability | `ValueObject` (frozen), CBOR capture dataclasses | Partial | Core payloads are often immutable; envelopes/context remain mutable/weakly typed. |
| 6. Validation + errors | Pydantic validation, `LLMProxyError` hierarchy, exception adapters | Partial | Some invariants are validated ad hoc; contract-construction errors are not uniformly structured. |
| 7. Capture + replay | CBOR capture entries and reader | Unknown | Capture is byte-oriented; “round-trip into contracts” needs a defined decoding strategy. |
| 8. Guidance + enforcement | Steering docs, existing domain models | Missing | No single contributor-facing contract policy for typed boundaries/extension fields. |

## 4. Implementation Approach Options

### Option A: Extend existing types in place (incremental tightening)

**Description**: Promote existing “almost canonical” types (`CanonicalChatRequest`, `ChatMessage`, `RequestContext`, `StreamingChunk`, capture models) and progressively narrow interface signatures and adapter outputs. Replace dynamic context attributes with typed optional fields and introduce explicit extension-field types.

**Pros**:
- Minimizes new conceptual layers; leverages existing domain models and patterns.
- Allows phased rollout (start at the most harmful boundaries).
- Easier to preserve behavior by keeping runtime objects largely the same.

**Cons**:
- Still touches many files; improvements are spread across the codebase.
- Risk of leaving “mixed-mode” periods where both typed and untyped paths coexist.

### Option B: Create a new dedicated “contracts” module set and adapt boundaries

**Description**: Define a clean set of new canonical contracts (request, context, backend request/response, streaming chunk, usage, capture) and make existing services adapt to them at boundaries, leaving older models as compatibility shapes.

**Pros**:
- Clean separation with clear “source of truth” contract types.
- Easier to reason about and document boundaries once adopted.

**Cons**:
- High migration cost and risk; duplication likely during transition.
- Requires careful compatibility façade to avoid widespread breakage.

### Option C: Hybrid (target highest-leverage boundaries first; converge representations)

**Description**: Prioritize the cross-layer seams with the biggest typing pain: `RequestContext` (dynamic attrs), connector boundary signatures, backend completion collaborators, and streaming representation convergence. Keep deep protocol/vendor payloads as constrained “extension fields” initially, with a documented promotion path.

**Pros**:
- Reduces risk by focusing on the most impactful seams first.
- Creates early wins (removes `type: ignore[attr-defined]`, reduces repeated normalization).
- Allows a deliberate choice of the canonical streaming representation with minimal disruption.

**Cons**:
- Requires strong design discipline to avoid permanent duplication.
- Needs explicit “promotion” rules so extensions don’t remain permanently untyped.

## 5. Implementation Complexity & Risk

- **Effort: XL (2+ weeks)** — Architectural cross-cut across transport adapters, request processing, backend completion, connectors, streaming, captures, and translation utilities; requires phased rollout and extensive regression validation.
- **Risk: High** — Tightening cross-layer types can easily surface latent behavior mismatches (especially streaming semantics, usage/capture accuracy, and multi-protocol translation).

## 6. Recommendations for the Design Phase (Information, not final decisions)

### Candidate “canonical contract set” to baseline in design

- Requests: `CanonicalChatRequest`, `ChatMessage` (+ clarified tool definitions and extension fields).
- Context: `RequestContext` with explicit typed optional fields for commonly attached attributes (domain request, raw body, backend target, request ID).
- Responses: decide whether `ResponseEnvelope.content` should be a small union (e.g., `ChatResponse`/`dict`/`bytes`) or a typed generic.
- Streaming: pick a single canonical representation (`StreamingChunk` vs `CanonicalStreamChunk` vs `ProcessedResponse`), and define compatibility adapters.
- Usage: adopt a common “usage envelope” shape (typed where possible) while preserving vendor-specific details via extension fields.
- Capture: define a “decode path” for replay (bytes → structured JSON → canonical contracts) while preserving the raw bytes as the fidelity source.

### Research Needed (carry into design)

1. **Context attribute inventory**: enumerate all dynamic `RequestContext` attributes used across services/controllers and classify them (must-be-field vs optional extension).
2. **Boundary `Any` inventory**: list public/protocol interfaces that still use `Any`/dict at cross-layer seams and rank by impact (connectors, translation, response processing, backend completion collaborators).
3. **Streaming convergence**: identify which streaming representation is used on each path (OpenAI connector pipeline vs other backends) and where conversion happens.
4. **Capture round-trip definition**: determine which directions/entries can be decoded into canonical contracts and what constitutes “round-trip” for byte-precise CBOR capture.
5. **Performance implications**: measure/estimate copy behavior from immutable `ValueObject` updates (`model_copy`) on hot paths (streaming and large payload requests).

### Key design decisions to make explicit

- Pydantic v2 vs dataclasses vs a mix for each contract category (payload vs context vs capture).
- Extension field typing strategy (constrained JSON type, TypedDict, or dedicated models).
- Backward compatibility strategy for connector and controller surfaces (compat façade vs signature tightening).

