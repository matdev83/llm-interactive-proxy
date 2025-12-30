# Tests That Should Be Unskipped

**⚠️ UPDATE**: Most tests listed below have **already been removed** as obsolete. See `docs/tests-to-unskip-investigation.md` for details.

## Summary

**Status**: Most tests have been **removed** (they were obsolete). Only **1 test** remains for evaluation:

1. ✅ **Path Fixup Tests** - **ALREADY REMOVED** (obsolete, replacement tests exist)
2. ✅ **Session Pruning Tests** - **ALREADY REMOVED** (obsolete, replacement tests exist)
3. ⚠️ **Meta Test Suite Protection** (1 test) - **NEEDS EVALUATION**
4. ✅ **Backend Routing Tests** - **ALREADY REMOVED** (obsolete, replacement tests exist)

**Total**: Only **1 test** needs evaluation

---

## Detailed List

### 1. ✅ Path Fixup Tests - ALREADY REMOVED

**Status**: ✅ **Already removed** - These tests were identified as obsolete and deleted.

**Original Location**: `tests/unit/core/services/test_tool_call_reactor_middleware.py`

**Replacement Tests**: 
- ✅ `tests/unit/core/services/tool_call_reactor/test_droid_path_fixup.py`
- ✅ `tests/unit/core/services/tool_call_reactor/test_arguments_fixup_pipeline.py`

**Conclusion**: ✅ **Correctly removed** - Functionality is comprehensively tested in replacement tests.

---

### 2. ✅ Session Pruning Tests - ALREADY REMOVED

**Status**: ✅ **Already removed** - These tests were identified as obsolete and deleted.

**Original Location**: `tests/unit/services/test_execution_reminder/test_test_execution_reminder_handler.py`

**Replacement Tests**:
- ✅ `tests/unit/services/test_execution_reminder/test_logging.py` - Tests automatic TTL cleanup

**Conclusion**: ✅ **Correctly removed** - Manual pruning was replaced by automatic TTL cleanup, which is tested.

---

### 3. ⚠️ Meta Test Suite Protection Test - NEEDS EVALUATION
**File**: `tests/test_meta_test_suite_protection.py`

**Skip Reason**: "Skipped by default"

**Test to Unskip**:
- `test_test_suite_protection` - Verifies test suite count hasn't decreased

**Current Status**: Skipped with reason "Skipped by default"

**Purpose**: 
- Verifies that test suite count hasn't decreased
- Protects against accidental test removal
- Tracks test suite growth over time

**Key Details**:
- Has comment: "Note to LLM agents: You are **NOT ALLOWED** to skip, disable, mute or alter this test unless EXPLICITLY INSTRUCTED BY HUMAN OPERATOR"
- Currently skipped "by default"
- NOT run in CI/CD (not found in `.github/workflows/`)
- Uses `EXPECTED_MIN_COUNT = 3706` as baseline
- Stores test count in `var/state/test_suite_state.json`

**Investigation Results**:
- Test can be run explicitly (not hard-coded to skip)
- "Skipped by default" suggests it's intentionally skipped to avoid false positives when tests are legitimately removed
- After removing ~70+ obsolete tests, `EXPECTED_MIN_COUNT` needs updating

**Recommendation**: 
- **Option A**: Keep skipped by default, run explicitly in CI/CD when test suite changes are intentional
- **Option B**: Unskip it and update `EXPECTED_MIN_COUNT` after legitimate test removals
- The comment suggests it should NOT be skipped, but the "by default" skip may be intentional

**Action Required**: 
1. ✅ Verify current test count
2. ⚠️ Update `EXPECTED_MIN_COUNT` if test is to be unskipped (currently 3706, needs update after removing ~70+ tests)
3. ⚠️ Decide: Should this test run in CI/CD or remain manual-only?

**Priority**: Low-Medium

---

### 4. ✅ Backend Routing Tests - ALREADY REMOVED

**Status**: ✅ **Already removed** - This test file was identified as obsolete and deleted.

**Original Location**: `tests/unit/core/services/test_backend_routing.py`

**Replacement Tests**:
- ✅ `tests/unit/core/services/test_backend_routing_service.py` - Comprehensive tests for `BackendRoutingService`

**Conclusion**: ✅ **Correctly removed** - Functionality is comprehensively tested in `test_backend_routing_service.py`.

---

## Tests That Should Stay Skipped (For Reference)

These tests are correctly skipped for legitimate reasons:

### Architectural Changes (Resilience Layer)
- `tests/behavior/test_graceful_degradation_behavior.py` - Entire module (~30+ tests)
- `tests/behavior/test_disable_gemini_oauth_fallback_behavior.py` - Entire module (~5 tests)
- `tests/unit/connectors/test_gemini_oauth_plan.py` - Entire module (~3 tests)
- `tests/unit/connectors/test_gemini_oauth_fix.py` - Entire module (~2 tests)
- `tests/unit/connectors/test_tool_call_request_patterns.py` - Entire module (~8 tests)

**Reason**: Connector-level graceful degradation replaced by Resilience Layer. Functionality exists but at a different architectural layer.

### Infrastructure Issues
- `tests/unit/connectors/test_antigravity_oauth.py` - Entire module (~30+ tests)

**Reason**: Tests hang/crash. Needs infrastructure fixes before unskipping.

### Credentials Required
- `tests/integration/test_qwen_oauth_*.py` - Multiple tests (~15+ tests)
- `tests/integration/test_gemini_end_to_end.py` - Requires API key
- `tests/integration/test_gemini_cli_acp_integration.py` - Requires gemini-cli tool
- `tests/integration/test_zai_real_integration.py` - Requires ZAI_API_KEY
- `tests/integration/connectors/test_gemini_request_counter_integration.py` - Requires credentials

**Reason**: Require real API credentials or external tools.

### Platform-Specific
- `tests/unit/test_cli_di.py` - Windows-specific (2 tests)
- `tests/unit/core/services/test_path_validation_service.py` - Windows/Unix-specific (9 tests)
- `tests/unit/core/services/test_sandboxing_performance.py` - Unix-specific (1 test)
- `tests/unit/core/cli_support/test_privilege_checker.py` - Platform-specific (7 tests)

**Reason**: Should only run on appropriate platform.

### Optional Dependencies
- `tests/codex/integration/test_droid_codex_compatibility.py` - Requires `cbor2` (1 test)

**Reason**: Should only run when dependency is available.

---

## Next Steps

1. **Immediate**: Investigate backend routing implementation status
2. **Short-term**: Check orchestrator fixup pipeline test coverage
3. **Short-term**: Verify session pruning functionality location
4. **Medium-term**: Refactor tests that need architectural updates
5. **Long-term**: Fix Antigravity OAuth test infrastructure issues

---

## Related Documents

- `docs/skipped-tests-analysis.md` - Comprehensive analysis of all skipped tests
- `docs/tests-to-unskip.md` - Tests skipped during Phase 4 refactoring
