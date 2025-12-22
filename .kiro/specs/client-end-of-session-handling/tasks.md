# Implementation Plan

- [ ] 1. Extend End-of-Session model for client termination
- [ ] 1.1 Add a distinct End-of-Session signal type for client termination
  - Add a client-termination signal type that is distinct from normal completion and error termination.
  - Ensure the emitted End-of-Session event preserves the termination category as normal for client termination.
  - Ensure End-of-Session idempotency rules still apply (no duplicate EoS for the same lifecycle session).
  - _Requirements: 3.3, 3.5, 3.7_

- [ ] 1.2 Introduce a transport-agnostic session identity used for cancellation and EoS scoping
  - Represent the lifecycle session identity consistently across HTTP and Codebuff.
  - Ensure the lifecycle session identity is stable for a single request/connection and never shared across concurrent sessions.
  - Enforce “missing context ⇒ no attribution” behavior for any termination signal that lacks required identity.
  - _Requirements: 1.6, 2.2, 4.6_

- [ ] 2. Ensure session metrics exist and EoS can fail-open
- [ ] 2.1 Implement best-effort session metrics initialization with strict timeout
  - Ensure a session metrics record exists early in the lifecycle before backend work begins.
  - Make initialization callable from both HTTP and Codebuff flows without relying on request-scoped state.
  - Enforce a strict timeout so metrics initialization cannot stall cancellation/EoS handling under DB slowness.
  - _Requirements: 3.10, 5.5_

- [ ] 2.2 Make End-of-Session emission fail-open when persistence is unavailable
  - When the DB claim cannot be performed due to persistence errors, still emit End-of-Session at most once within the current process.
  - Log a high-signal persistence-unavailable diagnostic to support operator investigation.
  - Preserve “at most once per session” within-process behavior during fail-open operation.
  - _Requirements: 3.9, 3.10_

- [ ] 2.3 Add focused unit tests for metrics initialization and fail-open EoS behavior
  - Verify session metrics initialization is best-effort and does not raise on persistence failures.
  - Verify the strict timeout behavior under simulated unresponsive persistence.
  - Verify fail-open End-of-Session emits once-per-process when DB operations fail.
  - _Requirements: 3.9, 3.10, 5.5_

- [ ] 3. Implement session-scoped cancellation coordination
- [ ] 3.1 Build a session cancellation coordinator with per-session state and bounded retention
  - Track “cancelled” state per lifecycle session and store the standardized client termination reason.
  - Support registering cancellable in-flight work under a lifecycle session, and cancelling all registered work on termination.
  - Deduplicate multiple termination signals for the same lifecycle session to a single cancellation action.
  - Use a passive TTLCache (e.g., `cachetools.TTLCache`) for state storage to automatically handle cleanup/expiry without background tasks.
  - Ensure cancellation is strictly scoped to the lifecycle session and cannot impact other sessions.
  - _Requirements: 2.5, 2.6, 4.1, 4.3, 4.6_

- [ ] 3.2 Add a cancellation gate to prevent any new backend/agentic work after client termination
  - Provide a low-friction guard that can be applied at every backend initiation site (initial call, retries, failover, recovery, follow-up calls).
  - Ensure uncancellable in-flight outcomes are treated as non-deliverable and never forwarded after cancellation.
  - _Requirements: 4.2, 4.4, 4.5, 4.7_

- [ ] 3.3 Clean up cancellation state on End-of-Session emission
  - Clean up in-memory cancellation state when End-of-Session is emitted for a lifecycle session.
  - Ensure cleanup is best-effort and cannot block other subsystem finalization.
  - _Requirements: 5.4_

- [ ] 4. Normalize client termination signals and orchestrate EoS closure
- [ ] 4.1 Implement standardized mapping for legacy and transport-specific cancellation markers
  - Map known legacy cancellation markers and transport signals into standardized termination reasons.
  - Ensure standardized reason values are limited to the approved set.
  - _Requirements: 2.4, 2.7_

- [ ] 4.2 Implement a client end-of-session service with idempotent termination reporting
  - Accept client termination reports from transports and normalize them into a single session-scoped signal.
  - Log the standardized client termination reason together with the lifecycle session identity.
  - Initiate session cancellation before any blocking persistence work to minimize wasted backend work.
  - Ensure End-of-Session is emitted for client termination (including when termination propagates as cancellation exceptions).
  - Ensure multiple client termination signals do not produce duplicate client end-of-session signals or duplicate EoS events.
  - _Requirements: 1.1, 2.1, 2.2, 2.3, 2.5, 2.6, 3.1, 3.2, 3.4, 3.5, 3.8, 6.1_

- [ ] 4.3 Add unit tests for normalization, dedupe, and termination orchestration
  - Verify multiple termination reports collapse into one normalized signal per lifecycle session.
  - Verify End-of-Session emission occurs once and includes the standardized client termination reason.
  - Verify cancellation is initiated and remains session-scoped.
  - _Requirements: 2.5, 2.6, 3.2, 3.4, 4.6_

- [ ] 5. Integrate transport-level detection (HTTP + Codebuff)
- [ ] 5.1 (P) Report client disconnect during HTTP streaming in a shielded termination hook
  - Detect client disconnect/cancellation during streaming and report client termination with the correct lifecycle session identity.
  - Ensure termination reporting runs in a shielded context so it executes even if the request task is cancelled.
  - Continue evaluating disconnect signals while the stream is active.
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 3.6, 3.8_

- [ ] 5.2 (P) Report client disconnect/cancellation for HTTP non-streaming requests consistently
  - Detect client termination for non-streaming HTTP flows (e.g., via cancellation propagation or request disconnect checks).
  - Ensure termination reporting does not attribute signals when session context is missing.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.6, 3.8_

- [ ] 5.3 (P) Report Codebuff WebSocket disconnect as client termination and initialize session metrics
  - On Codebuff identify, initialize session metrics for the Codebuff lifecycle session.
  - On WebSocket disconnect, report client termination for the Codebuff lifecycle session and initiate cancellation of in-flight backend work.
  - _Requirements: 1.3, 1.7, 4.8, 5.5_

- [ ] 5.4 Add integration tests for client termination detection across transports
  - Verify HTTP streaming disconnect triggers client termination reporting, cancellation initiation, and EoS emission.
  - Verify Codebuff disconnect triggers client termination reporting and EoS emission.
  - _Requirements: 1.1, 1.3, 1.7, 3.2, 3.6_

- [ ] 6. Cancel backend and agentic work when client termination occurs
- [ ] 6.1 Update BaseBackendConnector and all implementations to accept explicit cancellation_token
  - Refactor `BaseBackendConnector.chat_completions` signature to accept an explicit `cancellation_token: SessionKey | None` argument.
  - Update **ALL** concrete backend connector implementations (OpenAI, Anthropic, Gemini, etc.) to accept the new argument.
  - Ensure the identity propagation uses this explicit argument and does not rely on fragile `**kwargs` or context dictionaries.
  - Ensure backend execution components have access to the lifecycle session identity for gating and registration.
  - _Requirements: 4.6_

- [ ] 6.2 Enforce cancellation gating before any backend call, retry, failover, or recovery action
  - Stop initiating any additional backend work for a lifecycle session once client termination is observed.
  - Prevent internal recovery workflows from scheduling follow-up backend calls after client termination.
  - _Requirements: 4.2, 4.4, 4.7_

- [ ] 6.3 Cancel in-flight backend work and scheduled workflow steps for the terminated lifecycle session
  - Register in-flight backend work under the lifecycle session so it can be cancelled when termination is observed.
  - Cancel scheduled agentic/steering workflow steps associated with the terminated lifecycle session.
  - Record (via structured logging/metrics) that backend work was cancelled due to client termination when in-flight work existed.
  - _Requirements: 4.1, 4.3, 6.3_

- [ ] 6.4 Treat uncancellable outcomes as non-deliverable after client termination
  - Ensure any completion that finishes after client termination is not delivered to the client.
  - Ensure End-of-Session is still emitted for the lifecycle session.
  - _Requirements: 3.2, 4.5_

- [ ] 6.5 Add integration tests for cancellation scope and recovery suppression
  - Verify in-flight backend work is cancelled (or suppressed) and no follow-up backend calls are initiated after client termination.
  - Verify cancellation is strictly scoped to one lifecycle session and does not impact concurrent sessions.
  - _Requirements: 4.1, 4.2, 4.4, 4.6, 4.7_

- [ ] 7. Finalize subsystems and ensure client termination observability
- [ ] 7.1 Ensure usage tracking and wire capture finalize with client termination reason on End-of-Session
  - Ensure the standardized client termination reason is available to internal metrics/accounting and persists in session-level aggregates.
  - Ensure wire captures record the client termination reason in End-of-Session metadata when enabled.
  - _Requirements: 5.1, 5.2, 6.2_

- [ ] 7.2 Include client termination reason in ProxyMem finalization when enabled
  - Ensure ProxyMem session completion records a termination reason indicating client termination.
  - Ensure ProxyMem finalization remains best-effort and fault-isolated.
  - _Requirements: 5.3, 5.4_

- [ ] 7.3 Add observability outputs for client termination and cancellation effects
  - Ensure logs include session identity and standardized client termination reason for all terminations.
  - Ensure client termination can be distinguished from backend error termination in categorization and reporting.
  - _Requirements: 6.1, 6.4_

- [ ] 7.4 Verify subsystem finalization is robust under partial/early termination
  - Ensure End-of-Session is emitted even when the client terminates before any backend response is received.
  - Ensure failures in one subsystem finalizer do not prevent other finalizers from running.
  - _Requirements: 5.4, 5.5_
