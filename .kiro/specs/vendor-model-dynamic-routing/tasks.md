# Implementation Plan

- [ ] 1. Establish canonical model addressing semantics
- [ ] 1.1 Implement model string parsing that uses `:` for backend selection only
  - Treat the portion before the first `:` as the backend selector, and the remainder as the model identifier (which may include `/` and additional `:` characters).
  - Treat any string without `:` as a backend-agnostic model identifier and never infer backend selection from `/` segments.
  - Ensure `backend/model` (no `:`) is treated as model-only input everywhere it is accepted.
  - _Requirements: 1.1, 1.2, 1.4, 1.5, 8.1_

- [ ] 1.2 Apply the parsing rules uniformly across all model-consuming flows
  - Ensure API request handling, internal routing, and failover logic all use the same parsing behavior.
  - Ensure explicit instance routing (`backend-instance:model`) is detected and handled without load balancing.
  - Add validation and structured errors for malformed backend selectors where explicit backend selection is required.
  - _Requirements: 1.3, 1.4, 8.3_

- [ ] 2. Build a model capability index from configured backends
- [ ] 2.1 Implement startup discovery of which instances can serve which models
  - On proxy startup, enumerate models from backend instances when supported, and fall back to configured model hints when enumeration is unavailable.
  - Ensure discovery failures do not prevent startup and result in best-effort capability coverage.
  - _Requirements: 5.1, 5.2_

- [ ] 2.2 Maintain a backend-agnostic unique model set and fast lookup mapping
  - Store model identifiers without backend prefixes and expose a unique set in backend-agnostic form.
  - Support constant-time lookup of candidate backend instances by model identifier on the request path.
  - _Requirements: 5.3, 7.3_

- [ ] 2.3 Support safe runtime updates of capability information
  - Provide a way to refresh or replace capability mappings without restarting the proxy.
  - Ensure updates are concurrency-safe and do not block request handling.
  - _Requirements: 5.4, 7.1, 7.2_

- [ ] 3. Integrate runtime availability state into candidate selection
- [ ] 3.1 Implement permanent unsupported-model tracking per backend instance
  - Track and query permanent “unsupported model on instance” signals for specific (instance, model) pairs.
  - Ensure routing excludes permanently unsupported (instance, model) pairs before attempting backend calls.
  - _Requirements: 4.4, 4.5_

- [ ] 3.2 Use instance-wide and model-specific cooldown/disablement to filter candidates
  - Treat instance cooldown as making all models unavailable for that instance during the cooldown period.
  - Treat model cooldown as making only that (instance, model) pair unavailable during the cooldown period.
  - Ensure permanently disabled instances are excluded from all routing decisions.
  - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [ ] 3.3 Ensure availability decisions are async-safe and do not block the event loop
  - Ensure concurrent requests can evaluate availability and update state safely without deadlocks.
  - _Requirements: 7.1, 7.2_

- [ ] 4. Implement dynamic routing for all supported model request variants
- [ ] 4.1 Route `backend:model` via eligible instances using Round Robin by default
  - Select among available instances of the requested backend type using a deterministic Round Robin policy.
  - If the backend has no numbered instances, treat the backend type itself as a single selectable target.
  - If no eligible instance exists at selection time, return a routing error without attempting a backend call.
  - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [ ] 4.2 Route `backend-instance:model` via the explicitly selected instance only
  - Ensure explicit instance routing never load-balances to other instances.
  - If the selected instance is unavailable, return a routing error without attempting other instances.
  - _Requirements: 1.3, 2.3_

- [ ] 4.3 Route model-only (`model` or `vendor/model`) requests across eligible instances
  - Determine the candidate set of backend instances that can serve the requested model via the capability index.
  - Select a candidate using Round Robin by default when multiple eligible instances exist.
  - If the model identifier is unknown (no candidates), return an error without attempting any backend call.
  - Enforce routing policy to optionally disable model-only routing with a clear error.
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [ ] 4.4 Ensure bounded failover attempts per request
  - Ensure the routing/execution pipeline limits the maximum number of distinct backend instances attempted for a single request.
  - _Requirements: 7.4_

- [ ] 5. Update availability state based on backend call outcomes
- [ ] 5.1 Mark authentication failures as permanent instance disablement
  - Detect authentication failures for an instance (e.g., 401/403) and mark the instance as permanently unavailable until explicitly reactivated.
  - Ensure subsequent routing excludes disabled instances.
  - _Requirements: 4.3, 4.5_

- [ ] 5.2 Mark model-not-found failures as permanent (instance, model) unsupported
  - Detect model-not-found signals for a specific backend instance and model (e.g., 404) and record the pair as permanently unsupported.
  - Ensure subsequent routing excludes that specific (instance, model) pair without impacting other models on the same instance.
  - _Requirements: 4.4, 4.5_

- [ ] 5.3 Clear temporary cooldown on success
  - When a request succeeds for a previously rate-limited (instance, model) pair, clear the temporary cooldown for that pair.
  - _Requirements: 4.6_

- [ ] 6. Expose routing and availability state for observability
- [ ] 6.1 Serve backend-agnostic model listings
  - Update the models listing endpoint to expose the backend-agnostic set of `vendor/model` identifiers derived from the capability index.
  - _Requirements: 5.3, 6.1_

- [ ] 6.2 Provide diagnostics for eligibility and availability
  - Extend diagnostics to expose instance availability state and a mapping from models to eligible backend instances.
  - Ensure diagnostics and model listings do not leak secrets.
  - _Requirements: 6.2_

- [ ] 6.3 Return structured routing errors that distinguish “unknown model” from “temporarily unavailable”
  - Ensure routing errors are consistent across `backend:model`, `backend-instance:model`, and model-only routing flows.
  - _Requirements: 2.4, 3.3, 6.3_

- [ ] 7. Enforce migration and configuration validation rules
- [ ] 7.1 Require `backend:model` format for configuration elements that express explicit backend selection
  - Validate configuration so that any explicit backend addressing uses `backend:model`, and reject ambiguous `backend/model` inputs with clear errors.
  - _Requirements: 8.2_

- [ ] 7.2 Ensure explicit-backend user-facing features reject non-`backend:model` inputs
  - Enforce strict validation for features that require explicit backend selection, returning clear error messages on invalid inputs.
  - _Requirements: 8.3_

- [ ] 8. Add comprehensive tests and verification for routing and observability
- [ ] 8.1 Add unit tests for model parsing and routing decisions
  - Cover `backend:model`, `backend-instance:model`, `vendor/model`, and plain `model` variants, including multiple `:` edge cases.
  - Assert “unknown model” and “temporarily unavailable” errors return without backend calls.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.4, 3.3, 6.3, 8.1_

- [ ] 8.2 Add unit tests for capability discovery and index behavior
  - Cover startup discovery fallbacks, backend-agnostic uniqueness rules, and runtime refresh behavior.
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 7.3_

- [ ] 8.3 Add unit tests for availability filtering and state transitions
  - Cover instance cooldown, (instance, model) cooldown, permanent disablement, permanent unsupported-model, and cooldown clearing on success.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 7.1, 7.2_

- [ ] 8.4 Add integration tests for API and DI wiring
  - Verify model-only routing selects eligible instances dynamically and respects routing policy gates.
  - Verify explicit backend routing uses Round Robin across instances and honors explicit instance selection.
  - Verify models listing and diagnostics reflect backend-agnostic model identifiers and availability state.
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.4, 5.3, 6.1, 6.2, 7.4_

- [ ] 8.5 Run focused test suite, linting, and type checks for modified areas and fix any issues found
  - _Requirements: 7.1, 7.2_
