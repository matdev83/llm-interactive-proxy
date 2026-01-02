# Implementation Plan

- [ ] 1. Validation-time DI lifecycle foundations
- [ ] 1.1 Add a validation-only provider build capability
  - Enable building a DI service provider that does not run unrelated post-build hooks.
  - Ensure the validation provider can still resolve required services deterministically.
  - Add a focused unit test proving post-build hooks do not run during validation provider creation.
  - _Requirements: 2.11, 11.1_

- [ ] 1.2 Add a safe “temporary provider” validation context
  - Introduce a lock-protected context that temporarily installs a service provider for validation and always restores the previous provider.
  - Provide a fail-fast accessor for the “currently installed provider” so stage validation does not implicitly build providers.
  - Add unit tests covering restore semantics, nested usage behavior, and failure cleanup paths.
  - _Requirements: 2.11, 11.1_

- [ ] 2. Runtime static-route configuration validation
- [ ] 2.1 Implement runtime validation for `static_route` on the final resolved configuration
  - Validate that the configured backend name exists in the registered backend set after connector auto-discovery.
  - Raise a `ConfigurationError` that includes the invalid value, available backends, expected format, and an example.
  - Implement this validation in the semantic validation layer (or an equivalent dedicated config validator module) as the single source of truth.
  - Ensure the validation entry point is callable during application build before stage execution.
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.6, 4.7, 4.8, 12.4, 14.2_

- [ ] 2.2 Add unit tests for runtime `static_route` validation
  - Cover valid values, invalid backend name, missing delimiter cases, and empty/None behavior.
  - Assert the error payload is actionable (includes example and available backend names).
  - _Requirements: 4.1, 4.2, 4.3, 4.8, 12.4_

- [ ] 3. Contracts and DI wiring for extracted validation components
- [ ] 3.1 Define DI boundary interfaces for validation, HTTP client lifecycle, and init strategies
  - Define the contracts as Protocol-style interfaces with complete type annotations.
  - Ensure contracts are mock-friendly and enforce async correctness at the boundary.
  - _Requirements: 1.2, 8.1, 8.2, 8.3_

- [ ] 3.2 Register extracted validation services via a focused backend registrar
  - Register the backend validation service and validation HTTP client manager with appropriate lifetimes.
  - Provide interface-to-implementation bindings consistent with existing DI patterns.
  - _Requirements: 2.9, 3.8, 8.4, 8.5, 8.7, 8.8_

- [ ] 4. Validation HTTP client manager
- [ ] 4.1 Write unit tests for validation HTTP client lifecycle behavior
  - Cover HTTP/2-first creation with HTTP/1.1 fallback behavior.
  - Verify immediate close on partial creation failures.
  - Verify cleanup waits for tasks with timeout and cancels as needed, clearing task references afterward.
  - _Requirements: 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 11.1, 11.4_

- [ ] 4.2 Implement the validation HTTP client manager and integrate it with DI
  - Centralize validation client creation, registration, and cleanup behind the manager.
  - Ensure cleanup is safe on both success and failure paths and emits debug-level cleanup logs.
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 12.3_

- [ ] 5. Backend validation service
- [ ] 5.1 Write unit tests for backend validation outcomes and environment behavior
  - Cover configured-backend detection across default backend, static route, and named backend configs.
  - Cover “no configured backends” permissive behavior and warnings.
  - Cover test-environment allowance behavior when no functional backends exist.
  - Cover fail-fast behavior when required dependencies are missing (no fallbacks).
  - _Requirements: 2.2, 2.4, 2.5, 2.6, 2.7, 2.10, 9.2, 9.3, 11.2, 12.2_

- [ ] 5.2 Implement backend validation using the canonical backend initialization path
  - Validate backend functionality by creating backends only via the canonical factory path (no manual instantiation).
  - Preserve current startup behavior for pass/fail decisions and error logging.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.10, 9.2, 11.2, 12.2_

- [ ] 6. Initialization strategy extraction (Strategy Pattern)
- [ ] 6.1 Implement a strategy registry with a default strategy and warning behavior
  - Allow registering and selecting strategies by connector type without modifying existing initialization code paths.
  - Keep strategies colocated with connector code to reduce cross-module coupling for new backends.
  - Ensure missing strategy uses default behavior and emits an observable warning.
  - Ensure strategy exceptions propagate with clear connector context.
  - _Requirements: 1.1, 1.3, 1.4, 1.7, 6.7, 8.6, 11.3_

- [ ] 6.2 (P) Implement the Anthropic initialization strategy
  - Preserve existing backend-specific initialization shaping behavior.
  - Ensure behavior matches current connector expectations without modifying connector runtime behavior.
  - _Requirements: 1.8, 6.5, 14.1_

- [ ] 6.3 (P) Implement the Gemini initialization strategy
  - Preserve existing backend-specific initialization shaping behavior.
  - Ensure behavior matches current connector expectations without modifying connector runtime behavior.
  - _Requirements: 1.8, 6.5, 14.1_

- [ ] 6.4 (P) Implement the OpenRouter initialization strategy
  - Preserve existing backend-specific initialization shaping behavior.
  - Ensure behavior matches current connector expectations without modifying connector runtime behavior.
  - _Requirements: 1.8, 6.5, 14.1_

- [ ] 7. Backend factory refactor to eliminate duplication
- [ ] 7.1 Refactor backend initialization to delegate augmentation to strategies
  - Remove backend-specific conditional augmentation from the factory and delegate to the strategy registry.
  - Keep the public factory API stable for callers and preserve existing connector initialization behavior.
  - Log initialization details consistently to maintain observability.
  - _Requirements: 1.5, 6.1, 6.4, 6.6, 11.3, 12.1, 14.4_

- [ ] 7.2 Add regression-focused tests for strategy-based initialization equivalence
  - Assert the factory uses strategy augmentation for known connectors and default behavior for unknown connectors.
  - Assert behavior remains backward compatible for existing configurations and connectors.
  - _Requirements: 1.4, 6.1, 6.3, 14.1, 14.2, 14.4_

- [ ] 8. Builder-managed validation lifecycle and config injection
- [ ] 8.1 Ensure the builder validates config and prepares DI before stage validation
  - Trigger connector auto-discovery before runtime static-route validation.
  - Replace the DI-registered configuration instance with the runtime configuration instance before validation begins.
  - _Requirements: 4.4, 4.7, 9.5, 14.2, 14.3_

- [ ] 8.2 Implement leak-safe stage validation using the validation provider context
  - Build a validation provider (without post-build hooks), install it via the lock-protected context, and validate all stages.
  - Ensure failure paths dispose the service collection so validation-created resources cannot leak.
  - Ensure stage validation is deterministic and does not require stage execution side effects.
  - _Requirements: 2.11, 3.10, 11.1, 11.2_

- [ ] 9. BackendStage simplification (delegation-only)
- [ ] 9.1 Refactor BackendStage to orchestration + delegation only
  - Ensure stage execution only triggers connector auto-discovery and backend DI registration.
  - Ensure stage validation only delegates to the backend validation service via the installed validation provider.
  - Ensure any validation-time cleanup is delegated to the extracted lifecycle manager (no direct resource lifecycle in the stage).
  - Update the stage documentation string to state the single responsibility of registration orchestration + validation delegation.
  - Remove legacy/fallback/manual validation and validation-time resource lifecycle behavior from the stage.
  - _Requirements: 1.6, 2.8, 3.9, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 6.2, 6.8, 9.1, 9.2, 13.2_

- [ ] 9.2 Update stage validation tests to delegation-only
  - Reduce stage validation tests to delegation coverage only and ensure they do not assert internal resource tracking state.
  - _Requirements: 7.1, 9.4_

- [ ] 10. Test migration and leak-regression repointing
- [ ] 10.1 Move static-route validation tests to config-level tests
  - Update tests to validate runtime `static_route` behavior and error payloads.
  - _Requirements: 4.1, 4.2, 4.3, 4.5, 7.7, 12.4_

- [ ] 10.2 Add comprehensive unit tests for the backend validation service
  - Migrate prior stage validation scenarios and ensure coverage meets or exceeds previous behavior.
  - Ensure the service is testable in isolation without requiring full app/stage initialization.
  - _Requirements: 7.2, 7.5, 13.3_

- [ ] 10.3 Add comprehensive unit tests for the validation HTTP client manager
  - Ensure tests cover cleanup behavior and failure paths aligned with existing leak regression expectations.
  - _Requirements: 7.3, 7.6, 11.1, 11.4_

- [ ] 10.4 Update leak regression tests to target the extracted lifecycle components
  - Repoint existing leak regression coverage from stage internals to the validation HTTP client manager and builder validation cleanup behavior.
  - _Requirements: 7.4, 9.4, 11.1_

- [ ] 11. Executable “add strategy” example
- [ ] 11.1 Add an example strategy and unit test proving OCP-compliant extension
  - Demonstrate adding a strategy without editing the factory or the stage.
  - Ensure the test asserts registry selection and default behavior for missing strategy.
  - _Requirements: 1.1, 1.4, 13.1, 13.4_

- [ ] 12. Performance and full verification
- [ ] 12.1 Add a lightweight benchmark harness for startup/validation/strategy overhead
  - Measure startup and validation durations over 10 iterations in an opt-in, non-flaky way.
  - Measure per-backend strategy augmentation overhead and ensure it stays within the target budget.
  - _Requirements: 10.1, 10.2, 10.3_

- [ ] 12.2 Run the full test suite and address regressions
  - Ensure the full test suite passes and no behavior regressions were introduced.
  - _Requirements: 7.8, 14.1, 14.2, 14.3, 14.4_
