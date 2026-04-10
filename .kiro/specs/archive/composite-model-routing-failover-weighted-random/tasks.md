# Implementation Tasks

- [x] 1. Establish composite routing foundations (domain models, attempt context, and surface envelopes)
- [x] 1.1 Define typed composite route plans, nodes, and validation error envelopes
  - Model leaf, failover-group, and weighted-group nodes with a deterministic, serializable representation
  - Represent per-leaf selector text, normalized selector text, optional weight annotation, and leaf-local parameter bindings
  - Define a stable validation error envelope taxonomy for syntax, unsupported constructs, invalid weights, and invalid leaves
  - Ensure error envelopes are safe to surface to operators (bounded message sizes and safe selector echoing)
  - _Requirements: 4.1, 4.3, 4.4, 4.5_

- [x] 1.2 Define a request-scoped routing attempt context with a shared hop budget for composite routing
  - Track hop count, configured maximum hops, exhaustion reason, and whether meaningful output has started
  - Provide a bounded branch-history record suitable for downstream diagnostics and deterministic exhaustion errors
  - Ensure composite evaluation increments one shared budget rather than resetting independently per mechanism
  - Source the hop bound from existing configuration where available, with a safe default and deterministic behavior
  - _Requirements: 5.1, 5.2, 5.3, 5.6, 8.2_

- [x] 1.3 Define surface-aware routing input/output envelopes for the shared entry point
  - Represent routing surfaces (main, auxiliary, quality verifier, replacement bridge) explicitly in routing inputs
  - Define a routing outcome envelope for “selected target” vs “deterministic routing error” results
  - Ensure envelopes do not require external request schema changes and can be reused by all call sites
  - _Requirements: 1.1, 1.5, 8.5_

- [x] 2. Implement deterministic composite selector parsing and validation
- [x] 2.1 (P) Implement composite selector parsing with deterministic operator exclusivity and normalization
  - Parse ordered failover (`|`) and weighted choice (`^`) as flat branch lists (no mixed operators in one string)
  - Reject selectors that contain both `|` and `^` with a clear validation error before any resolution attempt
  - Normalize whitespace consistently without breaking leaf selector semantics or URI-style parameter behavior
  - Bind selector-local URI parameters to the correct composite leaf target without interpreting query-string content as composite syntax
  - Reject selectors that mix `|` and `^` operators in the same string with a clear validation error
  - _Requirements: 2.1, 3.1, 4.1, 4.2, 4.5, 6.4_

- [x] 2.2 Validate weights and reject malformed composite syntax before provider execution begins
  - Parse optional `[weight=N]` prefix annotations (immediately before the target selector) and assign default weight `1` when omitted
  - Reject non-numeric, non-positive, or otherwise invalid weights with an explicit validation error
  - Reject syntactically malformed composite selectors with errors that clearly identify composite parsing/validation as the cause
  - Reject unsupported construct mixing rather than attempting best-effort interpretation
  - _Requirements: 3.2, 3.3, 3.4, 4.3, 4.4, 4.6_

- [x] 2.3 Validate composite leaves using existing single-target selector semantics with surface-aware constraints
  - Validate each composite leaf under the existing single-target selector rules (including explicit backend rules where applicable)
  - Reject the entire composite selector when any leaf is invalid under single-target semantics
  - Ensure composite validation happens before any provider execution begins and does not trigger partial downstream side effects
  - Preserve acceptance of existing valid selector formats that remain valid under the composite grammar
  - _Requirements: 4.6, 4.7, 6.1, 6.5_

- [x] 2.4 (P) Add unit tests for parser determinism, mixed-operator rejection, URI params, and validation failures
  - Golden tests for mixed-operator rejection when `|` and `^` appear in the same selector
  - Tests for whitespace normalization and mixed-operator rejection
  - Tests for leaf-local URI param binding and preservation
  - Tests for invalid weights, malformed selectors, and unsupported construct mixing
  - Tests proving deterministic parse structure for repeated parses under the same configuration
  - Tests for weight-prefix position validation
  - _Requirements: 3.4, 4.1, 4.2, 4.3, 4.4, 4.5, 4.7_

- [x] 3. Implement weighted random branch selection as a reusable service
- [x] 3.1 (P) Implement weighted branch selection with injectable randomness and single-branch semantics
  - Select exactly one branch for each weighted node during a routing decision
  - Use relative weights and support deterministic behavior under tests via an injected RNG boundary
  - Ensure selection produces a single chosen branch without fan-out execution
  - Defensively guard against invalid weights reaching selection despite earlier validation
  - _Requirements: 3.1, 3.5_

- [x] 3.2 (P) Add unit tests for weighted selection determinism and “exactly one branch” guarantees
  - Prove deterministic selection with seeded/stubbed randomness
  - Verify higher weights increase relative selection frequency under deterministic sampling
  - Verify selection always returns exactly one branch for a routing decision
  - _Requirements: 3.5_

- [x] 4. Implement the shared composite routing entry point, leaf adapter, and coordinator execution
- [x] 4.1 Implement a shared composite routing entry point and register it for use by all routing surfaces
  - Provide one canonical composite-aware routing API used by main, auxiliary, verifier, and replacement flows
  - Preserve existing behavior for non-composite selectors (including existing selector formats and URI param semantics)
  - Route composite selectors through the same parser and validation rules regardless of initiating surface
  - Ensure composite validation completes before any provider execution begins
  - _Requirements: 1.1, 1.2, 1.3, 1.5, 4.6, 6.3_

- [x] 4.2 Implement a leaf target resolver adapter that preserves selector semantics and selector-local parameters
  - Resolve leaf selectors through the existing single-target routing behavior without reinterpretation
  - Preserve `backend:model`, model-only, backend-instance, and URI-parameter semantics for composite leaves
  - Propagate selector-local URI parameters and chosen target identity for downstream execution
  - Produce structured leaf-resolution outcomes to support diagnostics and failover decisions
  - _Requirements: 2.4, 2.5, 6.1, 6.2, 6.4_

- [x] 4.3 Implement coordinator execution for weighted nodes (choose-one branch, then resolve/execute)
  - Choose exactly one branch for weighted nodes and route to that branch for the routing decision
  - Record the chosen branch and selection context into the routing attempt context for observability
  - Ensure weighted selection does not silently fall back to other routing behaviors when resolution fails
  - _Requirements: 3.1, 3.5, 8.1_

- [x] 4.4 Implement coordinator execution for ordered failover chains with shared hop budgeting and deterministic exhaustion
  - Evaluate failover chains left-to-right and advance only when a target is rejected before meaningful output begins
  - Count failover progress across composite evaluation using the shared hop budget (no independent resets)
  - Stop failover evaluation when the configured bound is reached and return a deterministic exhaustion error
  - Return deterministic failure when all targets are exhausted or ineligible (no silent unrelated fallback)
  - _Requirements: 2.1, 2.2, 2.3, 5.1, 5.2, 5.3_

- [x] 4.5 Add unit tests for coordinator behavior (weighted selection, failover progression, shared budget enforcement, and exhaustion)
  - Test failover progression for validation rejection and ineligibility outcomes
  - Test deterministic exhaustion when all failover targets are exhausted or the hop budget is reached
  - Test that composite failover shares one hop budget with existing retry/failover mechanisms across the full routing attempt
  - Test that weighted nodes always select exactly one branch per decision
  - _Requirements: 2.2, 2.3, 3.5, 5.1, 5.2, 5.3_

- [x] 5. Integrate composite routing with runtime failure handling and streaming-output safety rules
- [x] 5.1 Implement a failure-recovery bridge that advances composite failover only when allowed
  - Classify runtime failures into “advance failover” vs “surface error” decisions for composite routing
  - Enforce the “no retry/failover after meaningful output begins” protection consistently
  - Increment the shared hop budget when runtime failures legitimately advance failover
  - Keep non-composite runtime recovery behavior unchanged
  - _Requirements: 2.2, 5.4, 5.5, 5.6_

- [x] 5.2 Ensure composite routing shares one bounded attempt budget with existing retry/failover mechanisms
  - Prevent composite failover from multiplying retries beyond the configured safety limit when combined with existing retry mechanisms
  - Ensure the shared hop budget is consumed across the full routing attempt, including runtime recovery loops
  - Return deterministic exhaustion when the shared budget is exhausted, without spawning new nested retry loops
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.6_

- [x] 5.3 Add integration tests for streaming boundaries and shared-budget behavior under composite routes
  - Verify that failures after meaningful output begins do not advance composite failover
  - Verify that pre-output failures can advance failover within the configured hop bound
  - Verify composite failover still respects the shared attempt budget under retryable failures
  - _Requirements: 2.2, 5.3, 5.5, 5.6_

- [x] 6. Wire all routing surfaces through the shared entry point and add compliance guardrails
- [x] 6.1 Update main request routing to resolve selectors exclusively through the shared entry point
  - Ensure all main-request selector resolution uses the shared entry point for both composite and non-composite selectors
  - Preserve existing request payload shape and selector field names
  - Add an automated check/test that fails if main routing bypasses the shared entry point in the future
  - _Requirements: 1.1, 1.4, 1.5, 6.3_

- [x] 6.2 Update auxiliary routing to use the shared entry point while preserving auxiliary-specific behavior
  - Resolve configured auxiliary selectors through the shared entry point for composite and leaf-only inputs
  - Preserve auxiliary-specific flags and static-route bypass behavior
  - Add integration coverage for auxiliary composite routing and diagnostics consistency
  - _Requirements: 1.1, 1.2, 6.2, 6.3, 8.5_

- [x] 6.3 Update quality verifier routing to resolve verifier selectors through the shared entry point
  - Resolve verifier model selectors through the shared entry point without schema changes
  - Preserve surface-specific selector constraints (including explicit backend requirements where applicable)
  - Add integration coverage for verifier composite routing and diagnostics consistency
  - _Requirements: 1.1, 1.2, 6.5, 8.5_

- [x] 7. Deprecate random model replacement and provide a compatibility bridge
- [x] 7.1 Implement a compatibility bridge that maps safe legacy replacement behavior into composite weighted routing
  - Translate safe replacement configurations into equivalent composite weighted routing behavior
  - Ensure the bridge routes through the same shared entry point and parser/validation rules as normal routing
  - Reject unsafe or ambiguous mappings with an explicit migration error (no silent behavior change)
  - _Requirements: 7.2, 7.4, 7.5_

- [x] 7.2 Implement deprecation messaging and surface an N+1 removal timeline to operators
  - Mark legacy random model replacement as deprecated when composite weighted routing is available
  - Surface an explicit N+1 removal timeline via operator-facing configuration validation and/or deprecation messaging
  - Ensure messaging is consistent and does not regress non-replacement routing behavior
  - _Requirements: 7.1, 7.3, 8.4_

- [x] 7.3 Add tests for replacement bridge parity, deprecation messaging, and migration errors
  - Unit tests for safe translation cases and explicit rejection cases
  - Integration tests confirming legacy replacement behavior is preserved during the deprecation window
  - Regression tests confirming deprecation metadata does not affect requests without replacement behavior
  - _Requirements: 7.1, 7.2, 7.4_

- [x] 8. Deliver consistent composite routing observability and diagnosability across all surfaces
- [x] 8.1 Implement a composite diagnostics publisher for selected targets, skipped branches, and exhaustion causes
  - Record selected target and composite-routing context into existing observability surfaces
  - Record structured skip/exhaust context that distinguishes validation rejection, ineligibility, and runtime failure categories
  - Keep diagnostics payloads bounded and preserve existing diagnostics for non-composite routing
  - _Requirements: 8.1, 8.2, 8.4_

- [x] 8.2 Ensure composite parsing/validation errors are operator-actionable and consistent across routing surfaces
  - Surface explicit errors that identify composite-selector parsing/validation as the failure cause
  - Include enough context for operators to correct selectors without leaking sensitive data
  - Keep diagnostics and error behavior consistent across main, auxiliary, and quality verifier routing
  - _Requirements: 4.3, 8.3, 8.5_

- [x] 8.3 Add integration/regression tests for composite diagnostics and error reporting across surfaces
  - Validate that successful composite routing records selected-target metadata and routing context
  - Validate that failover skips/exhaustion produce structured branch trails with deterministic error outcomes
  - Validate that non-composite routing retains existing diagnostics behavior
  - _Requirements: 8.1, 8.2, 8.4, 8.5_

- [x] 9. Prove backward compatibility and end-to-end composite behavior with regression coverage
- [x] 9.1 Add regression tests for legacy selector semantics as standalone selectors and as composite leaves
  - Verify `backend:model`, model-only, backend-instance, and URI-parameter behavior remains stable when non-composite
  - Verify selector-local URI params are preserved for the chosen composite leaf target
  - Verify surfaces with strict explicit-backend requirements keep those constraints under composite routing
  - _Requirements: 2.4, 6.1, 6.2, 6.3, 6.5_

- [x] 9.2 Add end-to-end tests for composite route strings across main, auxiliary, and verifier surfaces
  - Verify ordered failover chains route left-to-right and fail deterministically on exhaustion
  - Verify weighted random selectors route to exactly one selected target per decision under deterministic test control
  - Verify composite routing enforces the shared hop bound across the entire routing attempt including existing retry mechanisms
  - _Requirements: 1.1, 1.3, 2.1, 2.2, 2.3, 3.1, 3.5, 5.1, 5.3, 8.5_
