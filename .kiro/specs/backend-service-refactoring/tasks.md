# Implementation Plan

## Phase 1: Foundation - Interfaces and Base Infrastructure

- [x] 1. Create interfaces for extracted services
  - [x] 1.1 Create IStreamFormattingService interface
    - Define interface in `src/core/interfaces/stream_formatting_interface.py`
    - Include methods: `stream_as_sse_bytes`, `is_valid_completion_token`, `format_chunk_as_sse`, `chunk_signals_done`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [x] 1.2 Create IUsageTrackingWrapper interface
    - Define interface in `src/core/interfaces/usage_tracking_wrapper_interface.py`
    - Include method: `wrap_stream_for_usage`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [x] 1.3 Create IModelAliasResolver interface
    - Define interface in `src/core/interfaces/model_alias_resolver_interface.py`
    - Include method: `resolve`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [x] 1.4 Create IURIParameterApplicator interface
    - Define interface in `src/core/interfaces/uri_parameter_applicator_interface.py`
    - Include method: `apply`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [x] 1.5 Create IReasoningConfigApplicator interface
    - Define interface in `src/core/interfaces/reasoning_config_applicator_interface.py`
    - Include method: `apply`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [x] 1.6 Create IPlanningPhaseManager interface
    - Define interface in `src/core/interfaces/planning_phase_manager_interface.py`
    - Include methods: `apply_if_needed`, `update_counters`, `count_file_writes`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [x] 1.7 Create IBackendLifecycleManager interface
    - Define interface in `src/core/interfaces/backend_lifecycle_manager_interface.py`
    - Include methods: `get_or_create`, `shutdown`, `discard`, `is_disabled`, `get_active_backends`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_
  - [x] 1.8 Create IExceptionNormalizer interface
    - Define interface in `src/core/interfaces/exception_normalizer_interface.py`
    - Include method: `normalize`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
  - [x] 1.9 Phase 1 checkpoint: validate interfaces and baseline tests
    - Run ruff/black/mypy on new interface files.
    - Run a quick baseline subset to ensure no accidental breaks: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service_targeted.py -v`
    - Proceed only if green.
    - _Requirements: 4.4, 13.1, 13.2, 13.3_

## Cross-Cutting: Incremental Integration Loop (repeat per extracted service)

- [x] For each extracted service, follow TDD (red‑green‑refactor):
  - **Red:** Write new unit/property/equivalence tests against the new service API. Use the current BackendService helper output as the oracle to lock in behavior.
  - **Green:** Implement the extracted service by moving code from BackendService until the new tests pass.
  - **Refactor:** Replace the corresponding BackendService helper body with a thin delegating wrapper to the new service.
  - Run the focused existing tests that cover that helper before moving on; only proceed when green.
  - Focused test commands:
    - StreamFormattingService: `./.venv/Scripts/python.exe -m pytest tests/unit/transport/test_streaming_done_marker.py tests/unit/transport/test_sse_formatting_fix.py tests/unit/transport/test_streaming_usage_propagation.py -v`
    - UsageTrackingWrapper: `./.venv/Scripts/python.exe -m pytest tests/unit/transport/test_streaming_usage_propagation.py -v`
    - ModelAliasResolver: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_model_name_rewrites.py -v`
    - URIParameterApplicator: `./.venv/Scripts/python.exe -m pytest tests/integration/test_uri_parameters_e2e.py -v`
    - ReasoningConfigApplicator: `./.venv/Scripts/python.exe -m pytest tests/integration/test_prompt_prefix_suffix.py tests/integration/test_reasoning_*.py -v`
    - PlanningPhaseManager: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_planning_phase.py -v`
    - BackendLifecycleManager: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service_targeted.py tests/reproduction/test_cross_session_leak.py -v`
    - ExceptionNormalizer: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service_rate_limit_cooldown.py -v`
  - _Requirements: 4.1, 4.4, 4.5, 4.6_

## Cross-Cutting: Safety and Recovery Practices

- [x] Work in small, reviewable slices:
  - One extracted service + its delegating wrappers per PR/commit.
  - Avoid mixing multiple phases in a single change.
  - _Requirements: 4.4, 4.6_
- [x] Create rollback points:
  - Commit after each phase checkpoint passes so `git bisect`/revert is trivial.
  - Keep commits mechanical (move code, add tests, wire DI).
  - _Requirements: 4.4_
- [x] Keep production path stable throughout:
  - Delegating wrappers must be in place before removing inline logic.
  - BackendService must remain fully functional between phases.
  - _Requirements: 4.5, 4.6_
- [x] Run per-file QA on new/changed Python files:
  - `./.venv/Scripts/python.exe -m ruff check --fix <file>`
  - `./.venv/Scripts/python.exe -m black <file>`
  - `./.venv/Scripts/python.exe -m mypy <file>`
  - _Requirements: 13.1, 13.2, 13.3_

## Phase 2: Extract StreamFormattingService

- [x] 2. Implement StreamFormattingService
  - [x] 2.1 Write property test for SSE format consistency (red)
    - **Property 1: SSE Format Consistency**
    - **Validates: Requirements 5.1, 5.3**
  - [x] 2.2 Write property test for done marker detection (red)
    - **Property 2: Done Marker Detection**
    - **Validates: Requirements 5.4**
  - [x] 2.3 Write property test for valid token identification (red)
    - **Property 3: Valid Token Identification**
    - **Validates: Requirements 5.2**
  - [x] 2.4 Write unit/equivalence tests for StreamFormattingService (red)
    - Test SSE encoding for different chunk types
    - Test [DONE] marker handling and pass-through of already framed `data:` chunks
    - Test edge cases (empty chunks, malformed data)
    - Compare `StreamFormattingService` outputs to `BackendService._stream_as_sse_bytes` and `_is_valid_completion_token` on representative fixtures
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 4.6_
  - [x] 2.5 Create StreamFormattingService implementation (green)
    - Create `src/core/services/stream_formatting_service.py`
    - Extract `_stream_as_sse_bytes`, `_is_valid_completion_token`, `_format_as_sse`, `_chunk_signals_done` from BackendService
    - Implement IStreamFormattingService interface
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 4.6_
  - [x] 2.6 Phase 2 checkpoint: run focused + smoke tests
    - Run the StreamFormattingService focused suite (see Incremental Integration Loop)
    - Then run a quick BackendService smoke subset: `./.venv/Scripts/python.exe -m pytest tests/unit/transport/test_streaming_done_marker.py tests/unit/core/services/test_backend_service_targeted.py -v`
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 3: Extract UsageTrackingWrapper

- [x] 3. Implement UsageTrackingWrapper
  - [x] 3.1 Write property test for usage accumulation (red)
    - **Property 4: Usage Accumulation**
    - **Validates: Requirements 6.2, 6.3**
  - [x] 3.2 Write unit/equivalence tests for UsageTrackingWrapper (red)
    - Test first token time tracking
    - Test usage data accumulation
    - Test TPS calculation
    - Compare wrapper behavior to `BackendService._wrap_stream_for_usage` on fixtures
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 4.6_
  - [x] 3.3 Create UsageTrackingWrapper implementation (green)
    - Create `src/core/services/usage_tracking_wrapper.py`
    - Extract `_wrap_stream_for_usage` from BackendService
    - Implement IUsageTrackingWrapper interface
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 4.6_
  - [x] 3.4 Phase 3 checkpoint: run focused + smoke tests
    - Run the UsageTrackingWrapper focused suite (see Incremental Integration Loop)
    - Then run: `./.venv/Scripts/python.exe -m pytest tests/unit/transport/test_streaming_usage_propagation.py -v`
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 4: Extract ModelAliasResolver

- [x] 4. Implement ModelAliasResolver
  - [x] 4.1 Write property test for model alias round-trip (red)
    - **Property 5: Model Alias Round-Trip**
    - **Validates: Requirements 7.1, 7.2**
  - [x] 4.2 Write property test for alias graceful degradation (red)
    - **Property 6: Alias Graceful Degradation**
    - **Validates: Requirements 7.3, 7.4**
  - [x] 4.3 Write unit/equivalence tests for ModelAliasResolver (red)
    - Test regex pattern matching
    - Test capture group expansion
    - Test invalid pattern handling
    - Compare to `BackendService._apply_model_aliases` behavior on fixtures
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 4.6_
  - [x] 4.4 Create ModelAliasResolver implementation (green)
    - Create `src/core/services/model_alias_resolver.py`
    - Extract `_apply_model_aliases` from BackendService
    - Implement IModelAliasResolver interface
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 4.6_
  - [x] 4.5 Phase 4 checkpoint: run focused tests
    - Run the ModelAliasResolver focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 5: Extract URIParameterApplicator

- [x] 5. Implement URIParameterApplicator
  - [x] 5.1 Write property test for parameter precedence (red)
    - **Property 7: Parameter Precedence**
    - **Validates: Requirements 8.1, 8.2**
  - [x] 5.2 Write property test for parameter type coercion (red)
    - **Property 8: Parameter Type Coercion**
    - **Validates: Requirements 8.3**
  - [x] 5.3 Write unit/equivalence tests for URIParameterApplicator (red)
    - Test parameter resolution from multiple sources
    - Test precedence rules
    - Test type coercion
    - Test edit-precision mode handling
    - Compare to `BackendService._apply_uri_parameters` behavior on fixtures
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 4.6_
  - [x] 5.4 Create URIParameterApplicator implementation (green)
    - Create `src/core/services/uri_parameter_applicator.py`
    - Extract `_apply_uri_parameters` from BackendService
    - Implement IURIParameterApplicator interface
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 4.6_
  - [x] 5.5 Phase 5 checkpoint: run focused tests
    - Run the URIParameterApplicator focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 4.4_

## Phase 6: Extract ReasoningConfigApplicator

- [x] 7. Implement ReasoningConfigApplicator
  - [x] 7.1 Write property test for reasoning config application (red)
    - **Property 9: Reasoning Config Application**
    - **Validates: Requirements 9.1, 9.2**
  - [x] 7.2 Write unit/equivalence tests for ReasoningConfigApplicator (red)
    - Test temperature, top_p, top_k application
    - Test reasoning_effort and thinking_budget
    - Test prompt prefix/suffix modification
    - Test edit-precision constraints
    - Compare to `BackendService._apply_reasoning_config` behavior on fixtures
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 4.6_
  - [x] 7.3 Create ReasoningConfigApplicator implementation (green)
    - Create `src/core/services/reasoning_config_applicator.py`
    - Extract `_apply_reasoning_config` from BackendService
    - Implement IReasoningConfigApplicator interface
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 4.6_
  - [x] 7.4 Phase 6 checkpoint: run focused tests
    - Run the ReasoningConfigApplicator focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 7: Extract PlanningPhaseManager

- [x] 8. Implement PlanningPhaseManager
  - [x] 8.1 Write property test for planning phase transition (red)
    - **Property 10: Planning Phase Transition**
    - **Validates: Requirements 10.1, 10.3**
  - [x] 8.2 Write property test for file write counting (red)
    - **Property 11: File Write Counting**
    - **Validates: Requirements 10.4**
  - [x] 8.3 Write unit/equivalence tests for PlanningPhaseManager (red)
    - Test model override application
    - Test turn count tracking
    - Test file write count tracking
    - Test route restoration
    - Compare to current planning-phase helpers on fixtures
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 4.6_
  - [x] 8.4 Create PlanningPhaseManager implementation (green)
    - Create `src/core/services/planning_phase_manager.py`
    - Extract `_apply_planning_phase_if_needed`, `_update_planning_phase_counters`, `_restore_planning_phase_route`, `_count_file_writes_in_response` from BackendService
    - Implement IPlanningPhaseManager interface
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 4.6_
  - [x] 8.5 Phase 7 checkpoint: run focused tests
    - Run the PlanningPhaseManager focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 8: Extract BackendLifecycleManager

- [x] 9. Implement BackendLifecycleManager
  - [x] 9.1 Write property test for backend cache LRU (red)
    - **Property 12: Backend Cache LRU**
    - **Validates: Requirements 11.1**
  - [x] 9.2 Write unit/equivalence tests for BackendLifecycleManager (red)
    - Test backend creation and caching
    - Test LRU eviction
    - Test backend shutdown
    - Test disabled backend tracking
    - Test recovery attempts
    - Compare to lifecycle helpers on fixtures (cache keys, eviction, disablement)
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 4.6_
  - [x] 9.3 Create BackendLifecycleManager implementation (green)
    - Create `src/core/services/backend_lifecycle_manager.py`
    - Extract `_get_or_create_backend`, `_shutdown_backend`, `_discard_backend`, `_enforce_per_session_backend_limit`, `_is_per_session_cache_key`, `_resolve_per_session_backend_limit` from BackendService
    - Implement IBackendLifecycleManager interface
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 4.6_
  - [x] 9.4 Phase 8 checkpoint: run focused tests
    - Run the BackendLifecycleManager focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

## Phase 9: Extract ExceptionNormalizer

- [x] 10. Implement ExceptionNormalizer
  - [x] 10.1 Write property test for exception translation (red)
    - **Property 13: Exception Translation**
    - **Validates: Requirements 12.1, 12.4**
  - [x] 10.2 Write unit/equivalence tests for ExceptionNormalizer (red)
    - Test 429 to RateLimitExceededError translation
    - Test 4xx to InvalidRequestError translation
    - Test 5xx to BackendError translation
    - Test retry-after header preservation
    - Compare to `BackendService._normalize_provider_exception` on fixtures
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 4.6_
  - [x] 10.3 Create ExceptionNormalizer implementation (green)
    - Create `src/core/services/exception_normalizer.py`
    - Extract `_normalize_provider_exception` from BackendService
    - Implement IExceptionNormalizer interface
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 4.6_
  - [x] 10.4 Phase 9 checkpoint: run focused tests
    - Run the ExceptionNormalizer focused suite (see Incremental Integration Loop)
    - Proceed only if green
    - _Requirements: 4.1, 4.4, 4.6_

- [x] 11. Checkpoint - Ensure all tests pass
  - ExceptionNormalizer focused tests pass. Some unrelated tests fail due to pre-existing issues.
  - _Requirements: 4.4_

## Phase 10: Refactor BackendService

- [x] 12. Refactor BackendService to use extracted services
  - [x] 12.1 Update BackendService constructor
    - Add optional parameters for all new service interfaces
    - Create default implementations when not provided
    - Remove inline imports from method bodies
    - _Requirements: 2.3, 2.4, 2.5_
  - [x] 12.2 Replace inline implementations with service calls
    - Replace `_stream_as_sse_bytes` with `stream_formatting_service.stream_as_sse_bytes`
    - Replace `_is_valid_completion_token` with `stream_formatting_service.is_valid_completion_token`
    - Replace `_wrap_stream_for_usage` with `usage_tracking_wrapper.wrap_stream_for_usage`
    - Replace `_apply_model_aliases` with `model_alias_resolver.resolve`
    - Replace `_apply_uri_parameters` with `uri_parameter_applicator.apply`
    - Replace `_apply_reasoning_config` with `reasoning_config_applicator.apply`
    - Replace planning phase methods with `planning_phase_manager` calls
    - Replace backend lifecycle methods with `backend_lifecycle_manager` calls
    - Replace `_normalize_provider_exception` with `exception_normalizer.normalize`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_
  - [x] 12.3 Replace extracted methods with delegating wrappers
    - Keep the existing helper/private method names and signatures in BackendService
    - Replace their bodies to call the corresponding extracted service
    - Ensure existing tests and debugging scripts continue to work unchanged
    - _Requirements: 4.5_
- [x] 12.4 Write property test for API signature preservation
    - **Property 14: API Signature Preservation**
    - **Validates: Requirements 3.1-3.6**
  - [x] 12.5 Phase 10 checkpoint: run BackendService regression suite
    - Run all existing BackendService unit tests: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service*.py -v`
    - Run high-signal integration subset: `./.venv/Scripts/python.exe -m pytest tests/integration/test_uri_parameters_e2e.py tests/integration/test_reasoning_*.py -v`
    - Proceed only if green.
    - _Requirements: 3.1, 3.2, 3.3, 4.1, 4.2, 4.4_

## Phase 11: DI Container Integration

- [x] 13. Register new services in DI container
  - [x] 13.1 Update src/core/di/services.py
    - Add factory functions for each new service
    - Register services with their interfaces
    - Update BackendService factory to inject new services
    - _Requirements: 2.1, 2.2_
  - [x] 13.2 Write integration tests for DI wiring
    - Test that all services are resolvable from container
    - Test that BackendService receives injected services
    - _Requirements: 2.2_
  - [x] 13.3 Phase 11 checkpoint: run container + BackendService smoke
    - Run DI wiring tests plus BackendService targeted suite: `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service_targeted.py tests/integration/test_models_endpoints.py -v`
    - Proceed only if green.
    - _Requirements: 2.2, 4.4_

## Phase 12: Verification and Cleanup

- [x] 14. Run full test suite and fix any regressions
  - Verification evidence:
    - Full suite (unit+integration) was run manually after fixes: `0 failed, 9380 passed, 93 skipped in 149.52s (0:02:29)` (reported by maintainer).
  - [x] 14.1 Run all existing BackendService tests
    - Execute `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service*.py -v`
    - Fix any failures without modifying test expectations
    - _Requirements: 4.1, 4.4_
  - [x] 14.2 Run integration tests
    - Execute `./.venv/Scripts/python.exe -m pytest tests/integration/ -v`
    - Fix any failures
    - _Requirements: 4.2, 4.4_
  - [x] 14.3 Run full test suite
    - Execute `./.venv/Scripts/python.exe -m pytest -m "unit or integration" -v`
    - Ensure zero failures
    - _Requirements: 4.4_

- [x] 15. Code quality verification
  - [x] 15.1 Run linting and formatting
    - Execute `./.venv/Scripts/python.exe -m ruff check --fix src/core/services/*.py src/core/interfaces/*.py`
    - Execute `./.venv/Scripts/python.exe -m black src/core/services/*.py src/core/interfaces/*.py`
    - _Requirements: 13.1, 13.2_
  - [x] 15.2 Run type checking
    - Execute `./.venv/Scripts/python.exe -m mypy src/core/services/*.py src/core/interfaces/*.py`
    - Fix any type errors
    - _Requirements: 13.3_
  - [x] 15.3 Verify docstrings
    - Ensure all public methods have docstrings
    - _Requirements: 13.4_

- [x] 16. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
  - _Requirements: 4.4_
