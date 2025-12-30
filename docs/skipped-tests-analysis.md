# Comprehensive Analysis of Skipped Tests

This document provides a comprehensive analysis of all skipped tests in the test suite, categorizing them by skip reason and identifying which tests should be unskipped.

## Summary

- **Total skipped tests analyzed**: ~100+ tests across multiple files
- **Tests that should be removed (obsolete)**: ~70+ tests (see `docs/obsolete-tests-to-remove.md`)
- **Tests that should be unskipped**: ~1 test (after evaluation)
- **Tests that should stay skipped**: ~80+ tests (legitimate reasons)

---

## ⚠️ IMPORTANT: Obsolete Tests to Remove

**See `docs/obsolete-tests-to-remove.md` for comprehensive list.**

Many skipped tests are **obsolete** because they test functionality that has been:
1. Moved to a different architectural layer (with comprehensive replacement tests)
2. Removed and replaced by automatic mechanisms
3. Superseded by newer, more comprehensive tests

**Quick Summary**:
- ✅ **Path Fixup Tests** (8 tests) - **DELETE** - Replacement tests exist
- ✅ **Connector-Level Graceful Degradation** (~50+ tests) - **DELETE** - Replacement tests exist for Resilience Layer
- ✅ **Session Pruning Tests** (4 tests) - **DELETE** - Replaced by automatic TTL cleanup
- ✅ **Backend Routing Tests** (9 tests) - **DELETE** - Replacement tests exist

**Total**: ~70+ obsolete tests should be **deleted**, not unskipped.

---

## Tests That Should Be Unskipped

**Note**: Most skipped tests are actually **obsolete** and should be **removed** (see `docs/obsolete-tests-to-remove.md`). Only the following test needs evaluation:

### 1. Meta Test Suite Protection Test
**File**: `tests/test_meta_test_suite_protection.py`

**Status**: ⚠️ **Should be investigated** - Test is skipped "by default" but may be useful for CI/CD.

**Test**:
- `test_test_suite_protection` - Checks that test suite count hasn't decreased

**Action**: Evaluate if this test should run in CI/CD. If yes, unskip it. If it's only for manual checks, keep skipped but document the reason. If not useful, remove it.

---

## Tests That Should Stay Skipped (Legitimate Reasons)

### 1. Connector-Level Graceful Degradation Tests (OBSOLETE - Should Be Removed)
**Files**:
- `tests/behavior/test_graceful_degradation_behavior.py` (entire module)
- `tests/behavior/test_disable_gemini_oauth_fallback_behavior.py` (entire module)
- `tests/unit/connectors/test_gemini_oauth_plan.py` (entire module)
- `tests/unit/connectors/test_gemini_oauth_fix.py` (entire module)
- `tests/unit/connectors/test_tool_call_request_patterns.py` (entire module)

**Reason**: Connector-level graceful degradation has been replaced by the Resilience Layer (fully implemented). Comprehensive replacement tests exist.

**Status**: ✅ **OBSOLETE - DELETE** - Functionality moved to `ResilienceCoordinator` and `RateLimitStateManager`. Comprehensive replacement tests exist in `tests/unit/core/services/resilience/`.

**Total**: ~50+ tests

**See**: `docs/obsolete-tests-to-remove.md` for details.

---

### 2. Antigravity OAuth Tests (Test Infrastructure Issues)
**File**: `tests/unit/connectors/test_antigravity_oauth.py`

**Reason**: "Antigravity OAuth tests hang/crash - needs investigation"

**Status**: ⚠️ **Legitimately skipped** - Tests have infrastructure issues. Should be fixed before unskipping.

**Total**: Entire module (~30+ tests)

**Action**: Investigate and fix test infrastructure issues, then unskip.

---

### 3. Integration Tests Requiring Credentials
**Files**:
- `tests/integration/test_qwen_oauth_tool_calling.py` - Multiple `skipif` decorators checking for Qwen OAuth credentials
- `tests/integration/test_qwen_oauth_error_scenarios.py` - Requires Qwen OAuth credentials
- `tests/integration/test_qwen_oauth_integration.py` - Requires Qwen OAuth credentials
- `tests/integration/test_gemini_end_to_end.py` - Requires Gemini API key
- `tests/integration/test_gemini_cli_acp_integration.py` - Requires gemini-cli tool and authentication
- `tests/integration/test_zai_real_integration.py` - Requires ZAI_API_KEY and RUN_REAL_ZAI=1
- `tests/integration/connectors/test_gemini_request_counter_integration.py` - Requires valid credentials

**Reason**: These tests require real API credentials or external tools that may not be available in all test environments.

**Status**: ✅ **Correctly skipped** - Should only run when credentials are available.

**Total**: ~20+ tests

---

### 4. Platform-Specific Tests
**Files**:
- `tests/unit/test_cli_di.py` - Windows-specific tests (2 tests)
- `tests/unit/core/services/test_path_validation_service.py` - Windows/Unix-specific tests (9 tests)
- `tests/unit/core/services/test_sandboxing_performance.py` - Unix-specific test (1 test)
- `tests/unit/core/cli_support/test_privilege_checker.py` - Platform-specific privilege checks (7 tests)
- `tests/property/core/cli_support/test_privilege_checker_property.py` - Platform-specific tests (4 tests)

**Reason**: These tests verify platform-specific behavior (Windows vs Unix).

**Status**: ✅ **Correctly skipped** - Should only run on the appropriate platform.

**Total**: ~23 tests

---

### 5. Optional Dependency Tests
**Files**:
- `tests/codex/integration/test_droid_codex_compatibility.py` - Requires `cbor2` package

**Reason**: Tests require optional dependencies that may not be installed.

**Status**: ✅ **Correctly skipped** - Should only run when dependency is available.

**Total**: 1 test

---

### 6. Gemini Connector Availability Tests
**File**: `tests/regression/test_gemini_background_task_leak_regression.py`

**Reason**: Tests check if Gemini connector classes are available (may be conditionally imported).

**Status**: ✅ **Correctly skipped** - Should only run when connector is available.

**Total**: 1 test class

---

### 7. Architectural Validation Tests
**File**: `tests/unit/test_architectural_validation_properties.py`

**Reason**: Multiple `skipif` decorators for various conditions (imports, features).

**Status**: ✅ **Correctly skipped** - Conditional tests based on available features.

**Total**: 3 tests

---

### 8. Gemini Client Integration (Commented Out)
**File**: `tests/integration/test_gemini_client_integration.py`

**Reason**: Test file has commented-out `pytestmark = pytest.mark.skip` with reason "Google Gemini API client not available or incompatible". The comment says "De-networked: tests now use mocked Gemini client instead of real network calls".

**Status**: ✅ **Correctly skipped** - Tests have been replaced with mocked versions.

**Total**: Entire file (commented skip)

---

## Tests Requiring Further Investigation

### 1. Backend Routing Service Implementation Status
**Question**: Is multi-instance backend routing fully implemented?

**Evidence**:
- `BackendRoutingService` exists and handles routing
- `BackendService` uses `BackendRoutingService`
- Tests are skipped because they depend on `_refresh_instance_registry()` which may not exist

**Action**: 
1. Check if `BackendService` or `BackendRoutingService` has instance registry refresh functionality
2. Verify if multi-instance routing is fully functional
3. If yes, refactor tests to use the new architecture

---

### 2. Path Fixup Orchestrator Tests
**Question**: Are there tests for the orchestrator's fixup pipeline?

**Evidence**:
- Tests are skipped because "Path fixup is now handled by orchestrator's fixup pipeline"
- Need to verify if orchestrator has its own tests

**Action**:
1. Search for orchestrator fixup pipeline tests
2. If missing, refactor skipped tests to test orchestrator
3. If tests exist, delete skipped tests

---

### 3. Session State Pruning
**Question**: Is session state pruning handled elsewhere?

**Evidence**:
- Tests skipped because `_prune_session_state` was removed
- Need to verify if pruning happens automatically or in another service

**Action**:
1. Check if session state has TTL/automatic cleanup
2. Check if another service handles pruning
3. If functionality exists elsewhere, refactor tests
4. If intentionally removed, delete tests

---

## Recommendations

### Immediate Actions

1. **Investigate Backend Routing**: Check if `BackendRoutingService` fully implements multi-instance routing. If yes, refactor `test_backend_routing.py` to test it directly.

2. **Fix Antigravity Tests**: Investigate why Antigravity OAuth tests hang/crash and fix the infrastructure issues.

3. **Evaluate Path Fixup Tests**: Check if orchestrator's fixup pipeline has tests. If not, refactor the skipped tests to test the orchestrator.

4. **Review Session Pruning**: Verify if session pruning functionality exists elsewhere or was intentionally removed.

### Short-Term Actions

1. **Refactor Architecture-Change Tests**: For tests skipped due to architectural changes (Resilience Layer, etc.), create new tests that verify the new architecture if coverage is missing.

2. **Document Skip Reasons**: Ensure all skipped tests have clear, actionable skip reasons that explain:
   - Why the test is skipped
   - What needs to happen to unskip it
   - Where the functionality is now tested (if applicable)

### Long-Term Actions

1. **Test Coverage Audit**: After unskipping tests, verify that all critical functionality has test coverage in the new architecture.

2. **CI/CD Integration**: Evaluate which skipped tests should run in CI/CD (e.g., platform-specific tests on appropriate runners, credential-requiring tests in secure environments).

---

## Statistics

### Tests That Should Be Unskipped (After Investigation/Refactoring)
- Path fixup tests: ~8 tests
- Session pruning tests: ~4 tests  
- Meta test suite protection: 1 test
- Backend routing tests: ~9 tests (if feature is implemented)
- **Total: ~22 tests**

### Tests That Should Stay Skipped
- Connector-level graceful degradation: ~50+ tests
- Antigravity OAuth (infrastructure issues): ~30+ tests
- Integration tests requiring credentials: ~20+ tests
- Platform-specific tests: ~23 tests
- Optional dependencies: ~5 tests
- **Total: ~128+ tests**

### Tests Requiring Investigation
- Backend routing implementation status
- Path fixup orchestrator test coverage
- Session pruning functionality location
- **Total: ~3 areas to investigate**

---

## Related Documents

- `docs/obsolete-tests-to-remove.md` - **NEW** - Comprehensive list of obsolete tests that should be deleted
- `docs/tests-to-unskip-list.md` - Tests that should be unskipped (after investigation)
- `docs/tests-to-unskip.md` - Documents tests skipped during Phase 4 refactoring
- `.kiro/specs/archive/resilience-layer-architecture/` - Resilience Layer architecture documentation
