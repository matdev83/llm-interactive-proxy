# Requirements Document

## Introduction
This specification defines detection and handling of end-of-session conditions on the Client <-> Proxy leg (for example, client cancellation and dropped connections) so that every session has consistent lifecycle closure and all in-flight and scheduled backend work is cancelled when the client is no longer able to receive results.

This specification is intended as a follow-up to `end-of-session-events` to ensure client-side termination reasons are observable to subsystems (for example, usage tracking, wire capture, and ProxyMem) and do not bypass End-of-Session (EoS) emission.

**Project Context**: Universal LLM Proxy - Traffic routing, failover, accounting for multiple LLM backends with async FastAPI architecture.

**Stakeholders**:
- Developers integrating LLM capabilities via unified API
- Operators managing backend configurations and monitoring
- End-users consuming LLM responses through client applications

## Requirements

### Requirement 1: Client End-of-Session Detection
**Objective:** As an operator, I want the proxy to detect client-side termination, so that client-driven session endings are handled consistently across protocols.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 1.1 When the client connection for a session is dropped, the LLM Proxy shall detect the session as client-terminated.
- 1.2 When a frontend protocol provides an explicit cancellation mechanism and the client invokes it for a session, the LLM Proxy shall detect the session as client-terminated.
- 1.3 The LLM Proxy shall support client termination detection for all supported frontend protocols, including HTTP-based endpoints and Codebuff WebSocket sessions.
- 1.4 The LLM Proxy shall support client termination detection for both streaming and non-streaming responses.
- 1.5 While a session is active, the LLM Proxy shall continue to evaluate client termination signals for that session.
- 1.6 If a client termination signal is missing required session context, then the LLM Proxy shall not attribute the signal to any session.
- 1.7 When a Codebuff WebSocket session disconnects, the LLM Proxy shall detect the session as client-terminated.

#### Technical Constraints
- Async compatibility: Must use `async/await` patterns
- DI integration: Services registered via `ServiceCollection`
- Error hierarchy: Exceptions extend `LLMProxyError`
- Config precedence: CLI > ENV > YAML

### Requirement 2: Client Termination Signal Normalization
**Objective:** As a developer, I want client termination captured as a normalized signal, so that downstream subsystems can react without transport coupling.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 2.1 When a client termination is detected for a session, the LLM Proxy shall produce a normalized client end-of-session signal.
- 2.2 When a normalized client end-of-session signal is produced, the LLM Proxy shall include the session identifier and event timestamp.
- 2.3 When a normalized client end-of-session signal is produced, the LLM Proxy shall include a termination reason.
- 2.4 When a normalized client end-of-session signal is produced, the LLM Proxy shall set the termination reason to one of: `client_disconnected`, `client_cancelled`, `unknown_client_termination`.
- 2.5 If multiple client termination signals are observed for the same session, then the LLM Proxy shall normalize them to a single client end-of-session signal.
- 2.6 If a client end-of-session signal has already been produced for a session, then the LLM Proxy shall not produce a duplicate client end-of-session signal for that session.
- 2.7 If the LLM Proxy observes any non-standard or legacy cancellation markers for a session, then the LLM Proxy shall map them to the standardized termination reasons.

#### Technical Constraints
- Observability: Normalized signals integrate with structured logging context
- Async compatibility: Normalization must avoid blocking I/O

### Requirement 3: End-of-Session (EoS) Integration for Client Termination
**Objective:** As an operator, I want client termination to reliably result in EoS closure, so that every session emits a final lifecycle event.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 3.1 When a client end-of-session signal is produced for a session, the LLM Proxy shall mark the session as ended.
- 3.2 When a session is marked as ended due to client termination, the LLM Proxy shall emit an End-of-Session event for that session.
- 3.3 When an End-of-Session event is emitted due to client termination, the LLM Proxy shall record the termination category as normal.
- 3.4 When an End-of-Session event is emitted due to client termination, the LLM Proxy shall include the client termination reason.
- 3.5 If an End-of-Session event has already been emitted for a session, then the LLM Proxy shall not emit an additional End-of-Session event due to client termination for that session.
- 3.6 When client termination occurs during a streaming response, the LLM Proxy shall emit the End-of-Session event even if the response stream does not complete normally.
- 3.7 When a session ends due to client termination, the LLM Proxy shall record the end-of-session signal type as client termination (distinct from normal completion and error termination).
- 3.8 If a session ends due to client termination and cancellation propagates as a cancellation exception, then the LLM Proxy shall still emit the End-of-Session event for that session.
- 3.9 If the LLM Proxy cannot persist end-of-session idempotency state for a client-terminated session, then the LLM Proxy shall still emit the End-of-Session event at most once within the current process and shall log that persistence was unavailable.
- 3.10 Where end-of-session persistence is enabled, the LLM Proxy shall persist end-of-session idempotency state for client-terminated sessions using the same persistence mechanism used for other end-of-session events.

#### Technical Constraints
- Reliability: EoS emission must preserve “at most once per session”
- Async compatibility: EoS emission must avoid blocking I/O

### Requirement 4: Cancellation of Backend and Agentic Work on Client Termination
**Objective:** As an operator, I want all backend work cancelled when the client session ends, so that resources are not wasted on results that will never be delivered.

**Priority:** P0 (Critical)

#### Acceptance Criteria
- 4.1 When a session is client-terminated, the LLM Proxy shall initiate cancellation of all in-flight backend requests associated with that session.
- 4.2 When a session is client-terminated, the LLM Proxy shall stop initiating any additional backend requests associated with that session.
- 4.3 When a session is client-terminated and an agentic or steering workflow is in progress for that session, the LLM Proxy shall initiate cancellation of all in-flight and scheduled workflow steps for that session.
- 4.4 While a session is client-terminated, the LLM Proxy shall prevent retries, failovers, or follow-up backend calls from being scheduled for that session.
- 4.5 If a backend request cannot be cancelled, then the LLM Proxy shall treat the request outcome as non-deliverable and shall not attempt to deliver results to the client.
- 4.6 The LLM Proxy shall not cancel backend requests or agentic workflow steps that are not associated with the client-terminated session.
- 4.7 While a session is client-terminated, the LLM Proxy shall prevent any internal recovery workflow that would initiate additional backend calls for that session.
- 4.8 When a Codebuff WebSocket session is client-terminated while backend work is in-flight for the session, the LLM Proxy shall initiate cancellation of that backend work.

#### Technical Constraints
- Safety: Cancellation must be scoped to a single session and avoid cross-session interference
- Async compatibility: Cancellation must avoid blocking I/O

### Requirement 5: Subsystem Finalization on Client Termination
**Objective:** As an operator, I want subsystems to finalize cleanly on client termination, so that accounting and captures remain consistent even for partial results.

**Priority:** P1 (High)

#### Acceptance Criteria
- 5.1 When an End-of-Session event is emitted due to client termination, the LLM Proxy shall finalize usage tracking for the session using any available partial usage data.
- 5.2 When an End-of-Session event is emitted due to client termination and wire capture is enabled, the LLM Proxy shall finalize the capture for the session and record the client termination reason in capture metadata.
- 5.3 When an End-of-Session event is emitted due to client termination and ProxyMem is enabled, the LLM Proxy shall finalize the memory session with a termination reason indicating client termination.
- 5.4 If subsystem finalization fails during client termination, then the LLM Proxy shall record the failure in logs and shall continue finalizing remaining subsystems.
- 5.5 When a session is client-terminated before any backend response is received, the LLM Proxy shall still emit the End-of-Session event and finalize subsystem state for that session.

#### Technical Constraints
- Reliability: Subsystem finalization must be best-effort and fault-isolated
- Observability: Finalization failures must be logged with correlation identifiers

### Requirement 6: Observability for Client Termination
**Objective:** As an operator, I want client termination reasons observable, so that I can measure client drop rate and diagnose session endings.

**Priority:** P1 (High)

#### Acceptance Criteria
- 6.1 When a session is client-terminated, the LLM Proxy shall log the client termination reason with the session identifier.
- 6.2 When a session is client-terminated, the LLM Proxy shall make the client termination reason available to internal metrics and accounting subsystems.
- 6.3 If client termination occurs while a backend request is active, then the LLM Proxy shall record that the backend request was cancelled due to client termination.
- 6.4 The LLM Proxy shall distinguish client termination from backend error termination in its termination categorization.

#### Technical Constraints
- Security: Observability data must not include API keys or authorization headers
- Privacy: Observability data must avoid capturing user secrets beyond existing wire-capture policy

## Non-Functional Requirements

### NFR 1: Performance
- Client termination detection and cancellation initiation shall add no more than 10 ms of overhead to normal request processing.
- Client termination handling shall not delay streaming first-byte.

### NFR 2: Reliability
- Sessions shall emit at most one End-of-Session event, regardless of client termination timing.
- Client termination handling shall be robust to listener/subsystem failures and continue best-effort finalization.

### NFR 3: Security and Isolation
- Client termination handling shall not allow a client to cancel or influence sessions owned by other clients.
- Session-scoped state for termination and cancellation shall be isolated per session and not shared across concurrent sessions.

### NFR 4: Code Quality and Architecture
- The implementation shall adhere to SOLID principles and maintain modular, layered architecture boundaries.
- Instance ownership shall be managed via DI (no hidden singletons with cross-session state).
- The implementation shall avoid hidden mutable global state that can cause cross-session leakage.

## Glossary
| Term | Definition |
|------|------------|
| Client termination | A session ending due to client disconnection or explicit cancellation. |
| Client end-of-session signal | A normalized internal signal representing client termination for a specific session. |
| End-of-Session (EoS) event | A system event emitted when a session ends (see `end-of-session-events`). |
| Session | A unit of request/response interaction tracked by the proxy. |
| Agentic / steering workflow | A multi-step internal process that may schedule additional backend calls for a session. |
| Backend request | A Proxy <-> Remote LLM request associated with a session (the “B-leg”). |
