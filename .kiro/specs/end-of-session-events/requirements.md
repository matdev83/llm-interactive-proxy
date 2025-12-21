# Requirements Document

## Introduction
This specification defines end-of-session detection and End-of-Session (EoS) event emission so that internal components and extensions can react to session lifecycle completion in a consistent, observable manner.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: End-of-Session Detection
**Objective:** As an operator, I want the proxy to detect end-of-session conditions, so that session lifecycles are consistent across protocols.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When a session meets a configured end-of-session condition, the LLM Proxy shall mark the session as ended.
2. While a session is active, the LLM Proxy shall evaluate configured end-of-session signals for that session.
3. If an end-of-session signal is missing required context, then the LLM Proxy shall treat the session as active.
4. When a session is marked as ended, the LLM Proxy shall treat the session state as terminal for that session.
5. The LLM Proxy shall detect end-of-session conditions for all supported frontend protocols.
6. The LLM Proxy shall detect end-of-session conditions for both streaming and non-streaming sessions.
7. When a remote backend or transport error terminates a session, the LLM Proxy shall treat it as an end-of-session signal.
8. When a session ends due to a remote backend or transport error, the LLM Proxy shall record the termination category as an error.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: End-of-Session Event Emission
**Objective:** As a developer, I want End-of-Session events emitted once per session, so that subscribers can react reliably.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When a session is marked as ended, the LLM Proxy shall emit an End-of-Session event.
2. When an End-of-Session event is emitted, the LLM Proxy shall include the session identifier and event timestamp.
3. If an End-of-Session event has already been emitted for a session, then the LLM Proxy shall not emit a duplicate event for that session.
4. While event emission is enabled, the LLM Proxy shall emit events for ended sessions before finalizing the session lifecycle.
5. The LLM Proxy shall emit End-of-Session events using a consistent backend-scoped identifier (for example, `remote_backend_connection_end_of_session` and RemoteBackendConnectionEndOfSessionEvent).
6. The LLM Proxy shall emit End-of-Session events for both streaming and non-streaming sessions.
7. The LLM Proxy shall persist End-of-Session completion state in the database and use it to prevent duplicate End-of-Session events after process restarts.
8. When emitting End-of-Session events, the LLM Proxy shall not delay response finalization beyond a configurable dispatch timeout.
9. When an End-of-Session event is emitted, the LLM Proxy shall include a termination category of normal or error.
10. When the termination category is error, the LLM Proxy shall include a normalized error classification and any available backend status context.
11. The normalized error classification shall be one of: `transport_error`, `http_error`, `backend_error`, `unknown_error`.

#### Technical Constraints
- Async compatibility: Event emission must avoid blocking I/O
- Observability: Emission integrates with structured logging context
- Error hierarchy: Emission failures extend `LLMProxyError`

### Requirement 3: Listener Subscription and Dispatch
**Objective:** As an integrator, I want to register listeners for End-of-Session events, so that my services can trigger follow-up actions.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When a listener subscribes to End-of-Session events, the LLM Proxy shall register the listener for future events.
2. When an End-of-Session event is emitted, the LLM Proxy shall dispatch the event to all registered listeners.
3. If a listener unsubscribes, then the LLM Proxy shall stop dispatching End-of-Session events to that listener.
4. While multiple listeners are registered, the LLM Proxy shall deliver the same event payload to each listener.
5. The LLM Proxy shall allow listeners to be registered at application startup.

#### Technical Constraints
- DI integration: Listener registrations must be compatible with `ServiceCollection`
- Async compatibility: Listener dispatch must be async-safe

### Requirement 4: Listener Fault Isolation
**Objective:** As an operator, I want listener failures isolated, so that event emission does not disrupt request processing.

**Priority:** P1 (High)

#### Acceptance Criteria
1. If a listener fails while handling an End-of-Session event, then the LLM Proxy shall record the failure and continue dispatching to other listeners.
2. When a listener fails, the LLM Proxy shall not revert the session end state.
3. While dispatching events, the LLM Proxy shall prevent listener failures from blocking completion of other listeners.
4. The LLM Proxy shall surface listener failures through logs or metrics.
5. The LLM Proxy shall preserve the End-of-Session event payload for all listeners despite a failure.

#### Technical Constraints
- Error hierarchy: Listener errors extend `LLMProxyError`
- Observability: Listener failures must include correlation identifiers

### Requirement 5: Configuration and Controls
**Objective:** As an operator, I want configuration to control end-of-session detection and event emission, so that deployment behavior is predictable.

**Priority:** P1 (High)

#### Acceptance Criteria
1. Where end-of-session detection is disabled by configuration, the LLM Proxy shall not mark sessions as ended.
2. Where End-of-Session event emission is disabled by configuration, the LLM Proxy shall not emit End-of-Session events.
3. When end-of-session configuration is invalid, the LLM Proxy shall reject startup with a clear configuration error.
4. While configuration is valid, the LLM Proxy shall apply end-of-session settings consistently across all running sessions.
5. The LLM Proxy shall expose configuration defaults for end-of-session detection and event emission.

#### Technical Constraints
- Config precedence: CLI > ENV > YAML
- Schema validation: Config must align with `config/schemas/`

### Requirement 6: Completion Signal Normalization
**Objective:** As a developer, I want protocol-specific completion signals normalized into a unified end-of-session signal, so that downstream subsystems do not implement their own completion detection.

**Priority:** P0 (Critical)

#### Acceptance Criteria
1. When the proxy receives a streaming completion sentinel from a supported protocol (for example, `[DONE]` or an equivalent marker), the LLM Proxy shall treat it as an end-of-session signal for the associated session.
2. When a response includes a completion reason marker from a supported protocol (for example, `finish_reason` or `end_turn`), the LLM Proxy shall translate it into an end-of-session signal with the reason recorded.
3. When a response protocol emits an explicit completion event (for example, `response.completed` or `message_stop`), the LLM Proxy shall translate it into an end-of-session signal.
4. When a completion tool call is invoked (for example, `attempt_completion` or `finish`), the LLM Proxy shall translate it into an end-of-session signal for the session.
5. If multiple completion signals are observed for the same session, then the LLM Proxy shall normalize them to a single End-of-Session event.
6. When a remote backend or transport error occurs, the LLM Proxy shall translate it into an end-of-session error signal with the error classification recorded.
7. The error signal classification shall use only the standardized values: `transport_error`, `http_error`, `backend_error`, `unknown_error`.

#### Technical Constraints
- Async compatibility: Normalization must avoid blocking I/O
- Error hierarchy: Signal normalization errors extend `LLMProxyError`

### Requirement 7: Subsystem Integration and Refactoring
**Objective:** As an operator, I want End-of-Session events to drive existing subsystem behaviors, so that completion handling is consistent and centralized.

**Priority:** P1 (High)

#### Acceptance Criteria
1. When an End-of-Session event is emitted and ProxyMem is enabled, the LLM Proxy shall mark the memory session complete and queue configured follow-up analysis.
2. When an End-of-Session event is emitted, the LLM Proxy shall finalize usage tracking for the session and persist session completion status in the usage store.
3. When an End-of-Session event is emitted and wire capture is enabled, the LLM Proxy shall record End-of-Session occurrence in capture metadata for the session.
4. When an End-of-Session event is emitted and test execution reminder steering is enabled, the LLM Proxy shall evaluate the session's dirty state and emit the configured reminder if tests are pending.
5. While End-of-Session events are enabled, the LLM Proxy shall trigger End-of-Session consumer behaviors from the End-of-Session event rather than from protocol-specific completion markers.
6. When End-of-Session events are enabled, the LLM Proxy shall replace all existing custom end-of-session detection logic with End-of-Session event subscribers.

#### Technical Constraints
- DI integration: Subsystem handlers must be compatible with `ServiceCollection`
- Async compatibility: Subsystem handlers must be async-safe

## Non-Functional Requirements

### NFR 1: Performance
- Response latency: End-of-session detection shall add no more than 10 ms to response finalization under normal load.
- Streaming first-byte: End-of-session processing shall not delay first-byte for streaming responses.
- Throughput: End-of-session event handling shall not reduce baseline request throughput by more than 5%.

### NFR 2: Reliability
- Event delivery: End-of-Session events shall be emitted at most once per session.
- Listener isolation: A failed listener shall not prevent other listeners from completing.
- Recovery: Ended sessions shall not emit duplicate End-of-Session events after process restart.

### NFR 3: Observability
- Wire captures: When wire capture is enabled, the LLM Proxy shall record End-of-Session event occurrence in capture metadata.
- Logging levels: End-of-Session event emission shall be logged at INFO with correlation identifiers.
- Health checks: Service health reporting shall include End-of-Session subsystem status.

### NFR 4: Security
- API key handling: End-of-Session events shall not include API keys or authorization headers.
- Input validation: End-of-session signals shall be validated against configured schemas.
- Authentication: End-of-Session events shall only be emitted for authenticated requests.

## Glossary
| Term | Definition |
|------|------------|
| End-of-Session (EoS) | The point at which a session is considered complete and terminal. |
| EoS Event | A system event emitted when a session ends. |
| Completion Signal | A protocol- or tool-level indicator that a response or task has finished. |
| EoS Consumer | A subsystem that reacts to EoS events (for example, usage tracking or ProxyMem). |
| Listener | A registered subscriber that receives EoS events. |
| Session | A unit of request/response interaction tracked by the proxy. |
| Wire Capture | CBOR-encoded traffic recording for debugging. |
| Staged Init | Sequential initialization phases for services. |
| DI Container | Dependency injection via `ServiceCollection`. |
| Termination Category | The outcome classification for an EoS event (normal or error). |
| Error Classification | Standardized error cause label for error terminations (transport_error, http_error, backend_error, unknown_error). |
