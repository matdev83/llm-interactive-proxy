PRIORITIZED FAILURE CATEGORIES

1) Async/Await Issues | ImpactScore=0.85 | Confidence=high
Root cause (concise): Missing await for async method calls causing 'coroutine' object has no attribute errors

Affected dependent code (calling → called):
•  src/core/services/request_processor.py:ResponseProcessor.process_response:443
•  src/core/app/controllers/chat_controller.py:handle_chat_completion:71
•  src/core/services/request_processor.py:_create_non_streaming_response:448

Estimated tests fixed if this category is resolved: 45

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): test_basic_proxying, test_command_only_requests, test_chat_completion_regression, test_app tests, test_multiple_oneoff, test_phase1_integration, test_versioned_api, test_updated_hybrid_controller
•  Why they pass after fix: The async methods will properly return processed data instead of unawaited coroutines

Proposed fix strategy (architecturally aligned):
•  Add await keyword to async method calls in request_processor.py
•  Ensure proper async/await chain throughout the request handling pipeline
•  Maintains SOLID/DIP by preserving interface contracts

Risks/Mitigations:
•  Low risk - straightforward syntax fix
•  Mitigation: Test incrementally to ensure no cascading issues

2) Request Data Type Mismatch | ImpactScore=0.72 | Confidence=high
Root cause (concise): ChatCompletionRequest objects being passed where dict expected, missing .get() method

Affected dependent code (calling → called):
•  src/core/services/request_processor.py:process_request:212
•  src/core/integration/hybrid_controller.py:hybrid_chat_completions:87
•  src/core/app/controllers/init.py:compat_chat_completions:204

Estimated tests fixed if this category is resolved: 25

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): test_basic_request_proxying_streaming, test_loop_detection tests
•  Why they pass after fix: Request objects will be properly converted to dict format for processing

Proposed fix strategy (architecturally aligned):
•  Add adapter/converter to transform ChatCompletionRequest to dict when needed
•  Use model_dump() or dict() method on Pydantic models
•  Follows adapter pattern from SOLID principles

Risks/Mitigations:
•  Medium risk - needs careful type handling
•  Mitigation: Add type checks and conversion logic

3) Validation Errors | ImpactScore=0.58 | Confidence=med
Root cause (concise): Empty messages array validation and extra_body type mismatches

Affected dependent code (calling → called):
•  src/core/services/request_processor.py:ChatRequest:212
•  tests/unit/chat_completions_tests/test_command_only_requests.py:various:19+

Estimated tests fixed if this category is resolved: 15

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): test_command_only_request patterns
•  Why they pass after fix: Request validation will handle edge cases properly

Proposed fix strategy (architecturally aligned):
•  Update ChatRequest validation to handle empty messages for command-only requests
•  Fix extra_body field type expectations
•  Preserves domain model integrity

Risks/Mitigations:
•  Medium risk - changing validation could affect other flows
•  Mitigation: Ensure backward compatibility

4) Missing Fixtures | ImpactScore=0.42 | Confidence=high
Root cause (concise): Test fixture 'mock_openai' not found in test configuration

Affected dependent code (calling → called):
•  tests/unit/chat_completions_tests/test_interactive_commands.py:test_set_backend_nonfunctional:129

Estimated tests fixed if this category is resolved: 2

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): test_set_backend_nonfunctional
•  Why they pass after fix: Test will have required fixtures available

Proposed fix strategy (architecturally aligned):
•  Add missing fixture definition in conftest.py
•  Follow existing fixture patterns

Risks/Mitigations:
•  Low risk - test infrastructure only
•  Mitigation: Copy pattern from existing fixtures

5) Missing Methods/Attributes | ImpactScore=0.35 | Confidence=high
Root cause (concise): Various missing attributes like _extract_response_content, LogLevel

Affected dependent code (calling → called):
•  tests/unit/test_response_shape.py:test_extract_response_content:35
•  src/core/app/application_factory.py:_load_config:291

Estimated tests fixed if this category is resolved: 8

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): test_response_shape, test_config tests
•  Why they pass after fix: Required methods/attributes will be available

Proposed fix strategy (architecturally aligned):
•  Add missing methods as private helpers or refactor to use public interfaces
•  Import missing enums/constants

Risks/Mitigations:
•  Low risk for adding missing pieces
•  Mitigation: Follow existing patterns

6) Mock Teardown Issues | ImpactScore=0.28 | Confidence=med
Root cause (concise): httpx_mock assertions failing due to unused registered responses

Affected dependent code (calling → called):
•  tests/unit/chat_completions_tests/test_failover.py:teardown
•  tests/unit/chat_completions_tests/test_rate_limit_wait.py:teardown

Estimated tests fixed if this category is resolved: 5

Evidence/derivation:
•  Tests currently failing due to this category (IDs/patterns): ERROR at teardown patterns
•  Why they pass after fix: Mock responses will be properly consumed or cleaned up

Proposed fix strategy (architecturally aligned):
•  Add httpx_mock.non_mocked_hosts or allow_unused parameters
•  Ensure all mocked requests are actually called

Risks/Mitigations:
•  Low risk - test infrastructure only
•  Mitigation: Review each test's mock setup