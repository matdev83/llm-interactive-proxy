# Implementation Plan

- [ ] 1. Core EoS domain and configuration
- [ ] 1.1 (P) Define End-of-Session event and signal models with required metadata
  - Include session identifier, timestamp, signal type, and optional reason/protocol details.
  - Set a stable event type identifier for all emissions.
  - Ensure payload fields exclude secrets or authorization data.
  - _Requirements: 2.2, 2.5_

- [ ] 1.2 (P) Add End-of-Session configuration options and validation
  - Provide toggles for detection, event emission, stream signal detection, tool completion detection, and dispatch timeout.
  - Validate configuration on startup and reject invalid settings.
  - Ensure configuration precedence is applied consistently across sessions.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [ ] 2. Persistence and idempotency foundation
- [ ] 2.1 Update session metrics storage to record EoS fields and migrate data
  - Add persisted EoS timestamp and signal metadata fields to session metrics.
  - Provide migration steps so existing data remains valid.
  - _Requirements: 2.7_

- [ ] 2.2 Add atomic claim and persistence behavior for EoS completion
  - Implement a concurrency-safe claim that allows only one emitter per session.
  - Persist completion metadata only when the claim succeeds.
  - Expose a fast check for already-ended sessions for hot-path dedupe.
  - _Requirements: 2.3, 2.7_

- [ ] 3. EoS detection and emission core
- [ ] 3.1 Implement EndOfSessionService for gating, dedupe, and bounded dispatch
  - Normalize incoming signals, enforce config gating, and skip when context is incomplete.
  - Use the atomic claim to guarantee at-most-once emission and mark terminal state.
  - Emit the event with a bounded wait that does not cancel in-flight handlers.
  - _Requirements: 1.1, 1.3, 1.4, 2.1, 2.3, 2.6, 2.7, 2.8, 5.1, 5.2, 5.4, 6.5_

- [ ] 3.2 Implement stream-based EoS detection across protocols and modes
  - Detect completion markers such as `[DONE]`, finish reasons, message stop, and response completion signals.
  - Ensure non-streaming responses are detected via the shared stream processing path.
  - Emit EoS signals before session finalization and skip when session identifiers are missing.
  - _Requirements: 1.2, 1.5, 1.6, 2.4, 6.1, 6.2, 6.3_

- [ ] 3.3 Implement tool-call completion detection
  - Detect completion tool calls and translate them into EoS signals.
  - Preserve tool-call execution flow and fail open if detection fails.
  - _Requirements: 6.4_

- [ ] 4. Wiring and subscription lifecycle
- [ ] 4.1 Wire EoS services into startup and processing pipelines
  - Register the EventBus early enough for EoS services to publish events.
  - Register EoS services, stream processor, and tool handler in startup.
  - Ensure all frontend protocols and response modes pass through the EoS detection path.
  - _Requirements: 1.5, 1.6, 3.1, 3.5_

- [ ] 4.2 Ensure listener dispatch isolation with correlation-aware logging
  - Subscribe listeners using a wrapper that logs failures with session identifiers.
  - Ensure one listener failure does not block or alter other listener execution.
  - Preserve the original payload for every listener invocation.
  - _Requirements: 3.2, 3.3, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5_

- [ ] 5. Subsystem subscribers and legacy refactors
- [ ] 5.1 (P) ProxyMem subscriber for EoS completion
  - Mark memory sessions complete and enqueue follow-up analysis on EoS.
  - Keep behavior idempotent for repeated signals.
  - _Requirements: 7.1_

- [ ] 5.2 (P) Usage tracking subscriber and legacy detector removal
  - Finalize usage tracking and persist completion state on EoS events.
  - Replace stream-end-based completion detection with EoS subscriber logic.
  - _Requirements: 7.2, 7.5, 7.6_

- [ ] 5.3 (P) Wire capture subscriber and metadata updates
  - Record EoS occurrence and metadata in wire capture records.
  - Remove stream-end-based completion metadata inference from capture services.
  - _Requirements: 7.3, 7.5, 7.6_

- [ ] 5.4 (P) Test reminder subscriber and legacy detector removal
  - Emit test execution reminders on EoS using existing dirty-state tracking.
  - Remove custom completion detection from reminder logic.
  - _Requirements: 7.4, 7.5, 7.6_

- [ ] 6. Verification and tests
- [ ] 6.1 Unit tests for EndOfSessionService idempotency and timeout behavior
  - Cover atomic-claim dedupe, config gating, and terminal state persistence.
  - Validate bounded dispatch timeout behavior without canceling handlers.
  - _Requirements: 1.1, 1.3, 1.4, 2.1, 2.3, 2.6, 2.7, 2.8, 5.1, 5.2, 5.4, 6.5_

- [ ] 6.2 Unit tests for stream and tool-call signal normalization
  - Cover `[DONE]`, finish reasons, response completion signals, and tool-call completion.
  - Validate behavior when session identifiers are missing.
  - _Requirements: 1.2, 1.5, 1.6, 2.4, 6.1, 6.2, 6.3, 6.4_

- [ ] 6.3 Unit tests for subscribers and listener isolation
  - Validate ProxyMem, usage tracking, wire capture, and test reminder behaviors.
  - Ensure failures are logged with correlation identifiers without blocking other listeners.
  - _Requirements: 3.2, 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 6.4 Integration tests for wiring and end-to-end emission
  - Verify DI wiring, startup registration, and dispatch to multiple listeners.
  - Cover both streaming and non-streaming EoS emission with persistence.
  - _Requirements: 1.6, 2.3, 2.6, 2.7, 3.1, 3.2, 3.5_

- [ ] 6.5 Property tests for dedupe invariants
  - Validate that multiple signals per session never produce duplicate EoS events.
  - _Requirements: 2.3, 6.5_
