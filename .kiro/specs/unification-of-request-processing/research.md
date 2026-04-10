# Research & Design Decisions: unification-of-request-processing

## Summary
- **Feature**: `unification-of-request-processing`
- **Discovery Scope**: complex brownfield convergence across manager orchestration, response middleware, transport adapters, and connectors
- **Key Findings**:
  - The codebase already proves the value of stream-first internals in `UnifiedResponsePipeline` and Gemini base orchestration, but that precedent stops below the current `BackendRequestManager` split.
  - Phase 1 should converge the system at the **current post-backend-response manager boundary**, not by immediately rewriting connector execution.
  - `ProcessedResponse` is already the canonical chunk unit, but it is **not sufficient by itself** at the current manager boundary because envelope metadata such as status, headers, media type, cancellation behavior, and usage must survive through adaptation.
  - The highest-risk areas are not conceptual stream unification, but compatibility-critical safeguards: dedup completion tracking, empty-response and empty-stream recovery, tool-call retry coordination, loop detection, quality verifier behavior, and transport/disconnect semantics.

## Research Log

### Current split point and true Phase 1 boundary
- **Context**: Determine where the first safe migration cut line really is.
- **Sources Consulted**:
  - `src/core/services/backend_request_manager_service.py`
  - `src/core/interfaces/backend_processor_interface.py`
  - `src/core/services/backend_processor.py`
- **Findings**:
  - `BackendRequestManager.process_backend_request()` performs shared preamble work, calls `IBackendProcessor.process_backend_request()`, then branches on `backend_request.stream`.
  - The streaming branch delegates to `BackendStreamingResponseHandler.handle()` and may later wrap the returned iterator for dedup completion tracking.
  - The non-streaming branch delegates to `BackendNonStreamingResponseHandler.handle()`.
- **Implications**:
  - Phase 1 should replace only the **post-backend-response branch**, not the backend-processor call itself.
  - This keeps the first migration stage bounded and compatible with the current DI graph and connector contracts.

### Why `ProcessedResponse` is necessary but not sufficient
- **Context**: Confirm the canonical chunk type and determine whether it can be the only Phase 1 contract.
- **Sources Consulted**:
  - `src/core/interfaces/response_processor_interface.py`
  - `src/core/domain/responses.py`
  - `src/core/services/response_pipeline.py`
  - `src/core/services/streaming/non_streaming_adapter.py`
- **Findings**:
  - `ProcessedResponse` is already the streaming chunk type used by `StreamingResponseEnvelope.content` and `IResponseProcessor.process_streaming_response()`.
  - `UnifiedResponsePipeline` already treats non-streaming as a wrapped single-chunk stream.
  - The current manager boundary still depends on envelope-level metadata carried by `ResponseEnvelope` and `StreamingResponseEnvelope`, including `status_code`, `headers`, `media_type`, `cancel_callback`, and usage records.
- **Implications**:
  - Phase 1 needs a richer internal contract than `AsyncIterator[ProcessedResponse]` alone.
  - The design therefore introduces `CanonicalResponseHandle`, which carries the canonical chunk stream plus the envelope metadata needed by compatibility adapters.

### Handler asymmetry is the main migration challenge
- **Context**: Determine whether the two handlers can be trivially merged into one stream-first coordinator.
- **Sources Consulted**:
  - `src/core/services/backend_non_streaming_response_handler.py`
  - `src/core/services/backend_request_manager/streaming_response_handler.py`
  - `tests/unit/core/services/test_backend_non_streaming_response_handler.py`
  - `tests/unit/core/services/test_backend_streaming_response_handler.py`
- **Findings**:
  - The non-streaming handler owns empty-response retry, structured-output enforcement, metadata filtering, and non-stream tool-call retry coordination.
  - The streaming handler owns middleware wrapping, quality-verifier buffering, loop detection, empty-stream recovery, tool-call retry coordination, status extraction, and stream lifecycle behavior.
  - Several behaviors are structurally different, not just duplicated implementations with different shapes.
- **Implications**:
  - The new coordinator must converge **shared business flow** without pretending all current behavior is already mode-agnostic.
  - Safeguard-sensitive behavior must either be deliberately converged, wrapped behind explicit adapters, or documented as temporary mode-specific exceptions.

### Dedup completion tracking is a compatibility-critical invariant
- **Context**: Validate whether deduplication can be treated as preamble-only logic.
- **Sources Consulted**:
  - `src/core/services/backend_request_manager_service.py`
  - `tests/unit/core/services/test_backend_request_manager_deduplication.py`
  - `tests/integration/test_backend_request_manager_e2e.py`
- **Findings**:
  - Duplicate short-circuit behavior happens before backend execution.
  - Streaming dedup completion tracking is applied **after** handler processing by wrapping the final returned stream.
  - Existing tests cover disconnect-before-completion, disconnect-after-`[DONE]`, `finish_reason=stop`, and `finish_reason=error` classification.
- **Implications**:
  - Dedup cannot be described only as "shared preamble logic".
  - Phase 1 must preserve the current streaming completion wrapper until equivalent canonical behavior is proven.

### Feature migration requires typed lifecycle context and an audit
- **Context**: Validate whether legacy response features can all be bridged by delegating canonical chunks through `process_streaming()`.
- **Sources Consulted**:
  - `src/core/interfaces/response_processor_interface.py`
  - `src/core/services/empty_response_middleware.py`
  - `src/core/services/structured_output_middleware.py`
  - `src/core/services/think_tags_fix_middleware.py`
  - `src/core/app/middleware/json_repair_middleware.py`
  - `src/core/interfaces/feature_parity.py`
  - `src/core/services/feature_parity_registration.py`
- **Findings**:
  - `IResponseFeature` enforces separate `process_non_streaming()` and `process_streaming()` methods.
  - Several feature implementations depend on stream-end or full-response semantics, not only per-chunk transformation.
  - The existing parity registry proves drift detection value, but it does not remove duplication.
- **Implications**:
  - A blanket `LegacyFeatureAdapter -> process_streaming()` strategy is unsafe.
  - The design needs a typed `CanonicalFeatureContext` and a **feature audit** that classifies each feature as chunk-safe, terminal-sensitive, full-response-sensitive, or explicit exception.

### Transport and disconnect behavior must remain boundary-aware
- **Context**: Validate the compatibility risks at the HTTP/SSE boundary.
- **Sources Consulted**:
  - `src/core/transport/fastapi/response_adapters.py`
  - `src/core/app/controllers/chat_controller.py`
  - `tests/integration/transport/fastapi/test_response_adapters_integration.py`
  - `tests/unit/test_transport_adapters.py`
- **Findings**:
  - `domain_response_to_fastapi()` still branches by response envelope type.
  - `StreamingResponseEnvelope` behavior includes SSE framing, response conversion, cancellation callbacks, and disconnect cleanup paths.
  - Existing tests pin non-streaming JSON behavior and streaming `text/event-stream` behavior, including `[DONE]` semantics.
- **Implications**:
  - External transport adaptation must remain at the boundary during migration.
  - The canonical path must preserve the information those adapters need rather than trying to bypass them in Phase 1.

### Connector migration should be delayed until the manager-level path is proven
- **Context**: Determine whether connector convergence should happen in Phase 1.
- **Sources Consulted**:
  - `src/connectors/openai.py`
  - `src/connectors/anthropic.py`
  - `src/connectors/gemini.py`
  - `src/connectors/gemini_cloud_project.py`
  - `src/connectors/gemini_base/orchestrator.py`
- **Findings**:
  - Main providers still have explicit stream and non-stream entry paths.
  - Gemini base orchestration provides the strongest stream-first precedent.
  - Connector heterogeneity remains significant enough that immediate connector-level unification would widen migration risk unnecessarily.
- **Implications**:
  - Provider-by-provider connector convergence belongs in Phase 3 after the manager-level canonical contract is stable.

### Existing validation surface is already rich enough to anchor migration gates
- **Context**: Determine whether the codebase already has enough behavioral evidence to support characterization-first migration.
- **Sources Consulted**:
  - `tests/unit/core/services/test_backend_request_manager_deduplication.py`
  - `tests/unit/core/services/test_backend_non_streaming_response_handler.py`
  - `tests/unit/core/services/test_backend_streaming_response_handler.py`
  - `tests/unit/core/services/test_quality_verifier_stream_verifier.py`
  - `tests/unit/core/services/test_response_processor_quality_verifier.py`
  - `tests/integration/test_backend_request_manager_e2e.py`
  - `tests/integration/test_quality_verifier_integration.py`
  - `tests/integration/transport/fastapi/test_response_adapters_integration.py`
- **Findings**:
  - The repository already contains meaningful tests for dedup behavior, empty-response retry, loop detection, quality verifier behavior, and transport adaptation.
  - Some of these tests are direct candidates for migration characterization baselines rather than new test invention.
- **Implications**:
  - The spec should treat characterization and evidence mapping as first-class preconditions, not as late cleanup work.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend dual paths | Keep dual contracts, add more shared helpers | Lowest immediate risk | Structural duplication remains and safeguard drift continues | Useful only for local cleanup |
| Full convergence big-bang | Replace handlers, features, transport assumptions, and connectors in one pass | Maximum simplification | Very high regression risk and weak rollback story | Not suitable for this brownfield path |
| Phased hybrid convergence | Converge first at the real manager boundary, then migrate features and connectors with gates | Best balance of simplification and control | Requires disciplined rollout and evidence tracking | Recommended |

## Design Decisions

### Decision: Phase 1 converges at the current manager boundary
- **Context**: The earliest large split is in `BackendRequestManager`, but `IBackendProcessor` already encapsulates backend execution and connector routing.
- **Selected Approach**: Keep `IBackendProcessor` unchanged in Phase 1 and replace only the post-backend-response handler branch with a gated canonical path.
- **Rationale**: This is the safest high-leverage cut line.
- **Trade-offs**: Connector duplication remains temporarily.
- **Follow-up**: Migrate connectors only after manager-level convergence is stable.

### Decision: Introduce `CanonicalResponseHandle` instead of using only `ProcessedResponse`
- **Context**: The canonical chunk type exists, but envelope metadata must survive until boundary adaptation.
- **Selected Approach**: Use `ProcessedResponse` as the canonical chunk unit and wrap it in a manager-level canonical handle that preserves envelope metadata.
- **Rationale**: Preserves compatibility without inventing a second chunk abstraction.
- **Trade-offs**: Temporary internal compatibility layer.
- **Follow-up**: Retire the handle only when public envelope dependency is sufficiently reduced.

### Decision: Use typed feature lifecycle context and constrained legacy adapters
- **Context**: Existing features are not uniformly chunk-safe.
- **Selected Approach**: Introduce typed canonical feature context and allow legacy bridging only for audit-approved features.
- **Rationale**: Prevents the migration from silently breaking terminal-sensitive or full-response-sensitive behavior.
- **Trade-offs**: Requires an explicit feature audit up front.
- **Follow-up**: Maintain a feature audit artifact during implementation.

### Decision: Treat safeguard characterization as a prerequisite, not a trailing validation step
- **Context**: Most migration risk lives in behavior that already has tests and operational meaning.
- **Selected Approach**: Pin current safeguard behavior before structural refactoring.
- **Rationale**: Makes rollback and promotion decisions evidence-based.
- **Trade-offs**: More up-front test organization work.
- **Follow-up**: Keep invariant and promotion-evidence guidance embedded in `design.md` and `tasks.md` so the main Kiro docs remain the source of truth.

## Risks and Mitigations
- **Transport contract drift** — Mitigate with boundary-level compatibility tests for SSE framing, terminal signaling, errors, and non-streaming payload shape.
- **Dedup completion tracking drift** — Mitigate with explicit preservation of the current streaming wrapper until an equivalent canonical mechanism is proven.
- **Safeguard regression in retry, loop detection, tool-call retry, or quality verifier** — Mitigate with characterization tests and phased convergence rather than forced early unification.
- **Feature migration mistakes** — Mitigate with typed lifecycle context and an explicit feature audit.
- **Connector overreach in early phases** — Mitigate by keeping connector migration out of Phase 1.

## References
- `src/core/services/backend_request_manager_service.py` — current split branch and dedup completion wrapper
- `src/core/services/backend_non_streaming_response_handler.py` — non-stream safeguard ownership
- `src/core/services/backend_request_manager/streaming_response_handler.py` — streaming safeguard ownership
- `src/core/services/response_pipeline.py` — existing internal stream-first unification precedent
- `src/core/services/streaming/non_streaming_adapter.py` — non-stream-as-stream adaptation precedent
- `src/core/transport/fastapi/response_adapters.py` — transport boundary behavior and disconnect cleanup
- `src/connectors/gemini_base/orchestrator.py` — proven stream-first accumulation example in connectors
- `tests/unit/core/services/test_backend_request_manager_deduplication.py` — streaming dedup and completion tracking invariants
- `tests/unit/core/services/test_backend_non_streaming_response_handler.py` — non-stream retry and validation invariants
- `tests/unit/core/services/test_backend_streaming_response_handler.py` — loop detection, cancel callback, and streaming safeguard invariants
- `tests/integration/transport/fastapi/test_response_adapters_integration.py` — boundary compatibility coverage
