# Tests That Should Be Unskipped

This document lists tests that were skipped during refactoring work and should now be unskipped since the implementations are back in place and functional.

## Summary

Tests were skipped during Phase 4 of the backend-service-god-object-refactoring. The implementations have been moved to new collaborators:
- `FailoverPlanner` - handles failover planning logic
- `StreamSessionIdResolver` - handles stream session ID resolution
- `BackendModelResolver` - handles backend/model resolution
- `BackendCompletionFlow` - orchestrates completion requests

**Note**: These tests need to be **refactored** to test the collaborators directly rather than testing internal methods on `BackendService`. The implementations exist and are functional, but the tests need updating to match the new architecture.

---

## Tests Requiring Refactoring (Should Be Unskipped After Refactoring)

### 1. Failover Planning Tests
**File**: `tests/unit/core/services/test_backend_service_failover.py`

All tests in this file are skipped with reason: "Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"

**Status**: ✅ Implementation exists (`src/core/services/failover_planner.py`)  
**Action**: Refactor tests to test `FailoverPlanner` directly instead of `BackendService._get_failover_plan()` and related private methods.

**Tests to unskip** (after refactoring):
- `TestFailoverStrategyPath` (1 test)
- `TestFailoverCoordinatorPath` (1 test)
- `TestHealthFiltering` (5 tests)
- `TestSessionScopedBackends` (1 test)
- `TestComplexFailoverExecution` (2 tests)
- `TestAttemptFailoverPlan` (5 tests)
- `TestApplyFailureStrategy` (2 tests)
- `TestEdgeCases` (2 tests)

**Total**: ~19 tests

---

### 2. Stream Session ID Resolution Tests
**File**: `tests/unit/core/services/test_stream_session_id_resolution.py`

All tests are skipped with reason: "Needs refactoring after Phase 4 - BackendService is now a thin facade"

**Status**: ✅ Implementation exists (`src/core/services/stream_session_id_resolver.py`)  
**Action**: Refactor tests to test `StreamSessionIdResolver.resolve_stream_session_id()` directly instead of `BackendService._resolve_stream_session_id()`.

**Tests to unskip** (after refactoring):
- `TestBackendServiceStreamSessionIdResolution` (5 tests)
- `TestBufferedWireCaptureStreamSessionIdResolution` (3 tests)
- `TestDivergenceDocumentation` (2 tests)
- `TestEdgeCases` (3 tests)
- `TestUnificationRequirements` (1 test)

**Total**: ~14 tests

**Note**: There's already a test file `test_stream_session_id_resolution.py` that may have some coverage, but these characterization tests document specific behavior that should be preserved.

---

### 3. Backend Routing Tests
**File**: `tests/unit/core/services/test_backend_routing.py`

**Status**: ⚠️ Entire module is skipped with `pytestmark = pytest.mark.skip(reason="Multi-instance backend routing feature not yet implemented")`

**Tests to unskip** (after feature implementation):
- `TestBackendRouting` (3 tests)
- `TestModelFormatRouting` (6 tests)

**Total**: ~9 tests

**Note**: These tests depend on `_refresh_instance_registry()` which is not yet implemented. This is a legitimate skip for a feature not yet implemented.

---

### 4. Model Name Rewrites Tests
**File**: `tests/unit/core/services/test_model_name_rewrites.py`

All tests are skipped with reason: "Needs refactoring after Phase 4 - BackendService is now a thin facade"

**Status**: ✅ Implementation exists (`src/core/services/model_alias_resolver.py` and `BackendModelResolver`)  
**Action**: Refactor tests to test `ModelAliasResolver` and `BackendModelResolver` directly instead of `BackendService._apply_model_aliases()` and `BackendService._resolve_backend_and_model()`.

**Tests to unskip** (after refactoring):
- `TestModelNameRewrites` (8 tests)
- `TestModelAliasesConfiguration` (7 tests)

**Total**: ~15 tests

---

### 5. Planning Phase Tests
**File**: `tests/unit/core/services/test_planning_phase.py`

All tests are skipped with reason: "Needs refactoring after Phase 4 - BackendService is now a thin facade"

**Status**: ✅ Implementation exists (`src/core/services/planning_phase_manager.py`)  
**Action**: Refactor tests to test `PlanningPhaseManager` directly instead of `BackendService` internal methods.

**Tests to unskip** (after refactoring):
- `TestPlanningPhaseConfiguration` (3 tests)
- `TestSessionStateWithPlanningPhase` (3 tests)
- `TestBackendServicePlanningPhase` (2 tests)
- `TestPlanningPhaseEndToEnd` (3 tests)

**Total**: ~11 tests

---

### 6. Streaming Rate Limit Retry Tests
**File**: `tests/unit/core/services/test_backend_service_streaming_rate_limit_retry.py`

**Status**: ✅ Implementation exists (`BackendCompletionFlow`)  
**Action**: Refactor test to test `BackendCompletionFlow` directly or through integration tests.

**Tests to unskip** (after refactoring):
- `test_streaming_wait_and_retry_emits_keepalives` (1 test)

**Total**: 1 test

---

### 7. Streaming Error Envelope Tests
**File**: `tests/unit/core/services/test_backend_service_streaming_error_envelope.py`

**Status**: ✅ Implementation exists (`BackendCompletionFlow`)  
**Action**: Refactor test to test `BackendCompletionFlow` directly or through integration tests.

**Tests to unskip** (after refactoring):
- `test_streaming_429_with_short_retry_after_emits_keepalive_and_retries` (1 test)

**Total**: 1 test

---

### 8. Auth Failure Tests
**File**: `tests/unit/core/services/test_backend_service_auth_failure.py`

All tests are skipped with reason: "Needs refactoring after Phase 4 - BackendService is now a thin facade"

**Status**: ✅ Implementation exists (`BackendCompletionFlow` handles auth failures)  
**Action**: Refactor tests to test `BackendCompletionFlow` directly or through integration tests.

**Tests to unskip** (after refactoring):
- `test_auth_failure_permanent_backend_disable` (1 test)
- `test_backend_error_401_permanent_disable` (1 test)
- `test_http_exception_401_permanent_disable` (1 test)
- `test_oauth_backend_not_permanently_disabled` (1 test)
- `test_disabled_backend_fails_fast_without_failover` (1 test)

**Total**: 5 tests

---

### 9. Keepalive Tests
**File**: `tests/unit/core/services/test_backend_service_keepalive.py`

**Status**: ✅ Implementation exists (`BackendCompletionFlow`)  
**Action**: Refactor test to test `BackendCompletionFlow` directly or through integration tests.

**Tests to unskip** (after refactoring):
- Entire module is skipped (1 test)

**Total**: 1 test

---

### 10. Rate Limit Cooldown Tests
**File**: `tests/unit/core/services/test_backend_service_rate_limit_cooldown.py`

**Status**: ✅ Implementation exists (`ResilienceCoordinator`)  
**Action**: Refactor test to test `ResilienceCoordinator` directly.

**Tests to unskip** (after refactoring):
- `test_call_completion_applies_cooldown_on_429` (1 test)

**Total**: 1 test

---

### 11. Backend Lifecycle Manager Tests
**File**: `tests/unit/core/services/test_backend_lifecycle_manager.py`

**Status**: ✅ Implementation exists (`BackendLifecycleManager`)  
**Action**: These tests are skipped because they test equivalence with old `BackendService` behavior. Since `BackendService` is now a thin facade, these equivalence tests are no longer meaningful. The `BackendLifecycleManager` is tested directly in other test classes.

**Tests**: 
- `test_get_or_create_equivalence` (1 test)
- `test_is_per_session_cache_key_equivalence` (1 test)

**Recommendation**: ⚠️ **Keep skipped** - These equivalence tests are no longer relevant since `BackendService` architecture changed. The functionality is tested directly in other test classes.

---

## Tests That Should Stay Skipped (Legitimate Reasons)

### Integration Tests Requiring Credentials
- `tests/integration/test_zai_coding_plan.py` - `test_zai_coding_plan_backend_integration` (failing due to mocking issue, not related to refactoring)
- `tests/integration/test_qwen_oauth_*.py` - Multiple tests requiring OAuth credentials
- `tests/integration/test_gemini_*.py` - Tests requiring Gemini API credentials
- `tests/integration/test_backend_real_e2e.py` - Tests requiring real backend credentials
- `tests/streaming_regression/*.py` - Tests requiring authentication
- `tests/live/*.py` - Live tests requiring credentials

### Tests Requiring Specific Files/Data
- `tests/simulation/test_gemini_antigravity_regression.py` - Requires specific capture files
- `tests/codex/integration/test_droid_codex_compatibility.py` - Requires CBOR capture files
- `tests/unit/core/ports/test_usage_chunk_cbor_replay.py` - Requires CBOR capture files

### Platform-Specific Tests
- `tests/unit/test_cli_di.py` - Windows-specific tests (correctly skipped on non-Windows)
- `tests/unit/core/cli_support/test_privilege_checker.py` - Platform-specific privilege checks
- `tests/unit/core/services/test_path_validation_service.py` - Platform-specific path validation
- `tests/unit/core/services/test_sandboxing_performance.py` - Unix-specific symlink tests

### Feature Not Yet Implemented
- `tests/unit/core/services/test_backend_routing.py` - Multi-instance backend routing feature not yet implemented

### External Dependencies
- `tests/conftest.py` - Tests skipped when `pytest_asyncio` or `pytest_httpx` not installed
- `tests/unit/core/services/test_structured_wire_capture.py` - Python runtime limitation
- `tests/unit/test_architectural_validation_properties.py` - Various conditional skips

### Completely Skipped Files (`.skip` extension)
- `tests/unit/core/test_request_processor_os_detection.py.skip` - OS detection moved to `SessionEnricher` (keep skipped, functionality tested elsewhere)
- `tests/unit/services/test_request_processor_truncated_outputs.py.skip` - **✅ Should be unskipped immediately** - Tests `RequestProcessor._expand_truncated_tool_outputs()` which exists and is functional
- `tests/unit/core/services/test_response_middleware.py.skip` - **✅ Should be unskipped immediately** - Tests middleware classes (`ContentFilterMiddleware`, `LoggingMiddleware`, `LoopDetectionMiddleware`) which exist and are functional

---

## Summary Statistics

### Tests That Should Be Unskipped (After Refactoring)
- Failover planning: ~19 tests
- Stream session ID resolution: ~14 tests
- Model name rewrites: ~15 tests
- Planning phase: ~11 tests
- Streaming rate limit retry: 1 test
- Streaming error envelope: 1 test
- Auth failure: 5 tests
- Keepalive: 1 test
- Rate limit cooldown: 1 test
- **Total: ~68 tests**

### Tests That Should Stay Skipped
- Integration tests requiring credentials: ~50+ tests
- Platform-specific tests: ~20+ tests
- Tests requiring specific files/data: ~10+ tests
- Feature not implemented: ~9 tests
- External dependencies: ~5 tests

### Completely Skipped Files to Review
- `test_request_processor_truncated_outputs.py.skip` - **✅ Should be unskipped immediately** (1 test)
- `test_response_middleware.py.skip` - **✅ Should be unskipped immediately** (~10 tests)

---

## Next Steps

1. **Immediate**: Unskip the two `.skip` files that test existing, functional code:
   - `tests/unit/services/test_request_processor_truncated_outputs.py.skip` → Rename to `.py` (tests `RequestProcessor._expand_truncated_tool_outputs()`)
   - `tests/unit/core/services/test_response_middleware.py.skip` → Rename to `.py` (tests `ContentFilterMiddleware`, `LoggingMiddleware`, `LoopDetectionMiddleware`)

2. **Short-term**: Refactor and unskip tests for collaborators that are fully implemented:
   - `FailoverPlanner` tests (refactor `test_backend_service_failover.py`)
   - `StreamSessionIdResolver` tests (refactor `test_stream_session_id_resolution.py`)
   - `ModelAliasResolver`/`BackendModelResolver` tests (refactor `test_model_name_rewrites.py`)

3. **Medium-term**: Refactor remaining tests:
   - Planning phase tests
   - Streaming tests
   - Auth failure tests

4. **Long-term**: Implement multi-instance backend routing feature and unskip those tests
