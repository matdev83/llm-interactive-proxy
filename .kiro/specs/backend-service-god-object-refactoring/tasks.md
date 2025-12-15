# Implementation Plan: BackendService God Object Refactoring

## Task Format

Tasks are organized by implementation phase. Each task maps to specific requirements and builds incrementally toward the complete refactoring.

---

## Phase 1: Interface Definitions

- [ ] 1. Define interfaces for new services
- [ ] 1.1 (P) Define IBackendModelResolver interface
  - Create `src/core/interfaces/backend_model_resolver_interface.py`
  - Define `resolve_backend_and_model` method with proper type hints
  - Define `synchronize_request_with_target` method with proper type hints
  - Document preconditions and postconditions in docstrings
  - Follow `I*` naming convention
  - _Requirements: 1.3, 2.1, 7.1, 7.2_

- [ ] 1.2 (P) Define IRequestTransformer interface
  - Create `src/core/interfaces/request_transformer_interface.py`
  - Define `apply_model_aliases`, `apply_reasoning_config`, `apply_uri_parameters` methods
  - Define `transform_request` method that coordinates all transformations
  - Document transformation order requirement (aliases → reasoning → URI params)
  - Follow `I*` naming convention
  - _Requirements: 1.4, 2.1, 8.1, 8.2, 8.4_

- [ ] 1.3 (P) Define IStreamProcessor interface
  - Create `src/core/interfaces/stream_processor_interface.py`
  - Define `stream_as_sse_bytes` method for SSE encoding
  - Define `resolve_stream_session_id` method for session ID resolution
  - Define `is_valid_completion_token` method for token validation
  - Document format preservation requirements
  - Follow `I*` naming convention
  - _Requirements: 1.6, 2.1, 9.1, 9.2, 9.3, 9.6_

- [ ] 1.4 (P) Define IFailureStrategyExecutor interface
  - Create `src/core/interfaces/failure_strategy_executor_interface.py`
  - Define `apply_failure_strategy` method with failure decision return type
  - Document integration with IFailureHandlingStrategy
  - Document decision preservation requirements
  - Follow `I*` naming convention
  - _Requirements: 1.7, 2.1, 11.1, 11.2, 11.4_

- [ ] 1.5 (P) Define IFailoverPlanGenerator interface
  - Create `src/core/interfaces/failover_plan_generator_interface.py`
  - Define `get_failover_plan` method for plan generation
  - Define `filter_unhealthy_backends` method for health filtering
  - Document integration with IFailoverCoordinator
  - Follow `I*` naming convention
  - _Requirements: 1.2, 2.1, 6.1, 6.2_

- [ ] 1.6 (P) Define IComplexFailoverExecutor interface
  - Create `src/core/interfaces/complex_failover_executor_interface.py`
  - Define `execute_complex_failover` method for complex failover execution
  - Define `attempt_failover_plan` method for plan attempts
  - Document recursive call requirements (allow_failover=False)
  - Follow `I*` naming convention
  - _Requirements: 1.2, 2.1, 6.3_

## Phase 2: Service Implementations

- [ ] 2. Implement BackendModelResolver service
- [ ] 2.1 Create BackendModelResolver implementation
  - Create `src/core/services/backend_model_resolver.py`
  - Implement `resolve_backend_and_model` method extracting logic from BackendService._resolve_backend_and_model
  - Preserve exact behavior: session resolution, planning phase application, model alias resolution, backend routing, URI parameter parsing, static route override
  - Handle all side effects: planning_phase_manager.apply_if_needed(), backend_lifecycle_manager.get_disabled_backends()
  - Maintain transformation order: model aliases applied before backend parsing
  - Inject dependencies: BackendRoutingService, ModelAliasResolver, PlanningPhaseManager, IBackendLifecycleManager, ISessionService, IConfig
  - Use async/await for all I/O operations
  - _Requirements: 1.3, 2.3, 2.4, 2.5, 7.1, 7.2, 7.3, 7.4, 7.5_

- [ ] 2.2 Implement synchronize_request_with_target method
  - Extract logic from BackendService._synchronize_request_with_target
  - Preserve request synchronization behavior: update model if backend overridden, update extra_body with backend_type and model
  - Handle edge cases: preserve original model format when backend matches, remove stale backend_type
  - Return updated ChatRequest with model_copy
  - _Requirements: 1.3, 7.2, 7.5_

- [ ] 3. Implement RequestTransformer service
- [ ] 3.1 Create RequestTransformer implementation
  - Create `src/core/services/request_transformer.py`
  - Implement `apply_model_aliases` method delegating to ModelAliasResolver
  - Implement `apply_reasoning_config` method delegating to ReasoningConfigApplicator
  - Implement `apply_uri_parameters` method delegating to URIParameterApplicator
  - Implement `transform_request` method coordinating all transformations in correct order
  - Preserve transformation order: aliases → reasoning → URI parameters
  - Inject dependencies: ModelAliasResolver, ReasoningConfigApplicator, URIParameterApplicator
  - Handle errors gracefully, preserve existing error types
  - _Requirements: 1.4, 2.3, 2.4, 2.5, 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 4. Implement StreamProcessor service
- [ ] 4.1 Create StreamProcessor implementation
  - Create `src/core/services/stream_processor.py`
  - Implement `stream_as_sse_bytes` method delegating to StreamFormattingService
  - Implement `resolve_stream_session_id` method extracting logic from BackendService._resolve_stream_session_id
  - Preserve session ID resolution fallback: context.session_id → request.session_id → request.extra_body.session_id → context.request_id → uuid4().hex
  - Implement `is_valid_completion_token` method delegating to StreamFormattingService
  - Preserve SSE encoding format exactly matching current implementation
  - Inject dependency: IStreamFormattingService
  - Handle edge cases: None values, missing attributes, exception handling
  - _Requirements: 1.6, 2.3, 2.4, 2.5, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [ ] 5. Implement FailureStrategyExecutor service
- [ ] 5.1 Create FailureStrategyExecutor implementation
  - Create `src/core/services/failure_strategy_executor.py`
  - Implement `apply_failure_strategy` method extracting logic from BackendService._apply_failure_strategy
  - Preserve failure decision logic: calculate elapsed_time, find available_backends via BackendRoutingService, call IFailureHandlingStrategy.decide()
  - Return tuple of (FailureDecision, wait_seconds, next_backend) matching current implementation
  - Handle None failure_strategy case: return SURFACE_ERROR decision
  - Inject dependencies: IFailureHandlingStrategy (optional), BackendRoutingService (optional)
  - Preserve logging behavior and decision reasoning
  - _Requirements: 1.7, 2.3, 2.4, 2.5, 11.1, 11.2, 11.3, 11.4, 11.5_

- [ ] 6. Implement FailoverPlanGenerator service
- [ ] 6.1 Create FailoverPlanGenerator implementation
  - Create `src/core/services/failover_plan_generator.py`
  - Implement `get_failover_plan` method extracting logic from BackendService._get_failover_plan
  - Preserve failover plan generation: check use_failover_strategy flag, try IFailoverStrategy.get_failover_plan(), fallback to IFailoverCoordinator.get_failover_attempts()
  - Convert FailoverAttempt objects to (backend, model) tuples
  - Call filter_unhealthy_backends on generated plan
  - Handle errors gracefully, fallback to coordinator on strategy errors
  - Inject dependencies: IFailoverCoordinator, IBackendLifecycleManager, IConfig, IApplicationState, IFailoverStrategy (optional)
  - _Requirements: 1.2, 2.3, 2.4, 2.5, 6.1, 6.4_

- [ ] 6.2 Implement filter_unhealthy_backends method
  - Extract logic from BackendService._filter_unhealthy_backends
  - Preserve health filtering: check circuit_breaker_enabled, filter permanently disabled backends, filter unhealthy endpoints via is_backend_functional()
  - Handle session-scoped backends: check "{backend}:default" cache key
  - Fallback to original plan if all backends filtered (preserve existing behavior)
  - Preserve logging for filtered backends
  - _Requirements: 1.2, 6.2, 6.4_

- [ ] 7. Implement ComplexFailoverExecutor service
- [ ] 7.1 Create ComplexFailoverExecutor implementation
  - Create `src/core/services/complex_failover_executor.py`
  - Implement `execute_complex_failover` method extracting logic from BackendService._execute_complex_failover
  - Preserve complex failover execution: create BackendConfiguration, get failover plan, call attempt_failover_plan
  - Handle errors: wrap non-BackendError exceptions in BackendError with "all backends failed" message
  - Inject dependencies: IFailoverCoordinator, IBackendLifecycleManager, IBackendModelResolver, IBackendService (for recursive calls)
  - _Requirements: 1.2, 2.3, 2.4, 2.5, 6.3, 6.5_

- [ ] 7.2 Implement attempt_failover_plan method
  - Extract logic from BackendService._attempt_failover_plan
  - Preserve failover attempt logic: iterate through plan, create attempt_request with backend_type and model, call BackendService.call_completion with allow_failover=False
  - Handle errors: catch BackendError and RateLimitExceededError, continue to next attempt, raise BackendError if all fail
  - Preserve error wrapping: include last_error message in final BackendError
  - Preserve logging for each failed attempt
  - Ensure recursive calls use allow_failover=False to prevent infinite loops
  - _Requirements: 1.2, 6.3, 6.5_

## Phase 3: Dependency Injection Registration

- [ ] 8. Register new services in DI container
- [ ] 8.1 Register BackendModelResolver in DI container
  - Add factory function `_backend_model_resolver_factory` in `src/core/di/services.py`
  - Resolve all dependencies via IServiceProvider: BackendRoutingService, ModelAliasResolver, PlanningPhaseManager, IBackendLifecycleManager, ISessionService, IConfig
  - Register as singleton with interface binding: `_add_singleton(IBackendModelResolver, implementation_factory=_backend_model_resolver_factory)`
  - Ensure registration happens in CoreServicesStage before BackendService registration
  - _Requirements: 2.2, 2.7_

- [ ] 8.2 Register RequestTransformer in DI container
  - Add factory function `_request_transformer_factory` in `src/core/di/services.py`
  - Resolve dependencies: ModelAliasResolver, ReasoningConfigApplicator, URIParameterApplicator
  - Register as singleton with interface binding
  - Ensure registration happens before BackendService registration
  - _Requirements: 2.2, 2.7_

- [ ] 8.3 Register StreamProcessor in DI container
  - Add factory function `_stream_processor_factory` in `src/core/di/services.py`
  - Resolve dependency: IStreamFormattingService
  - Register as singleton with interface binding
  - Ensure registration happens before BackendService registration
  - _Requirements: 2.2, 2.7_

- [ ] 8.4 Register FailureStrategyExecutor in DI container
  - Add factory function `_failure_strategy_executor_factory` in `src/core/di/services.py`
  - Resolve optional dependencies: IFailureHandlingStrategy, BackendRoutingService (use get_service for optional)
  - Register as singleton with interface binding
  - Ensure registration happens before BackendService registration
  - _Requirements: 2.2, 2.7_

- [ ] 8.5 Register FailoverPlanGenerator in DI container
  - Add factory function `_failover_plan_generator_factory` in `src/core/di/services.py`
  - Resolve dependencies: IFailoverCoordinator, IBackendLifecycleManager, IConfig, IApplicationState (optional), IFailoverStrategy (optional)
  - Register as singleton with interface binding
  - Ensure registration happens before BackendService registration
  - _Requirements: 2.2, 2.7_

- [ ] 8.6 Register ComplexFailoverExecutor in DI container
  - Add factory function `_complex_failover_executor_factory` in `src/core/di/services.py`
  - Resolve dependencies: IFailoverCoordinator, IBackendLifecycleManager, IBackendModelResolver, IBackendService
  - Register as singleton with interface binding
  - Ensure registration happens before BackendService registration
  - Note: IBackendService dependency creates circular reference - handle via late binding or service locator pattern
  - _Requirements: 2.2, 2.7_

## Phase 4: BackendService Refactoring

- [ ] 9. Refactor BackendService constructor
- [ ] 9.1 Update BackendService constructor to require all dependencies
  - Remove all optional parameters with inline instantiation patterns
  - Require all new services via constructor: IBackendModelResolver, IRequestTransformer, IStreamProcessor, IFailureStrategyExecutor, IFailoverPlanGenerator, IComplexFailoverExecutor
  - Remove conditional service creation logic (`if service is None: create_default()`)
  - Remove inline imports and service instantiation from constructor
  - Preserve existing required dependencies (factory, rate_limiter, config, session_service, app_state, etc.)
  - Update constructor docstring to document all dependencies
  - _Requirements: 2.3, 2.4, 2.6, 12.1_

- [ ] 9.2 Update BackendService to delegate to BackendModelResolver
  - Replace `_resolve_backend_and_model` implementation with delegation to `backend_model_resolver.resolve_backend_and_model`
  - Replace `_synchronize_request_with_target` implementation with delegation to `backend_model_resolver.synchronize_request_with_target`
  - Keep methods as thin wrappers preserving exact signatures for backward compatibility
  - Update `call_completion` method to use delegated resolution
  - Preserve all observable behavior and return values
  - _Requirements: 1.3, 3.7, 3.8, 7.4_

- [ ] 9.3 Update BackendService to delegate to RequestTransformer
  - Replace `_apply_model_aliases` implementation with delegation to `request_transformer.apply_model_aliases`
  - Replace `_apply_reasoning_config` implementation with delegation to `request_transformer.apply_reasoning_config`
  - Replace `_apply_uri_parameters` implementation with delegation to `request_transformer.apply_uri_parameters`
  - Keep methods as thin wrappers preserving exact signatures
  - Update `call_completion` method to use delegated transformation
  - Preserve transformation order and behavior
  - _Requirements: 1.4, 3.7, 3.8, 8.3_

- [ ] 9.4 Update BackendService to delegate to StreamProcessor
  - Replace `_stream_as_sse_bytes` static method with instance method delegating to `stream_processor.stream_as_sse_bytes`
  - Replace `_resolve_stream_session_id` implementation with delegation to `stream_processor.resolve_stream_session_id`
  - Replace `_is_valid_completion_token` implementation with delegation to `stream_processor.is_valid_completion_token`
  - Keep methods as thin wrappers preserving exact signatures
  - Update streaming response handling in `call_completion` to use delegated processing
  - Preserve SSE encoding format and session ID resolution behavior
  - _Requirements: 1.6, 3.7, 3.8, 9.5_

- [ ] 9.5 Update BackendService to delegate to FailureStrategyExecutor
  - Replace `_apply_failure_strategy` implementation with delegation to `failure_strategy_executor.apply_failure_strategy`
  - Keep method as thin wrapper preserving exact signature
  - Update failure handling in `call_completion` to use delegated execution
  - Preserve failure decision logic and return values
  - _Requirements: 1.7, 3.7, 3.8, 11.3_

- [ ] 9.6 Update BackendService to delegate to FailoverPlanGenerator and ComplexFailoverExecutor
  - Replace `_get_failover_plan` implementation with delegation to `failover_plan_generator.get_failover_plan`
  - Replace `_filter_unhealthy_backends` implementation with delegation to `failover_plan_generator.filter_unhealthy_backends`
  - Replace `_execute_complex_failover` implementation with delegation to `complex_failover_executor.execute_complex_failover`
  - Replace `_attempt_failover_plan` implementation with delegation to `complex_failover_executor.attempt_failover_plan`
  - Keep methods as thin wrappers preserving exact signatures
  - Update failover handling in `call_completion` to use delegated services
  - Preserve failover behavior and error handling
  - _Requirements: 1.2, 3.7, 3.8, 6.5_

- [ ] 9.7 Ensure BackendService delegates to existing services properly
  - Verify `_get_or_create_backend` delegates to BackendLifecycleManager (already exists, ensure full delegation)
  - Verify `_normalize_provider_exception` delegates to ExceptionNormalizer (already exists, ensure full delegation)
  - Verify `_wrap_stream_for_usage` delegates to UsageTrackingWrapper (already exists, ensure full delegation)
  - Remove any remaining inline logic from these methods
  - Ensure all helper methods are thin delegating wrappers
  - _Requirements: 1.1, 1.5, 3.7, 5.5, 5.6, 10.3_

- [ ] 9.8 Update BackendService factory function in DI container
  - Update `_backend_service_factory` in `src/core/di/services.py` to resolve all new service dependencies
  - Resolve IBackendModelResolver, IRequestTransformer, IStreamProcessor, IFailureStrategyExecutor, IFailoverPlanGenerator, IComplexFailoverExecutor
  - Pass all dependencies to BackendService constructor
  - Ensure factory resolves dependencies in correct order
  - Verify registration happens after all new services are registered
  - _Requirements: 2.2, 2.7, 9.1_

- [ ] 9.9 Verify BackendService is reduced to orchestration only
  - Review BackendService implementation to ensure it contains only orchestration logic
  - Verify no business logic remains in BackendService methods
  - Confirm BackendService is <500 lines of code
  - Ensure all public API methods (call_completion, chat_completions, validate_backend_and_model, get_backend, get_active_backends) work correctly
  - Verify all wrapper methods delegate properly
  - _Requirements: 1.8, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 12.1, 12.2, 12.5_

## Phase 5: Test Implementation

- [ ] 10. Create unit tests for new services
- [ ] 10.1 Create unit tests for BackendModelResolver
  - Create `tests/unit/core/services/test_backend_model_resolver.py`
  - Test `resolve_backend_and_model` with mocked dependencies
  - Test session resolution, planning phase application, model alias resolution, backend routing, URI parameter parsing, static route override
  - Test `synchronize_request_with_target` with various request formats
  - Test edge cases: None session, missing extra_body, backend override scenarios
  - Verify behavior matches current BackendService implementation
  - Use TDD: write tests first, then verify implementation
  - _Requirements: 4.3, 7.5_

- [ ] 10.2 Create unit tests for RequestTransformer
  - Create `tests/unit/core/services/test_request_transformer.py`
  - Test `apply_model_aliases` delegation to ModelAliasResolver
  - Test `apply_reasoning_config` delegation to ReasoningConfigApplicator
  - Test `apply_uri_parameters` delegation to URIParameterApplicator
  - Test `transform_request` coordinates transformations in correct order
  - Verify transformation order preservation: aliases → reasoning → URI params
  - Test error handling and edge cases
  - _Requirements: 4.3, 8.5_

- [ ] 10.3 Create unit tests for StreamProcessor
  - Create `tests/unit/core/services/test_stream_processor.py`
  - Test `stream_as_sse_bytes` delegation to StreamFormattingService
  - Test `resolve_stream_session_id` with various input combinations
  - Test session ID resolution fallback logic: context → request → extra_body → request_id → uuid
  - Test `is_valid_completion_token` delegation to StreamFormattingService
  - Verify SSE encoding format matches current implementation
  - Test edge cases: None values, missing attributes
  - _Requirements: 4.3, 9.6_

- [ ] 10.4 Create unit tests for FailureStrategyExecutor
  - Create `tests/unit/core/services/test_failure_strategy_executor.py`
  - Test `apply_failure_strategy` with mocked IFailureHandlingStrategy
  - Test failure decision logic: elapsed_time calculation, available_backends lookup, strategy decision
  - Test None failure_strategy case returns SURFACE_ERROR
  - Test return value format: (FailureDecision, wait_seconds, next_backend)
  - Verify decision logic matches current implementation
  - Test error handling and edge cases
  - _Requirements: 4.3, 11.5_

- [ ] 10.5 Create unit tests for FailoverPlanGenerator
  - Create `tests/unit/core/services/test_failover_plan_generator.py`
  - Test `get_failover_plan` with mocked IFailoverCoordinator and IFailoverStrategy
  - Test failover strategy flag checking and fallback logic
  - Test `filter_unhealthy_backends` with circuit breaker enabled/disabled
  - Test health filtering: permanently disabled backends, unhealthy endpoints, session-scoped backends
  - Test fallback to original plan when all backends filtered
  - Verify plan generation matches current implementation
  - _Requirements: 4.3, 6.5_

- [ ] 10.6 Create unit tests for ComplexFailoverExecutor
  - Create `tests/unit/core/services/test_complex_failover_executor.py`
  - Test `execute_complex_failover` with mocked dependencies
  - Test `attempt_failover_plan` with various plan scenarios
  - Test recursive call to BackendService with allow_failover=False
  - Test error handling: BackendError wrapping, last_error preservation
  - Test failover attempt iteration and success/failure scenarios
  - Verify failover behavior matches current implementation
  - Mock IBackendService for recursive calls to prevent actual backend calls
  - _Requirements: 4.3, 6.5_

- [ ] 11. Create characterization tests
- [ ] 11.1 Create characterization tests for BackendService behavior preservation
  - Create `tests/unit/core/services/test_backend_service_characterization.py`
  - Test exact behavior preservation: compare old and new implementation outputs
  - Test request processing flow end-to-end with mocked backends
  - Test failover flow end-to-end
  - Test error handling scenarios
  - Test streaming response handling
  - Verify all observable invariants are preserved
  - Use property-based testing where applicable
  - _Requirements: 4.5, 4.6_

- [ ] 12. Verify existing tests pass
- [ ] 12.1 Run all existing BackendService unit tests
  - Execute `./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_service*.py -v`
  - Verify all tests pass without modification
  - Fix any test failures by ensuring wrapper methods preserve exact behavior
  - Document any test adjustments needed (should be minimal)
  - _Requirements: 4.1, 4.4_

- [ ] 12.2 Run BackendService integration tests
  - Execute integration tests that use BackendService
  - Verify DI wiring works correctly
  - Verify end-to-end request flows work
  - Fix any integration issues
  - _Requirements: 4.2, 4.4_

- [ ] 12.3 Run BackendService property tests
  - Execute `./.venv/Scripts/python.exe -m pytest tests/property/core/test_backend_service_api_preservation.py -v`
  - Verify API stability property tests pass
  - Verify no API contract violations
  - _Requirements: 3.1, 4.4_

## Phase 6: Integration and Verification

- [ ] 13. Verify complete refactoring
- [ ] 13.1 Verify all requirements are met
  - Review requirements.md and verify each acceptance criterion is satisfied
  - Verify BackendService is reduced to <500 lines
  - Verify all services have single responsibility
  - Verify all services are independently testable
  - Verify consistent naming conventions
  - Verify clear separation between orchestration and implementation
  - Verify comprehensive docstrings for all public methods
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [ ] 13.2 Run full test suite
  - Execute `./.venv/Scripts/python.exe -m pytest -m "not slow" -v`
  - Verify zero test failures
  - Fix any remaining test failures
  - Verify test coverage for new services
  - _Requirements: 4.4_

- [ ] 13.3 Run linting and type checks
  - Execute `./.venv/Scripts/python.exe -m ruff check --fix .`
  - Execute `./.venv/Scripts/python.exe -m black .`
  - Execute `./.venv/Scripts/python.exe -m mypy src/`
  - Fix any linting or type errors
  - Verify code quality standards are met
  - _Requirements: 12.6_

- [ ] 13.4 Verify DI registration completeness
  - Verify all new services are registered in DI container
  - Verify all interfaces are bound correctly
  - Verify service dependencies resolve correctly
  - Verify no circular dependencies (except ComplexFailoverExecutor → BackendService handled via late binding)
  - Test service resolution via IServiceProvider
  - _Requirements: 2.2, 2.7_

- [ ] 13.5 Verify backward compatibility
  - Verify IBackendService interface unchanged
  - Verify all public methods have unchanged signatures
  - Verify all wrapper methods preserve exact behavior
  - Verify existing callers work without modification
  - Test with actual BackendProcessor integration
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [ ] 13.6 Performance verification
  - Verify no measurable latency overhead (< 1ms per request)
  - Verify streaming first-byte timing unchanged
  - Verify request throughput maintained
  - Run basic performance smoke tests
  - Document any performance observations
  - _Requirements: NFR 1_

- [ ] 13.7 Final code review and cleanup
  - Review all new service implementations for code quality
  - Remove any debugging code or temporary comments
  - Ensure all docstrings are comprehensive
  - Verify error handling follows project patterns
  - Verify async/await usage is correct
  - Verify no blocking I/O operations
  - _Requirements: 12.6_
