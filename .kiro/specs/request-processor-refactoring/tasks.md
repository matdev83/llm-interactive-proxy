# Implementation Tasks: Request Processor Refactoring

- [x] 1. Establish refactoring safety rails
- [x] 1.1 Define internal phase boundaries and contracts
  - Introduce internal contracts for the request-pipeline phases described in the design
  - Ensure the existing request processor remains the DI-resolved implementation of the public request-processing contract
  - Preserve direct instantiation of the request processor in unit tests (minimal required dependencies)
  - _Requirements: 2.1, 2.2, 2.4, 3.1, 11.1, 11.2_
  - _Status: Internal interfaces created in src/core/interfaces/request_processor_internal.py (ISessionEnricher, IRequestSideEffects, ICommandHandler, IArtifactService, IBackendPreparer, IRequestTransformPipeline, IBackendExecutor)_

- [x] 1.2 Add characterization coverage for under-specified behavior
  - Identify request-processor behaviors that are not currently pinned by tests (especially fail-open paths and ordering guarantees)
  - Add tests that lock down these behaviors without changing existing tests
  - _Requirements: 1.1, 1.2, 5.2, 5.4, 5.6, 8.5, 9.7, 12.2_
  - _Status: Characterization tests created in tests/unit/core/services/test_request_processor_characterization.py covering type validation, fail-open behavior, and transformation ordering (8 passing, 2 xfail for complex ordering logic)_

- [x] 2. (P) Extract artifact preview handling
  - Preserve expansion rules for the most recent tool-message batch and compression of older previews
  - Preserve behavior when artifact paths are missing, unreadable, or not convertible
  - Keep existing preview size limits unchanged
  - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - _Status: ArtifactService extracted, registered in DI, integrated into RequestProcessor with fallback for backward compatibility, all tests passing (8 artifact service tests, 1 existing truncated outputs test, 10 characterization tests, 20 full request processor tests)_

- [x] 3. Extract session enrichment
  - Preserve session ID resolution and session loading behavior
  - Preserve agent normalization (incoming agent vs session agent) and request updates
  - Preserve client OS detection behavior and propagation into processing context
  - Preserve best-effort VTC enablement behavior and propagation into the request
  - Preserve best-effort project directory auto-resolution behavior
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8_
  - _Status: ✅ SessionEnricher extracted, registered in DI, fully integrated into RequestProcessor with fallback, all tests passing_

- [x] 4. Extract streaming and memory side effects
  - Preserve allowed tool-name registration for the current session when tools are present
  - Preserve fail-open behavior when registry updates fail
  - Preserve the ordering of project directory resolution before context injection
  - Preserve context injection and request capture behavior and fail-open handling
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - _Status: ✅ RequestSideEffects extracted, registered in DI, fully integrated into RequestProcessor with fallback, all tests passing_

- [x] 5. Extract command processing and command-only flows
  - Preserve global command-disable behavior and the backend fall-through path when disabled
  - Preserve command processing delegation and the returned processed result shape
  - Preserve command-only early returns and session recording behavior
  - Preserve special command-only behavior for agents that require it
  - Ensure artifact normalization runs for executed commands before command-only decisions
  - _Requirements: 1.3, 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Status: ✅ CommandHandler extracted, registered in DI, fully integrated into RequestProcessor with fallback, all tests passing_

- [x] 6. Extract backend request preparation and validation
  - Preserve backend request creation behavior (including the ability to skip the backend call)
  - Preserve token limit enforcement behavior, including structured validation failures
  - Preserve fail-open behavior for unexpected enforcement failures
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - _Status: ✅ BackendPreparer extracted, registered in DI, fully integrated into RequestProcessor with fallback, all tests passing_

- [x] 7. Extract request transformation pipeline
- [x] 7.1 Implement the transformation pipeline boundary and ordering
  - Preserve the fixed transformation order across all requests
  - Preserve fail-open behavior for unexpected failures in transformations
  - _Requirements: 9.7, 9.8_
  - _Status: Complete - RequestTransformPipeline class created with fixed ordering, registered in DI, integrated into RequestProcessor with fallback_

- [x] 7.2 Implement redaction behavior inside the transformation pipeline
  - Preserve configuration and session-state gating for enabling and disabling redaction
  - Preserve command-prefix precedence behavior used by redaction
  - _Requirements: 9.1, 9.2_
  - _Status: Complete - Redaction logic extracted with config precedence and fail-open behavior_

- [x] 7.3 Implement edit-precision behavior inside the transformation pipeline
  - Preserve parameter adjustment behavior based on configuration and agent exclusions
  - Preserve hybrid reasoning suppression behavior and associated state transitions
  - _Requirements: 9.3, 9.4, 9.7, 9.8_
  - _Status: Complete - Edit precision logic extracted with agent exclusion, force-apply, and hybrid reasoning suppression_

- [x] 7.4 Implement tool filtering behavior inside the transformation pipeline
  - Preserve filtering behavior when tools are present and policy service is available
  - Preserve tool-choice adjustment when the referenced tool is removed
  - Preserve metadata injection into the outbound request for observability
  - _Requirements: 9.5, 9.6, 9.7, 9.8_
  - _Status: Complete - Tool filtering logic extracted with metadata injection, telemetry, and tool-choice adjustment_

- [x] 8. Extract backend execution and persistence side effects
  - Preserve session ID injection into outbound request metadata prior to execution
  - Preserve backend invocation semantics and error propagation
  - Preserve session history updates and best-effort fingerprint updates
  - Preserve turn completion behavior that must run in a finally block when replacement state exists
  - _Requirements: 1.4, 1.5, 1.6, 1.7, 10.1, 10.2, 10.3, 10.4_
  - _Status: ✅ BackendExecutor extracted, registered in DI, fully integrated into RequestProcessor with fallback, all tests passing (10 new BackendExecutor tests, 1735 total unit tests green)_

- [x] 9. Final orchestration refactor and verification
  - [x] 9.1 Reduce the request processor to orchestration and validate overall behavior
  - Ensure orchestration remains readable and delegates all phase logic to extracted components
  - Validate method size and maintainability constraints are met
  - Validate DI wiring works under staged initialization and legacy container paths
  - Run the full test suite to confirm no regressions
  - _Requirements: 1.1, 1.2, 2.3, 3.2, 11.3, 11.4, 12.1, 12.3_
  - [x] 9.2 Get rid of legacy
  - This is alpha stage project, as long as the test suite is green we don't need to keep any legacy code to maintain backwards compability
  - Look for any leftovers of the old implementation architecture of this class,
  - Check if they are now safe to completely remove (that is only if fully replaced by the new modular code),
  - Check if all legacy code paths are now gone,
  - Validate all of the new code implemented during this whole effort in steps 1-9 is now fully and properly wired-in and used as main hot code path,
  - Ensure no fallbacks to legacy code exist nor are needed - if noticed any, thats a red flag - RISE ALERT,
