# Implementation Plan

## Phase 1: Foundation - Interfaces and Base Infrastructure

- [ ] 1. Create interfaces for extracted services
  - [ ] 1.1 Create IStreamFormattingService interface
    - Define interface in `src/core/interfaces/stream_formatting_interface.py`
    - Include methods: `stream_as_sse_bytes`, `is_valid_completion_token`, `format_chunk_as_sse`, `chunk_signals_done`
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ] 1.2 Create IUsageTrackingWrapper interface
    - Define interface in `src/core/interfaces/usage_tracking_wrapper_interface.py`
    - Include method: `wrap_stream_for_usage`
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ] 1.3 Create IModelAliasResolver interface
    - Define interface in `src/core/interfaces/model_alias_resolver_interface.py`
    - Include method: `resolve`
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [ ] 1.4 Create IURIParameterApplicator interface
    - Define interface in `src/core/interfaces/uri_parameter_applicator_interface.py`
    - Include method: `apply`
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [ ] 1.5 Create IReasoningConfigApplicator interface
    - Define interface in `src/core/interfaces/reasoning_config_applicator_interface.py`
    - Include method: `apply`
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [ ] 1.6 Create IPlanningPhaseManager interface
    - Define interface in `src/core/interfaces/planning_phase_manager_interface.py`
    - Include methods: `apply_if_needed`, `update_counters`, `count_file_writes`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [ ] 1.7 Create IBackendLifecycleManager interface
    - Define interface in `src/core/interfaces/backend_lifecycle_manager_interface.py`
    - Include methods: `get_or_create`, `shutdown`, `discard`, `is_disabled`, `get_active_backends`
    - _Requirements: 11.1, 11.2, 11.3, 11.4_
  - [ ] 1.8 Create IExceptionNormalizer interface
    - Define interface in `src/core/interfaces/exception_normalizer_interface.py`
    - Include method: `normalize`
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

## Phase 2: Extract StreamFormattingService

- [ ] 2. Implement StreamFormattingService
  - [ ] 2.1 Create StreamFormattingService implementation
    - Create `src/core/services/stream_formatting_service.py`
    - Extract `_stream_as_sse_bytes`, `_is_valid_completion_token`, `_format_as_sse`, `_chunk_signals_done` from BackendService
    - Implement IStreamFormattingService interface
    - _Requirements: 5.1, 5.2, 5.3, 5.4_
  - [ ] 2.2 Write property test for SSE format consistency
    - **Property 1: SSE Format Consistency**
    - **Validates: Requirements 5.1, 5.3**
  - [ ] 2.3 Write property test for done marker detection
    - **Property 2: Done Marker Detection**
    - **Validates: Requirements 5.4**
  - [ ] 2.4 Write property test for valid token identification
    - **Property 3: Valid Token Identification**
    - **Validates: Requirements 5.2**
  - [ ] 2.5 Write unit tests for StreamFormattingService
    - Test SSE encoding for different chunk types
    - Test [DONE] marker handling
    - Test edge cases (empty chunks, malformed data)
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

## Phase 3: Extract UsageTrackingWrapper

- [ ] 3. Implement UsageTrackingWrapper
  - [ ] 3.1 Create UsageTrackingWrapper implementation
    - Create `src/core/services/usage_tracking_wrapper.py`
    - Extract `_wrap_stream_for_usage` from BackendService
    - Implement IUsageTrackingWrapper interface
    - _Requirements: 6.1, 6.2, 6.3, 6.4_
  - [ ] 3.2 Write property test for usage accumulation
    - **Property 4: Usage Accumulation**
    - **Validates: Requirements 6.2, 6.3**
  - [ ] 3.3 Write unit tests for UsageTrackingWrapper
    - Test first token time tracking
    - Test usage data accumulation
    - Test TPS calculation
    - _Requirements: 6.1, 6.2, 6.3, 6.4_

## Phase 4: Extract ModelAliasResolver

- [ ] 4. Implement ModelAliasResolver
  - [ ] 4.1 Create ModelAliasResolver implementation
    - Create `src/core/services/model_alias_resolver.py`
    - Extract `_apply_model_aliases` from BackendService
    - Implement IModelAliasResolver interface
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [ ] 4.2 Write property test for model alias round-trip
    - **Property 5: Model Alias Round-Trip**
    - **Validates: Requirements 7.1, 7.2**
  - [ ] 4.3 Write property test for alias graceful degradation
    - **Property 6: Alias Graceful Degradation**
    - **Validates: Requirements 7.3, 7.4**
  - [ ] 4.4 Write unit tests for ModelAliasResolver
    - Test regex pattern matching
    - Test capture group expansion
    - Test invalid pattern handling
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

## Phase 5: Extract URIParameterApplicator

- [ ] 5. Implement URIParameterApplicator
  - [ ] 5.1 Create URIParameterApplicator implementation
    - Create `src/core/services/uri_parameter_applicator.py`
    - Extract `_apply_uri_parameters` from BackendService
    - Implement IURIParameterApplicator interface
    - _Requirements: 8.1, 8.2, 8.3, 8.4_
  - [ ] 5.2 Write property test for parameter precedence
    - **Property 7: Parameter Precedence**
    - **Validates: Requirements 8.1, 8.2**
  - [ ] 5.3 Write property test for parameter type coercion
    - **Property 8: Parameter Type Coercion**
    - **Validates: Requirements 8.3**
  - [ ] 5.4 Write unit tests for URIParameterApplicator
    - Test parameter resolution from multiple sources
    - Test precedence rules
    - Test type coercion
    - Test edit-precision mode handling
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

- [ ] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Phase 6: Extract ReasoningConfigApplicator

- [ ] 7. Implement ReasoningConfigApplicator
  - [ ] 7.1 Create ReasoningConfigApplicator implementation
    - Create `src/core/services/reasoning_config_applicator.py`
    - Extract `_apply_reasoning_config` from BackendService
    - Implement IReasoningConfigApplicator interface
    - _Requirements: 9.1, 9.2, 9.3, 9.4_
  - [ ] 7.2 Write property test for reasoning config application
    - **Property 9: Reasoning Config Application**
    - **Validates: Requirements 9.1, 9.2**
  - [ ] 7.3 Write unit tests for ReasoningConfigApplicator
    - Test temperature, top_p, top_k application
    - Test reasoning_effort and thinking_budget
    - Test prompt prefix/suffix modification
    - Test edit-precision constraints
    - _Requirements: 9.1, 9.2, 9.3, 9.4_

## Phase 7: Extract PlanningPhaseManager

- [ ] 8. Implement PlanningPhaseManager
  - [ ] 8.1 Create PlanningPhaseManager implementation
    - Create `src/core/services/planning_phase_manager.py`
    - Extract `_apply_planning_phase_if_needed`, `_update_planning_phase_counters`, `_restore_planning_phase_route`, `_count_file_writes_in_response` from BackendService
    - Implement IPlanningPhaseManager interface
    - _Requirements: 10.1, 10.2, 10.3, 10.4_
  - [ ] 8.2 Write property test for planning phase transition
    - **Property 10: Planning Phase Transition**
    - **Validates: Requirements 10.1, 10.3**
  - [ ] 8.3 Write property test for file write counting
    - **Property 11: File Write Counting**
    - **Validates: Requirements 10.4**
  - [ ] 8.4 Write unit tests for PlanningPhaseManager
    - Test model override application
    - Test turn count tracking
    - Test file write count tracking
    - Test route restoration
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

## Phase 8: Extract BackendLifecycleManager

- [ ] 9. Implement BackendLifecycleManager
  - [ ] 9.1 Create BackendLifecycleManager implementation
    - Create `src/core/services/backend_lifecycle_manager.py`
    - Extract `_get_or_create_backend`, `_shutdown_backend`, `_discard_backend`, `_enforce_per_session_backend_limit`, `_is_per_session_cache_key`, `_resolve_per_session_backend_limit` from BackendService
    - Implement IBackendLifecycleManager interface
    - _Requirements: 11.1, 11.2, 11.3, 11.4_
  - [ ] 9.2 Write property test for backend cache LRU
    - **Property 12: Backend Cache LRU**
    - **Validates: Requirements 11.1**
  - [ ] 9.3 Write unit tests for BackendLifecycleManager
    - Test backend creation and caching
    - Test LRU eviction
    - Test backend shutdown
    - Test disabled backend tracking
    - Test recovery attempts
    - _Requirements: 11.1, 11.2, 11.3, 11.4_

## Phase 9: Extract ExceptionNormalizer

- [ ] 10. Implement ExceptionNormalizer
  - [ ] 10.1 Create ExceptionNormalizer implementation
    - Create `src/core/services/exception_normalizer.py`
    - Extract `_normalize_provider_exception` from BackendService
    - Implement IExceptionNormalizer interface
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
  - [ ] 10.2 Write property test for exception translation
    - **Property 13: Exception Translation**
    - **Validates: Requirements 12.1, 12.4**
  - [ ] 10.3 Write unit tests for ExceptionNormalizer
    - Test 429 to RateLimitExceededError translation
    - Test 4xx to InvalidRequestError translation
    - Test 5xx to BackendError translation
    - Test retry-after header preservation
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Phase 10: Refactor BackendService

- [ ] 12. Refactor BackendService to use extracted services
  - [ ] 12.1 Update BackendService constructor
    - Add optional parameters for all new service interfaces
    - Create default implementations when not provided
    - Remove inline imports from method bodies
    - _Requirements: 2.3, 2.4, 2.5_
  - [ ] 12.2 Replace inline implementations with service calls
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
  - [ ] 12.3 Remove extracted methods from BackendService
    - Delete `_stream_as_sse_bytes`, `_format_as_sse`, `_chunk_signals_done`
    - Delete `_is_valid_completion_token`
    - Delete `_wrap_stream_for_usage`
    - Delete `_apply_model_aliases`
    - Delete `_apply_uri_parameters`
    - Delete `_apply_reasoning_config`
    - Delete `_apply_planning_phase_if_needed`, `_update_planning_phase_counters`, `_restore_planning_phase_route`, `_count_file_writes_in_response`
    - Delete `_get_or_create_backend`, `_shutdown_backend`, `_discard_backend`, `_enforce_per_session_backend_limit`, `_is_per_session_cache_key`, `_resolve_per_session_backend_limit`
    - Delete `_normalize_provider_exception`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7_
  - [ ] 12.4 Write property test for API signature preservation
    - **Property 14: API Signature Preservation**
    - **Validates: Requirements 3.1-3.6**

## Phase 11: DI Container Integration

- [ ] 13. Register new services in DI container
  - [ ] 13.1 Update src/core/di/services.py
    - Add factory functions for each new service
    - Register services with their interfaces
    - Update BackendService factory to inject new services
    - _Requirements: 2.1, 2.2_
  - [ ] 13.2 Write integration tests for DI wiring
    - Test that all services are resolvable from container
    - Test that BackendService receives injected services
    - _Requirements: 2.2_

## Phase 12: Verification and Cleanup

- [ ] 14. Run full test suite and fix any regressions
  - [ ] 14.1 Run all existing BackendService tests
    - Execute `pytest tests/unit/core/services/test_backend_service*.py -v`
    - Fix any failures without modifying test expectations
    - _Requirements: 4.1, 4.4_
  - [ ] 14.2 Run integration tests
    - Execute `pytest tests/integration/ -v`
    - Fix any failures
    - _Requirements: 4.2, 4.4_
  - [ ] 14.3 Run full test suite
    - Execute `pytest -m "unit or integration" -v`
    - Ensure zero failures
    - _Requirements: 4.4_

- [ ] 15. Code quality verification
  - [ ] 15.1 Run linting and formatting
    - Execute `ruff check --fix src/core/services/*.py src/core/interfaces/*.py`
    - Execute `black src/core/services/*.py src/core/interfaces/*.py`
    - _Requirements: 13.1, 13.2_
  - [ ] 15.2 Run type checking
    - Execute `mypy src/core/services/*.py src/core/interfaces/*.py`
    - Fix any type errors
    - _Requirements: 13.3_
  - [ ] 15.3 Verify docstrings
    - Ensure all public methods have docstrings
    - _Requirements: 13.4_

- [ ] 16. Final Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.
