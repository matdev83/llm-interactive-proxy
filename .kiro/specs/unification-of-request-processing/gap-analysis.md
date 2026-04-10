# Gap Analysis: unification-of-request-processing

## 0. Context and Preconditions

- Requirements, design, and tasks are approved enough for implementation planning (`phase=tasks-approved` in `spec.json`).
- This is a brownfield architectural convergence effort with a large compatibility and safeguard surface.
- The purpose of this gap analysis is no longer to pick a broad direction; it is to record the **remaining implementation gaps** a fresh session must understand before coding.

## 1. Current State Investigation

### Key files and modules

**Core orchestration and response flow**
- `src/core/services/request_processor_service.py`
- `src/core/services/backend_request_manager_service.py`
- `src/core/services/backend_non_streaming_response_handler.py`
- `src/core/services/backend_request_manager/streaming_response_handler.py`
- `src/core/transport/fastapi/response_adapters.py`
- `src/core/app/controllers/chat_controller.py`

**Existing unification assets**
- `src/core/services/response_pipeline.py` (`UnifiedResponsePipeline`)
- `src/core/services/streaming/non_streaming_adapter.py`
- `src/core/services/response_processor_service.py`
- `src/connectors/gemini_base/orchestrator.py`

**Dual-path contracts and parity infrastructure**
- `src/core/interfaces/response_processor_interface.py`
- `src/core/interfaces/backend_request_manager_components.py`
- `src/core/interfaces/feature_parity.py`
- `src/core/services/feature_parity_registration.py`
- `src/core/di/registration_helpers/request_processing/_rp_backend_components.py`

**Representative existing verification surface**
- `tests/unit/core/services/test_backend_request_manager_deduplication.py`
- `tests/unit/core/services/test_backend_non_streaming_response_handler.py`
- `tests/unit/core/services/test_backend_streaming_response_handler.py`
- `tests/unit/core/services/test_quality_verifier_stream_verifier.py`
- `tests/unit/core/services/test_response_processor_quality_verifier.py`
- `tests/integration/test_backend_request_manager_e2e.py`
- `tests/integration/test_quality_verifier_integration.py`
- `tests/integration/transport/fastapi/test_response_adapters_integration.py`

### Dominant patterns and constraints

1. **The first high-leverage split is manager-level, not connector-level**
   - `BackendRequestManager` performs the main requested-mode branch after `IBackendProcessor` returns.
   - This is the safest Phase 1 convergence boundary.

2. **`ProcessedResponse` is already canonical at chunk level**
   - It is already used across the streaming pipeline.
   - The remaining gap is preserving envelope metadata at the current manager boundary.

3. **Handlers contain materially different safeguard flows**
   - The non-streaming and streaming handlers are not just shape variants.
   - They own different retry, buffering, loop-detection, and completion behaviors.

4. **Feature parity tooling proves the problem but does not solve it**
   - Current parity infrastructure detects drift between dual implementations.
   - It does not remove the need for dual-path code.

5. **Transport and disconnect behavior remain boundary-critical**
   - `domain_response_to_fastapi()` still branches by envelope type.
   - Disconnect cleanup, cancellation callbacks, and SSE framing must remain stable through migration.

6. **Connector unification is still real work, but it is not the first gap to close**
   - Connector heterogeneity is significant enough that pushing convergence there too early would widen risk.

## 2. Requirement Feasibility Analysis

### Requirement-to-asset map with remaining gaps

| Requirement | Existing Assets | Gap Tags | Current Gap |
|---|---|---|---|
| R1 Canonical Processing Path | `UnifiedResponsePipeline`, `NonStreamingAdapter`, `ResponseProcessor` | Missing, Constraint | Need a manager-level canonical contract and coordinator that preserve envelope metadata while removing post-backend-response dual business flow. |
| R2 External Behavior Compatibility | transport adapters, controllers, response adapter tests | Constraint | Need canonical-to-envelope adaptation that keeps SSE, JSON, status, header, and error behavior stable. |
| R3 Connector Contract Simplification | Gemini base stream-first precedent | Missing, Deferred | Need provider-by-provider migration after manager-level canonical path is proven. |
| R4 Feature Parity by Construction | `IResponseFeature`, parity registry, parity tests | Missing, Constraint | Need typed canonical feature context and a feature audit before legacy features can be bridged safely. |
| R5 Reliability and Safeguards | dedup, retries, cancellation, loop detection, quality verifier logic | Constraint, High Risk | Need explicit preservation plans for safeguard behaviors that currently differ structurally by mode. |
| R6 Migration Safety and Incremental Adoption | staged startup, DI seams, existing tests | Missing | Need migration config, gates, path-selection diagnostics, and promotion criteria wired into runtime and validation workflow. |
| R7 Performance and Resource Safety | existing tests plus transport cleanup hooks | Missing | Need codified guardrails for non-stream latency, streaming TTFT, memory, and cleanup correctness. |

## 3. Concrete Gaps That Still Matter Before Coding

### Missing implementation artifacts
1. **`CanonicalResponseHandle`** at the manager boundary.
2. **`CanonicalResponseCoordinator`** that consumes the existing backend envelope in Phase 1.
3. **`EnvelopeCompatibilityAdapter`** that maps canonical handles back to `ResponseEnvelope` and `StreamingResponseEnvelope`.
4. **`CanonicalFeatureContext`** and feature audit results.
5. **Migration gate config and diagnostics** integrated with current config precedence rules.
6. **Verification matrix and invariants mapping** that tell a fresh session what evidence is required before each phase promotion.

### Constraints that must remain explicit
1. Public SSE and non-streaming contracts cannot drift.
2. Streaming dedup completion tracking cannot be lost or weakened.
3. Empty-response and empty-stream recovery cannot be hand-waved as generic chunk processing.
4. Tool-call retry and quality verifier behavior remain compatibility-sensitive and may need temporary adapters.
5. DI must support additive rollout and fallback branches until retirement.

### Unknowns that require staged discovery, not speculation
1. Which response features are truly chunk-safe.
2. Which provider cohorts are the safest first connector migration targets.
3. The acceptable non-stream latency and streaming TTFT deltas for production promotion.
4. Whether any current safeguard behavior should remain explicit mode exceptions through Phase 2.

## 4. Implementation Approach Options Revisited

### Option A: Keep dual handlers and extract more helpers

**Strengths**
- Lowest immediate change risk.

**Why it still falls short**
- Does not remove the main manager-level architectural split.
- Keeps parity policing instead of parity by construction.
- Offers limited long-term simplification.

### Option B: Immediate end-to-end canonical rewrite

**Strengths**
- Maximum simplification if it succeeds.

**Why it is still not recommended**
- Too much cross-layer blast radius at once.
- Weak rollback story.
- Unnecessarily couples manager, feature, transport, and connector migration into one step.

### Option C: Phased hybrid convergence at the real cut line (recommended)

**Phase order that matches the revised design**
1. **Phase 0**: characterization, feature audit, gate config, invariants, verification matrix.
2. **Phase 1**: manager-level canonical convergence after `IBackendProcessor` returns.
3. **Phase 2**: feature contract convergence with typed lifecycle context.
4. **Phase 3**: connector convergence provider by provider.
5. **Phase 4**: legacy retirement.

**Why this is still best**
- Delivers meaningful simplification in Phase 1 without pretending connector diversity does not exist.
- Preserves strong rollback and diagnostics.
- Uses existing tests as characterization assets rather than rebuilding validation from scratch.

## 5. Complexity and Risk Assessment

- **Effort: XL**
  - The work spans contracts, DI, service orchestration, transport compatibility, feature migration, and connector convergence.

- **Risk: High**
  - The main risk is behavioral compatibility, not coding volume.

- **Primary risk clusters**
  1. Boundary compatibility drift
  2. Safeguard regressions
  3. Feature migration mistakes
  4. Overreaching too early into connector internals

## 6. Recommendations for a Fresh Implementation Session

### Start here, not in the middle
1. Read `requirements.md`, `design.md`, and `tasks.md` together.
2. Treat the evidence and invariant guidance embedded in `design.md` as the characterization baseline for the first implementation session.
3. Implement Phase 0 artifacts before changing core request-processing logic.

### Preserve these assumptions during implementation
1. Phase 1 starts **after** `IBackendProcessor.process_backend_request()` returns.
2. `ProcessedResponse` stays the canonical chunk type.
3. The manager boundary needs `CanonicalResponseHandle`, not only a chunk iterator.
4. Legacy feature bridging is conditional on audit results.
5. Safeguard behavior is a promotion blocker, not secondary cleanup work.


## 7. Summary

The main gap is no longer conceptual uncertainty about whether stream-first internals are viable. The main gap is that the current implementation still lacks the manager-level canonical contract, explicit safeguard-preservation plan, feature audit results, and rollout evidence model required to do this safely. The revised design and tasks now point at the correct cut line; this gap analysis records the concrete missing pieces a fresh session still needs to respect.
