# Research Document: BackendService God Object Refactoring

## Discovery Summary

This document captures fact-based findings used to shape the requirements and design for refactoring `BackendService` without changing runtime behavior.

## Current BackendService Metrics (Verified)

- File: `src/core/services/backend_service.py`
- Size: 2109 lines (`wc -l`)
- Complexity (radon via `scripts/analyze_complexity.py`):
  - `BackendService.call_completion`: CC 180 (primary hotspot)
  - `BackendService._resolve_backend_and_model`: CC 29
  - `BackendService.__init__`: CC 20
  - Maintainability index for the module: 0.00

## Responsibilities Mixed in BackendService (Verified)

The current `call_completion` flow mixes the following concerns in one method:
- Target resolution (backend/model selection, URI params, static routing overrides)
- Session resolution (context + request extra_body usage)
- Backend instantiation and per-session backend usage (delegated to lifecycle manager but coordinated here)
- Retry/failover decision loops (including complex failover routes + recursive call semantics)
- Resilience integration (availability checks and failure recording)
- Usage tracking integration (request/response recording and wrapping streaming content)
- Optional wire capture integration (stream wrapping and session-id selection)
- Streaming response shaping and SSE byte adaptation (static wrapper method exists)

This is the core “God Object” pressure: changes in any of the above require editing the same method, and testing the flow requires extensive setup.

## Existing Extracted Services (Verified)

The codebase already contains and registers several focused services:
- Backend lifecycle: `IBackendLifecycleManager` / `BackendLifecycleManager`
- Failover routing policy: `IFailoverCoordinator` / `FailoverCoordinator` and `IFailoverStrategy`
- Failure handling policy: `IFailureHandlingStrategy` (optional via config/DI)
- Streaming formatting: `IStreamFormattingService` / `StreamFormattingService`
- Usage tracking wrapper: `IUsageTrackingWrapper` / `UsageTrackingWrapper`
- Model aliasing: `IModelAliasResolver` / `ModelAliasResolver`
- Planning phase management: `IPlanningPhaseManager` / `PlanningPhaseManager`
- Reasoning config and URI parameters: `IReasoningConfigApplicator` / `IURIParameterApplicator`
- Exception normalization: `IExceptionNormalizer` / `ExceptionNormalizer`

These services reduce surface area, but the completion orchestration still lives inside `BackendService.call_completion`.

## Duplication: Streaming Session ID Resolution (Verified)

There are two separate session-id resolution implementations used for streaming capture/buffering:
- `BackendService._resolve_stream_session_id`
- `BufferedWireCaptureService._resolve_stream_session_id`

The algorithms differ (inputs consulted and ordering), which can lead to inconsistent capture session identifiers across pipelines. This is a DRY and observability risk.

## Test and Compatibility Constraints (Verified)

Existing tests directly call some internal helper methods on BackendService, including:
- `_resolve_backend_and_model`
- `_get_failover_plan`
- `BackendService._stream_as_sse_bytes` (static)

This creates a strong constraint: these methods (or compatible wrappers) must remain available and preserve semantics, even after extraction.

## Design Implications

The biggest complexity reduction comes from extracting `call_completion` orchestration into a dedicated service and shrinking `BackendService` into a façade. However, simply moving code would risk creating a new God Object. The design therefore:
- Introduces a dedicated completion orchestration service (`BackendCompletionFlow`)
- Extracts the most testable sub-responsibilities into separate services (target resolution, failover planning, streaming session-id resolution)
- Keeps existing extracted services as dependencies of the flow
- Preserves BackendService’s test-facing wrappers as thin delegates

## Open Questions / Risks to Resolve During Implementation

- Best interface style for new collaborators (Protocol vs ABC) to match local conventions and typing constraints.
- Final definition of a shared streaming session-id algorithm that preserves current behavior while eliminating duplication (may require compatibility shims if other components rely on the existing differences).
- Ensuring failover recursion semantics are preserved without introducing circular dependencies (the completion flow must not depend on `IBackendService`).
