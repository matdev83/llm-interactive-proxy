# Tests That Should Be Unskipped

This document lists all tests that are currently skipped but should be unskipped because there's no legitimate reason for them to be skipped.

## Summary

**Total tests to unskip:** 15 tests across 3 files
**Fixed:** 2 issues (ZAI test unskipped, lifecycle manager tests removed)

## Detailed List

### 1. Meta Test Protection (CRITICAL)
**File:** `tests/test_meta_test_suite_protection.py`
- **Test:** `test_test_suite_protection`
- **Current skip reason:** "Skipped by default"
- **Why unskip:** This is a meta test designed to protect against test suite regression. The file explicitly states: "Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR."
- **Action:** Remove `@pytest.mark.skip(reason="Skipped by default")` decorator

### 2. Backend Routing Tests (CRITICAL - 11 tests)
**File:** `tests/unit/core/services/test_backend_routing.py`
- **Tests:** All 11 tests in this file:
  1. `test_round_robin_load_balancing`
  2. `test_model_centric_routing`
  3. `test_granular_rate_limiting_skip`
  4. `test_concurrency_limiting`
  5. `test_format1_specific_instance`
  6. `test_format2_generic_backend`
  7. `test_format3_model_only_simple`
  8. `test_format3_vendor_prefixed_model`
  9. `test_format2_with_vendor_prefixed_model`
  10. `test_format3_unknown_vendor_falls_to_default`
  11. `test_format2_model_with_colon_suffix`
- **Current skip reason:** Module-level skip: "Multi-instance backend routing feature not yet implemented"
- **Why unskip:** The `BackendRoutingService` class EXISTS in `src/core/services/backend_routing_service.py` and is actively used throughout the codebase. The tests were skipped because they need refactoring to test `BackendRoutingService` instead of `BackendService`, but the feature definitely exists.
- **Action:** 
  1. Remove `pytestmark = pytest.mark.skip(...)` at module level
  2. Refactor tests to use `BackendRoutingService` instead of `BackendService`
  3. Remove individual `@pytest.mark.skip` decorators from individual tests (they're redundant with module-level skip)

### 3. ZAI Integration Test ✅ FIXED
**File:** `tests/integration/test_zai_coding_plan.py`
- **Test:** `test_zai_coding_plan_backend_integration`
- **Previous skip reason:** "This test is failing due to a mocking issue and is not related to the current task."
- **Fix:** Removed incorrect `patch()` attempt and fixed mocking to use `respx` for HTTP calls only. The test now properly mocks both the models endpoint and the chat/completions endpoint.
- **Status:** ✅ Unskipped and passing

### 4. Backend Lifecycle Manager Equivalence Tests ✅ REMOVED
**File:** `tests/unit/core/services/test_backend_lifecycle_manager.py`
- **Tests:** (removed)
  1. ~~`test_get_or_create_equivalence`~~ (empty test, removed)
  2. ~~`test_is_per_session_cache_key_equivalence`~~ (empty test, removed)
- **Previous skip reason:** "Skipped after Phase 4 - BackendService is now a thin façade. BackendLifecycleManager is tested directly in other test classes."
- **Fix:** Removed empty test class entirely since the functionality is already thoroughly tested in other test classes in the same file.
- **Status:** ✅ Removed (24 tests remain, all passing)

## Implementation Steps

1. **Start with Priority 1 tests:**
   - Unskip meta test protection (test #1)
   - Unskip backend routing tests (test #2 - all 11 tests)

2. **Then fix Priority 2 tests:** ✅ COMPLETED
   - ✅ Fixed and unskipped ZAI integration test (test #3)
   - ✅ Removed empty lifecycle manager equivalence tests (test #4)

3. **After unskipping, run tests:**
   ```bash
   ./.venv/Scripts/python.exe -m pytest tests/test_meta_test_suite_protection.py -v
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_routing.py -v
   ./.venv/Scripts/python.exe -m pytest tests/integration/test_zai_coding_plan.py -v
   ./.venv/Scripts/python.exe -m pytest tests/unit/core/services/test_backend_lifecycle_manager.py -v
   ```

4. **Fix any failures** that occur after unskipping

5. **Remove this document** once all tests are unskipped and passing

## Notes

- The backend routing tests will require significant refactoring since they test `BackendService` but the functionality has moved to `BackendRoutingService`
- The meta test protection should NEVER be skipped - it's a critical safeguard
- Always fix tests rather than skipping them - skipping should only be for legitimate reasons (OS dependencies, missing external resources, etc.)
