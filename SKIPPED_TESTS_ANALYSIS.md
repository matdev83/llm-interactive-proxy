# Skipped Tests Analysis Report

## Summary

**Total skipped tests found:** 126
- **Suspicious (should be unskipped):** 4
- **Legitimate:** 71  
- **Unclear (need manual review):** 51

## Tests That Should Be UNSKIPPED

These tests are skipped for non-legitimate reasons and should be unskipped:

### 1. `tests/test_meta_test_suite_protection.py::test_test_suite_protection`
- **Reason:** "Skipped by default"
- **Analysis:** This is a meta test designed to protect against test suite regression. The comment in the file explicitly states: "Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR." This test should NOT be skipped.
- **Action:** Remove `@pytest.mark.skip(reason="Skipped by default")` decorator

### 2. `tests/integration/test_zai_coding_plan.py::test_zai_coding_plan_backend_integration`
- **Reason:** "This test is failing due to a mocking issue and is not related to the current task."
- **Analysis:** This is a clear case of hiding a failing test rather than fixing it. The test should be fixed, not skipped.
- **Action:** Fix the mocking issue and unskip the test

### 3. `tests/unit/core/services/test_backend_lifecycle_manager.py::test_get_or_create_equivalence`
- **Reason:** "Skipped after Phase 4 - BackendService is now a thin façade. BackendLifecycleManager is tested directly in other test classes."
- **Analysis:** While the reason mentions that functionality is tested elsewhere, equivalence tests can still be valuable for regression detection. If the functionality truly doesn't exist anymore, the tests should be removed, not skipped.
- **Action:** Either unskip and update the test, or remove it entirely if the functionality no longer exists

### 4. `tests/unit/core/services/test_backend_lifecycle_manager.py::test_is_per_session_cache_key_equivalence`
- **Reason:** "Skipped after Phase 4 - BackendService is now a thin façade. BackendLifecycleManager is tested directly in other test classes."
- **Analysis:** Same as above - if functionality exists, test it; if not, remove the test.
- **Action:** Either unskip and update the test, or remove it entirely if the functionality no longer exists

## Module-Level Skips That Need Review

These entire test modules are skipped. Each contains multiple tests:

### 5. `tests/unit/core/services/test_backend_routing.py` (11 tests)
- **Reason:** "Multi-instance backend routing feature not yet implemented"
- **Analysis:** **CRITICAL FINDING:** The `BackendRoutingService` class DOES exist in `src/core/services/backend_routing_service.py` and is actively used throughout the codebase. The tests were skipped because they test `BackendService` directly, but the routing functionality has been moved to `BackendRoutingService`. This is a clear case of hiding test failures rather than refactoring tests.
- **Action:** **UNSKIP ALL TESTS** in this file and refactor them to test `BackendRoutingService` instead of `BackendService`. The routing feature exists and should be tested.

### 6. `tests/unit/core/services/test_backend_routing.py` - Individual test skips (10 additional tests)
- **Reason:** "Needs refactoring after Phase 4 - BackendService is now a thin facade"
- **Analysis:** These tests are individually skipped WITHIN an already-skipped module. This is redundant, but the individual skip reasons suggest the tests need refactoring.
- **Action:** If the module-level skip is removed, these tests will need refactoring to work with the new architecture.

## Tests That Are Legitimately Skipped

These tests are correctly skipped for legitimate reasons:

### OS/Platform Dependent
- Windows-specific tests (correctly skipped on non-Windows)
- Unix-specific tests (correctly skipped on Windows)
- Symlink tests (correctly skipped when symlinks not supported)
- IPv6 tests (correctly skipped when IPv6 not available)
- Privilege check tests (correctly skipped on platforms without privilege checks)

### Requires External Resources
- Tests requiring API keys/credentials (OpenAI, Anthropic, Gemini, etc.)
- Tests requiring external tools (cbor2, gemini-cli, vulture)
- Tests requiring specific capture files or wire captures
- Tests requiring authentication

### Runtime/Environment Dependent
- Tests checking for Python runtime features (async generator frames)
- Tests requiring specific Python versions or packages

### Feature Not Yet Implemented (Conditional)
- Tests checking for existence of modules/files before running
- Tests for features that are conditionally available

## Recommendations

### Priority 1: Critical - Unskip Immediately
1. **Test #1:** `tests/test_meta_test_suite_protection.py::test_test_suite_protection` - Meta test protection (explicitly forbidden to skip)
2. **Test #5:** `tests/unit/core/services/test_backend_routing.py` - ALL 11 tests - Feature exists, tests need refactoring

### Priority 2: High - Fix and Unskip
3. **Test #2:** `tests/integration/test_zai_coding_plan.py::test_zai_coding_plan_backend_integration` - Fix mocking issue
4. **Tests #3-4:** `tests/unit/core/services/test_backend_lifecycle_manager.py` - Either update tests or remove if functionality doesn't exist

### Priority 3: Review Needed
5. **Review unclear tests:** The 51 "unclear" tests need manual review to determine if they're legitimate or should be unskipped

## Next Steps

1. Run the analysis script: `./.venv/Scripts/python.exe analyze_skipped_tests.py`
2. Review each suspicious test manually
3. Fix or remove tests rather than skipping them
4. Update this document as tests are unskipped
