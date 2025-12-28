# Research & Design Decisions

## Summary
- **Feature**: `client-end-of-session-handling`
- **Discovery Scope**: Complex Integration (Extension)
- **Key Findings**:
  - Client disconnect/cancellation detection is currently fragmented across HTTP controller logic, streaming pipeline behavior (`GeneratorExit`), and WebSocket disconnect handlers.
  - Client-driven cancellation can bypass End-of-Session (EoS) emission because `asyncio.CancelledError` is re-raised in backend orchestration without recording an EoS signal.
  - Codebuff WebSocket prompt streaming bypasses core request processing and does not consistently propagate cancellation via `StreamingResponseEnvelope.cancel_callback`.
  - EoS idempotency relies on persisted session metrics state; the codebase assumes a `session_metrics` record exists before claiming EoS emission.

## Research Log

### Existing Codebase Analysis
- **Components Reviewed**:
  - `src/core/app/controllers/responses_controller.py` - HTTP streaming disconnect detection and upstream cancellation callback usage.
  - `src/core/ports/streaming_orchestrator.py` - `GeneratorExit` handling for client disconnect in streaming pipeline.
  - `src/core/services/backend_completion_flow/service.py` - backend orchestration and cancellation propagation.
  - `src/core/services/end_of_session_service.py` and `src/core/domain/events/end_of_session_events.py` - EoS signal normalization and event emission.
  - `src/core/services/backend_completion_flow/eos_adapter.py` - error termination → EoS translation.
  - `src/codebuff/server.py` and `src/codebuff/handlers/prompt_handler.py` - WebSocket lifecycle and LLM streaming behavior.
  - EoS subscribers: `src/core/services/usage_tracking_eos_subscriber.py`, `src/core/services/wire_capture_eos_subscriber.py`, `src/core/memory/eos_subscriber.py`.
- **Patterns Identified**:
  - Event-driven normalization: a central EoS publisher emits a single event per session; subsystems attach via subscribers.
  - Cancellation propagation exists, but as localized callbacks (`StreamingResponseEnvelope.cancel_callback`) and ad-hoc cancellation markers (`cancel_reason`) rather than a session-wide cancellation contract.
  - Streaming disconnect is currently detected via two mechanisms:
    - proactive polling (`request.is_disconnected()`), and
    - consumer cancellation (`GeneratorExit`).
  - EoS persistence uses an atomic claim on the `session_metrics` row to enforce “at most once” across concurrency and restarts.
- **Implications**:
  - Client termination must be translated into the same EoS emission pathway used by backend completion and errors.
  - A session-scoped cancellation coordinator is required to prevent additional backend calls (retry/failover/tool-call retry/agentic steps) after client termination.
  - Codebuff requires an adapter to participate in the same cancellation + EoS lifecycle, even if it remains a separate transport.

### Cancellation and Termination Signal Sources
- **Context**: Multiple runtime signals currently represent client termination, but they are not normalized consistently.
- **Sources Consulted**:
  - HTTP streaming detection in `src/core/app/controllers/responses_controller.py` (`request.is_disconnected()` and cancellation callback).
  - Streaming pipeline disconnect behavior in `src/core/ports/streaming_orchestrator.py` (`GeneratorExit`).
  - Usage normalization mapping in `src/core/services/usage_normalization_service.py` (`cancel_reason` values).
- **Findings**:
  - Existing cancellation markers are not standardized (`client_disconnect`, `stream_cancelled`, `user_cancelled`).
  - Disconnect detection is uneven across protocols; most explicit disconnect detection exists in the Responses API controller path.
- **Implications**:
  - The design needs a single normalization contract for client termination reason.
  - The design should reduce controller-specific logic by providing reusable “termination reporting” interfaces that can be called from any transport adapter.

### EoS Idempotency and Persistence Precondition
- **Context**: Requirement 3.10 requires persistence of idempotency state for client termination; gap analysis found the EoS service depends on session metrics existence.
- **Sources Consulted**:
  - `src/core/services/end_of_session_service.py`
  - `src/core/database/repositories/usage_repository.py` (`SessionMetricsRepository.claim_eos_emission`)
- **Findings**:
  - `claim_eos_emission()` succeeds only if a `session_metrics` row exists and `eos_emitted_at IS NULL`.
  - Current EoS interface offers only an in-memory `has_ended()` fast path; missing DB state can block emission unless the design ensures metrics exist.
- **Implications**:
  - The design should ensure session metrics are created early in request processing so EoS claims are possible for client termination.
  - A fail-open in-process idempotency fallback is still required for cases where persistence is unavailable.

### Codebuff Transport Integration
- **Context**: Requirement 1.3/1.7 and 4.8 require Codebuff WebSocket disconnection to cancel backend work and close the session lifecycle.
- **Sources Consulted**:
  - `src/codebuff/server.py`, `src/codebuff/connection_manager.py`, `src/codebuff/handlers/prompt_handler.py`
- **Findings**:
  - WebSocket disconnect is detected and logged, but backend streaming does not consistently register cancellable work under a session-scoped cancellation contract.
  - Codebuff prompt streaming uses backend connector calls directly (not the core request processor / backend completion flow).
- **Implications**:
  - The design needs an explicit Codebuff adapter surface that can:
    - report client termination into the domain service, and
    - register/cancel in-flight backend work when the WebSocket closes.

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| Extend existing EoS only | Treat client termination as another `EndOfSessionSignal` source, called from transports | Reuses EoS subscribers and dedupe | Risk of overloading “remote backend connection” naming; still needs a cancellation coordinator | Works well as part of Hybrid |
| New client EoS event | Add `ClientConnectionEndOfSessionEvent` + parallel subscribers | Clear semantics, transport separation | Duplicates subscriber work; requires coordination with overall EoS | Adds complexity; not required by current requirements |
| Hybrid (selected) | Add client termination normalization + session cancellation coordinator; feed into existing EoS emission | Minimizes changes to subsystems; improves correctness quickly | Requires cross-cutting “do not start more backend work” gating | Best fit for SOLID + staged init |

## Design Decisions

### Decision: Session-wide Cancellation Coordinator
- **Context**: Requirement 4.x requires canceling in-flight backend work and preventing new backend work after client termination.
- **Alternatives Considered**:
  1. Rely on per-stream `cancel_callback` only
  2. Introduce a central session-scoped cancellation coordinator with explicit contracts
- **Selected Approach**: Introduce an `ISessionCancellationCoordinator` that tracks cancellation state per session and provides a gate for initiating backend work.
- **Rationale**: Meets cancellation semantics across streaming/non-streaming and across retry/agentic workflows without relying on transport-specific exceptions.
- **Trade-offs**: Introduces a new stateful singleton service requiring bounded caches and cleanup.
- **Follow-up**: Define cleanup triggers (EoS emission and/or time-based TTL).

### Decision: Client Termination → EoS via Existing EndOfSessionService
- **Context**: Requirement 3.x requires that client termination cannot bypass EoS.
- **Alternatives Considered**:
  1. Create a parallel client-specific event and subscribers
  2. Extend EoS signal sources to include client termination and emit the same EoS event type
- **Selected Approach**: Introduce `IClientEndOfSessionService` to normalize client termination and call `IEndOfSessionService.record_signal(...)` with a client-termination signal type.
- **Rationale**: Preserves subsystem integration (subscribers already listen for EoS events) and keeps the “one end-of-session per session” model intact.
- **Trade-offs**: Requires updating the EoS domain model to include a client-termination signal type and standardizing `reason` values.

### Decision: Ensure Session Metrics Existence Early
- **Context**: EoS persistence uses a DB claim against `session_metrics`; client termination can occur before backend completion.
- **Alternatives Considered**:
  1. Change EoS persistence to create records on demand
  2. Ensure session metrics are created at the start of request processing
- **Selected Approach**: Add a session-metrics initialization step early in request processing for all protocols that participate in EoS.
- **Rationale**: Keeps EoS emission logic stable and improves restart-safe idempotency for all termination types.
- **Trade-offs**: Requires identifying a consistent “session start” point and ensuring per-protocol session ID availability.

### Decision: Codebuff Integration Surface
- **Context**: Codebuff WebSocket flows must cancel backend work and emit EoS on disconnect.
- **Alternatives Considered**:
  1. Refactor Codebuff prompt handling to route through core request processor
  2. Add a minimal transport adapter that reports termination and registers cancellable backend work with the cancellation coordinator
- **Selected Approach**: Provide a Codebuff-facing adapter surface to integrate cancellation/EoS without forcing a full request processor migration.
- **Rationale**: Smaller change surface while meeting the feature requirements; preserves modularity.
- **Trade-offs**: Codebuff continues to bypass some proxy features unless separately migrated.

### Decision: DI Lifetime Selection
- **Context**: Cancellation state is per session, but must be visible across multiple components during a request and across async tasks.
- **Selected Approach**:
  - `ISessionCancellationCoordinator`: `Singleton` (explicitly stateful, bounded, with cleanup)
  - `IClientEndOfSessionService`: `Singleton` (stateless orchestrator over other services)
  - Transport adapters: `Transient` or `Scoped` (depending on existing controller/handler lifetimes)
- **Rationale**: Keeps state in one explicit component and avoids hidden module globals.

### Decision: Error Handling Strategy
- **Context**: Termination reporting must be fail-open and must not convert expected disconnects into “error” terminations.
- **Selected Approach**:
  - Client termination reports are treated as “normal” termination category (per requirements).
  - Failures to cancel backend work are logged and do not block EoS emission.
  - EoS dispatch uses the existing bounded-timeout mechanism.

## Testing Strategy Research

### Existing Test Patterns
- Integration tests cover EoS end-to-end and subscriber behavior: `tests/integration/core/services/test_eos_end_to_end.py`.
- Property tests exist for dedupe behavior: `tests/property/core/services/test_eos_dedupe_properties.py`.

### Coverage Requirements
- Client termination reason normalization (legacy markers → standardized reasons).
- EoS emission on client termination across:
  - HTTP streaming disconnect,
  - cancellation exception propagation,
  - Codebuff WebSocket disconnect.
- Cancellation gating prevents retry/failover/tool-call retry after termination.
- Session isolation: cancellation scoped to one session key.

## Risks & Mitigations
- Risk: Duplicate termination signals from multiple layers (polling + `GeneratorExit` + `CancelledError`) - Mitigation: central EoS dedupe + session cancellation idempotency.
- Risk: Cross-session cancellation leakage - Mitigation: explicit `SessionKey` contract, strict scoping, and cleanup.
- Risk: Missing session metrics row blocks persistence - Mitigation: session metrics initializer + fail-open in-process idempotency fallback.
- Risk: Codebuff remains outside core processing - Mitigation: dedicated adapter surface and explicit integration contracts.

## Performance Considerations
- Cancellation checks must be O(1) and avoid blocking I/O on the hot path.
- Cancellation state storage must be bounded (LRU/TTL cleanup).
- EoS dispatch must remain bounded by the configured dispatch timeout.

## References
- `.kiro/steering/tech.md` - Staged init, DI, backend completion flow overview
- `src/core/services/end_of_session_service.py` - Central EoS publisher and idempotency
- `src/core/services/backend_completion_flow/service.py` - Cancellation propagation and error termination handling
- `src/core/app/controllers/responses_controller.py` - Current HTTP streaming disconnect logic
- `src/codebuff/server.py` and `src/codebuff/handlers/prompt_handler.py` - Codebuff transport behavior
- `.kiro/settings/rules/design-principles.md` - Design rules and requirement ID conventions

