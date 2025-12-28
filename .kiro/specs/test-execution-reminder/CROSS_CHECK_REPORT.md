# Test Execution Reminder Spec - Cross-Check Verification Report

**Verification Date**: 2025-12-28
**Spec Location**: `.kiro/specs/archive/test-execution-reminder/`
**Verification Method**: Codebase inspection (no tests run)
**Status**: **INCOMPLETE - Critical discrepancies found**

---

## Executive Summary

The Test Execution Reminder spec claims to be 100% complete, with all 37 tasks implemented and Phase 2 improvements fully delivered. However, **cross-checking against the actual codebase reveals significant gaps**:

1. **Phase 1 (Core Features)**: ✅ Mostly complete and working
2. **Phase 2 (finish_reason Detection)**: ❌ **NOT IMPLEMENTED** - despite being marked complete
3. **Documentation**: ⚠️ Contains false claims about completed features
4. **CHANGELOG**: ❌ Missing required entry
5. **Validation Tests**: ❌ Claimed to exist but cannot be found

**Estimated Actual Completion**: ~70-75% (Phase 1 complete, Phase 2 incomplete)

---

## What EXISTS and WORKING ✅

### Core Implementation Files (7 files)

All core components from Phase 1 are implemented and present:

| File | Status | Notes |
|------|--------|-------|
| `src/services/test_execution_reminder/test_execution_reminder_handler.py` | ✅ EXISTS | Main handler with state management, TTL cleanup |
| `src/services/test_execution_reminder/completion_signal_detector.py` | ✅ EXISTS | Tool name detection only (no finish_reason) |
| `src/services/test_execution_reminder/file_modification_detector.py` | ✅ EXISTS | Detects file modification tools |
| `src/services/test_execution_reminder/test_runner_registry.py` | ✅ EXISTS | 14+ languages supported |
| `src/services/test_execution_reminder/session_state.py` | ✅ EXISTS | Per-session dirty/clean tracking |
| `src/services/test_execution_reminder/eos_subscriber.py` | ✅ EXISTS | EoS event listener (bonus feature) |
| `src/services/test_execution_reminder/__init__.py` | ✅ EXISTS | Proper package exports |

### Test Coverage

| Test Type | Spec Claim | Actual Found | Status |
|-----------|-------------|--------------|--------|
| Unit tests | 6 files | 7 files found | ✅ **EXCEEDS** |
| Property tests | 15 files | 17 files found | ✅ **EXCEEDS** |
| Integration tests | 1 file | 1 file found | ✅ **MATCHES** |
| Validation tests | 1 file (21 tests) | **0 files** | ❌ **MISSING** |

**Note**: Test count claims (184 unit, 14 integration, 15 property) cannot be verified without running tests.

### Configuration Support

All configuration methods are implemented:

| Configuration Method | Status | Evidence |
|-------------------|--------|----------|
| CLI arguments | ✅ EXISTS | Comments in handler suggest CLI flag usage |
| Environment variables | ✅ EXISTS | `TEST_EXECUTION_REMINDER_ENABLED`, `TEST_EXECUTION_REMINDER_MESSAGE` in config |
| Config file fields | ✅ EXISTS | `test_execution_reminder_enabled`, `test_execution_reminder_message` in session.py |
| sample.env | ✅ EXISTS | Lines 74, 78 in `config/sample.env` |

### Handler Registration

| Aspect | Status | Evidence |
|---------|--------|----------|
| Registered in DI container | ✅ YES | `src/core/di/provider_lifecycle.py:341, 351` |
| Correct priority | ✅ YES | Priority 90 (below pytest full-suite, above generic handlers) |
| Integration with reactor | ✅ YES | Implements `IToolCallHandler` interface |

### Documentation

| Document | Status | Notes |
|----------|--------|-------|
| User guide | ✅ EXISTS | `docs/user_guide/test-execution-reminder.md` is comprehensive |
| README | ✅ EXISTS | Feature mentioned in line 54 of README.md |
| CHANGELOG | ❌ **MISSING** | No entry for Test Execution Reminder feature |

---

## What's MISSING or INCOMPLETE ❌

### Critical Gap: Phase 2 finish_reason Detection

The spec documents extensively describe Phase 2 improvements, claiming they are 100% complete. However, **actual implementation does NOT include finish_reason detection**.

#### Claimed in Spec

From `tasks.md` lines 430-436:
```markdown
- [x] 28.3 Add FINISH_REASONS set (stop, tool_calls, length, end_turn)
- [x] 28.4 Update is_completion_signal() signature to accept finish_reason and metadata
- [x] 28.5 Add _is_finish_reason() method for finish_reason validation
```

From `tasks.md` lines 440-445:
```markdown
- [x] 29.1 Add _extract_finish_reason() method to extract from full_response
- [x] 29.2 Add _extract_metadata() method to extract metadata dict
```

From `COMPLETION_SUMMARY.md` lines 231-240:
```markdown
Added (Reliable):
- `attempt_completion` to `COMPLETION_TOOLS` (Cline, Roo-Code)
- `FINISH_REASONS` set (stop, tool_calls, length, end_turn)
- `finish_reason` parameter in `is_completion_signal()`
- `metadata` parameter in `is_completion_signal()`
- `_is_finish_reason()` method for validation
```

#### Actual Implementation Reality

**CompletionSignalDetector (59 lines total)**:
```python
# src/services/test_execution_reminder/completion_signal_detector.py

class CompletionSignalDetector:
    """Detects completion signals in tool calls.

    This detector identifies when agents signal task completion through:
    1. Explicit completion tool calls (e.g., attempt_completion from Cline/Roo-Code)
    """

    COMPLETION_TOOLS = {
        "attempt_completion",  # Cline, Roo-Code (most common)
        "finish",  # OpenHands (formerly OpenDevin)
        "finish_task",
        "task_complete",
        "mark_complete",
        "complete",
        "done",
    }

    @classmethod
    def is_completion_tool(cls, tool_name: str) -> bool:
        # Only checks tool names, NOT finish_reason
        if not tool_name:
            return False

        normalized_input = tool_name.lower().replace("_", "").replace("-", "")

        for pattern in cls.COMPLETION_TOOLS:
            normalized_pattern = pattern.replace("_", "").replace("-", "")
            if normalized_input == normalized_pattern:
                return True

        return False
```

**What's MISSING**:
- ❌ `FINISH_REASONS` set (should contain: "stop", "tool_calls", "length", "end_turn")
- ❌ `finish_reason` parameter in any method
- ❌ `metadata` parameter in any method
- ❌ `_is_finish_reason()` method
- ❌ `is_completion_signal()` method (doesn't exist - only `is_completion_tool()`)
- ❌ `_extract_finish_reason()` method in handler
- ❌ `_extract_metadata()` method in handler

### Handler Comments Indicate Abandonment

The handler contains comments suggesting finish_reason detection was **planned but abandoned**:

```python
# src/services/test_execution_reminder/test_execution_reminder_handler.py

# Line 153:
# Note: finish_reason-based completion detection is now handled by EoS events

# Line 220:
# Note: finish_reason-based completion detection is now handled by EoS events
```

However, `eos_subscriber.py` does NOT implement finish_reason detection either. It only logs warnings when sessions end in dirty state.

### Nonexistent Validation Tests

**FINAL_VALIDATION_REPORT.md claims** (lines 91-103):
```
tests/validation/test_final_validation.py:
  TestAttemptCompletionDetection:        5 passed
  TestFinishReasonDetection:             8 passed
  TestNoFalsePositives:                  4 passed
  TestReliableDetectionBenefits:         4 passed

Total:                                  21 passed
```

**Actual Reality**:
```bash
$ ls -la tests/validation/
total 16
drwxr-xr-x 1 Mateusz 197121 0 Dec 26 00:00 .
drwxr-xr-x 1 Mateusz 197121 0 Dec 28 14:51 ..
```

❌ `tests/validation/` directory is **completely empty**
❌ No `test_final_validation.py` file exists
❌ No `TestFinishReasonDetection` class exists anywhere
❌ No `TestAttemptCompletionDetection` class exists anywhere

### Missing CHANGELOG Entry

**Requirement from tasks.md** (line 404):
```markdown
- Update CHANGELOG.md with feature description
```

**Actual CHANGELOG.md content**:
```markdown
# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Changed
- Improved type safety in ToolArgumentsParser with proper TelemetryRecorder typing
- Added race condition prevention with sequential execution for mypy validation tests
...
```

❌ **No entry for Test Execution Reminder feature**
❌ No mention of the feature in version history

### Test Count Discrepancies

**COMPLETION_SUMMARY.md claims** (lines 34-38):
```
Unit Tests:           184 passed
Integration Tests:     14 passed
Property Tests:        15 passed (1500+ total iterations)
Total Tests:          213 passed
```

**Actual Test Files Found**:
- Unit test files: 7 (spec claimed 6) - **EXCEEDS**
- Property test files: 17 (spec claimed 15) - **EXCEEDS**
- Integration test files: 1 (spec claimed 14) - **DEFICIT**

⚠️ Test counts cannot be verified without running tests
⚠️ Integration test count (14 vs 1 actual) appears inflated

---

## Detailed Component Analysis

### 1. CompletionSignalDetector

| Feature | Spec Claim | Actual Implementation | Status |
|---------|-------------|---------------------|---------|
| Tool name detection | ✅ Implemented | ✅ `is_completion_tool()` exists and works | ✅ PASS |
| attempt_completion | ✅ Added | ✅ In COMPLETION_TOOLS | ✅ PASS |
| finish (OpenHands) | ✅ Added | ✅ In COMPLETION_TOOLS | ✅ PASS |
| FINISH_REASONS set | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| _is_finish_reason() | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| finish_reason param | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| metadata param | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| is_completion_signal() | ✅ Updated | ❌ **DOESN'T EXIST** | ❌ **FAIL** |

**Critical Finding**: The entire finish_reason detection mechanism described in Phase 2 is missing. Only tool name detection is implemented.

### 2. TestExecutionReminderHandler

| Feature | Spec Claim | Actual Implementation | Status |
|---------|-------------|---------------------|---------|
| Core handler logic | ✅ Implemented | ✅ Fully implemented | ✅ PASS |
| Session state mgmt | ✅ Implemented | ✅ Works correctly | ✅ PASS |
| TTL cleanup | ✅ Implemented | ✅ `_prune_session_state()` exists | ✅ PASS |
| _extract_finish_reason() | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| _extract_metadata() | ✅ Added | ❌ **NOT FOUND** | ❌ **FAIL** |
| can_handle() uses finish_reason | ✅ Updated | ⚠️ Comment says "handled by EoS events" | ⚠️ **UNCLEAR** |
| handle() uses finish_reason | ✅ Updated | ⚠️ Comment say "handled by EoS events" | ⚠️ **UNCLEAR** |

**Critical Finding**: The handler was NOT actually updated to use finish_reason detection. Comments suggest it was moved to EoS events, which don't implement it.

### 3. Test Files

| Test Type | Spec Claim | Actual Found | Status |
|-----------|-------------|--------------|--------|
| Unit tests | 6 files | 7 files | ✅ MORE |
| Property tests | 15 files | 17 files | ✅ MORE |
| Integration tests | 1 file | 1 file | ✅ MATCH |
| Validation tests | 1 file (21 tests) | **0 files** | ❌ **MISSING** |

**Note**: While more test files exist than claimed, the validation tests specifically mentioned in FINAL_VALIDATION_REPORT.md do not exist.

---

## Evidence of Incomplete Phase 2

### Code Evidence

1. **CompletionSignalDetector.is_completion_signal() does not exist**
   - Spec claims method was updated to accept `finish_reason` and `metadata`
   - Actual code only has `is_completion_tool(tool_name: str) -> bool`
   - No mention of finish_reason anywhere in the file

2. **No FINISH_REASONS set exists**
   - Spec: "FINISH_REASONS set (stop, tool_calls, length, end_turn)"
   - Actual: Not defined anywhere in the codebase
   - Searched: `src/services/test_execution_reminder/` - 0 matches

3. **Handler comments indicate abandonment**
   ```python
   # Line 153:
   # Note: finish_reason-based completion detection is now handled by EoS events

   # Line 220:
   # Note: finish_reason-based completion detection is now handled by EoS events
   ```
   - EoS subscriber does NOT implement finish_reason detection
   - Only logs warnings for dirty sessions at end-of-session

4. **No validation tests exist**
   - Spec: "tests/validation/test_final_validation.py" with 21 tests
   - Actual: Empty `tests/validation/` directory
   - No test files match claimed test class names

### Documentation Evidence

1. **FINAL_STATUS.md claims 100% completion**:
   ```markdown
   ## All Tasks Complete

   All 37 main tasks and their subtasks have been completed:
   - ✅ Tasks 1-27: Core implementation
   - ✅ Tasks 28-37: Phase 2 improvements
   ```

2. **FINAL_VALIDATION_REPORT.md claims successful validation**:
   ```markdown
   ## Validation Results

   ### Task 37.1: Verify attempt_completion Detection Works ✓

   ### Task 37.2: Verify finish_reason Detection Works ✓

   ### Task 37.3: Verify No False Positives from Removed Pattern Matching ✓
   ```

3. **COMPLETION_SUMMARY.md claims implementation**:
   ```markdown
   ### Added (Reliable):
   - `attempt_completion` to `COMPLETION_TOOLS` (Cline, Roo-Code)
   - `FINISH_REASONS` set (stop, tool_calls, length, end_turn)
   - `finish_reason` parameter in `is_completion_signal()`
   ```

All these claims contradict the actual code.

---

## Root Cause Analysis

Based on evidence, it appears:

1. **Phase 1 was fully implemented**:
   - ✅ Core functionality works (file modification tracking, test execution detection, tool name completion detection, steering injection)
   - ✅ All 27 Phase 1 tasks appear to be complete
   - ✅ Handler is registered and functioning

2. **Phase 2 was planned but abandoned mid-implementation**:
   - ❌ Tasks 28-37 were marked [x] complete in tasks.md
   - ❌ Completion reports were written claiming 100% completion
   - ❌ But actual code never implemented finish_reason detection
   - ❌ Comments in handler suggest it was "moved to EoS events" which don't implement it

3. **Documentation does not match implementation**:
   - Multiple spec documents (COMPLETION_SUMMARY.md, FINAL_STATUS.md, FINAL_VALIDATION_REPORT.md) were created
   - These documents claim Phase 2 is complete
   - But actual codebase doesn't reflect these claims
   - This suggests documentation was created based on planned work, not actual implementation

4. **Test counts may be inflated**:
   - Claimed: 184 unit tests, 14 integration tests
   - Found: 7 unit test files, 1 integration test file
   - Cannot verify without running tests
   - Integration test count discrepancy (14 vs 1) is suspicious

---

## Tasks Not Actually Performed

Based on codebase inspection, the following tasks marked as complete are **NOT COMPLETE**:

### Phase 2 Tasks (Incomplete)

| Task | Subtask | Claimed Status | Actual Status | Issue |
|------|----------|----------------|----------------|-------|
| **27. Final verification** | Update CHANGELOG.md | ✅ Complete | ❌ **NOT DONE** | No CHANGELOG entry exists |
| **28. Update CompletionSignalDetector** | 28.3 Add FINISH_REASONS | ✅ Complete | ❌ **NOT DONE** | No FINISH_REASONS in code |
| | 28.4 Update signature for finish_reason | ✅ Complete | ❌ **NOT DONE** | is_completion_signal() doesn't exist |
| | 28.5 Add _is_finish_reason() | ✅ Complete | ❌ **NOT DONE** | Method doesn't exist |
| **29. Update Handler** | 29.1 Add _extract_finish_reason() | ✅ Complete | ❌ **NOT DONE** | Method doesn't exist |
| | 29.2 Add _extract_metadata() | ✅ Complete | ❌ **NOT DONE** | Method doesn't exist |
| | 29.3 Update can_handle() | ✅ Complete | ⚠️ **UNCLEAR** | Comment says EoS handles it |
| | 29.4 Update handle() | ✅ Complete | ⚠️ **UNCLEAR** | Comment says EoS handles it |
| | 29.5 Update logging | ✅ Complete | ⚠️ **UNCLEAR** | No finish_reason in logs |
| **30. Update unit tests** | 30.3 Add finish_reason tests | ✅ Complete | ❌ **NOT DONE** | No finish_reason tests |
| | 30.4 Add metadata tests | ✅ Complete | ❌ **NOT DONE** | No metadata tests |
| | 30.5 Add OpenAI format tests | ✅ Complete | ❌ **NOT DONE** | No such tests |
| | 30.6 Combined detection tests | ✅ Complete | ❌ **NOT DONE** | No such tests |
| | 30.7 Update edge cases | ✅ Complete | ❌ **NOT DONE** | Edge cases not updated |
| **31. Update property tests** | 31.4 Add finish_reason property tests | ✅ Complete | ❌ **NOT DONE** | No such property tests |
| **32. Update integration tests** | 32.3 Add finish_reason tests | ✅ Complete | ❌ **NOT DONE** | No finish_reason in tests |
| | 32.4 Verify end-to-end | ✅ Complete | ⚠️ **PARTIAL** | Only tool name tested |
| **33. Update handler tests** | 33.2 Update for finish_reason | ✅ Complete | ❌ **N/A** | finish_reason not implemented |
| | 33.3 Add _extract_finish_reason() tests | ✅ Complete | ❌ **NOT DONE** | Method doesn't exist |
| | 33.4 Add _extract_metadata() tests | ✅ Complete | ❌ **NOT DONE** | Method doesn't exist |
| | 33.5 Update completion detection tests | ✅ Complete | ⚠️ **PARTIAL** | Only tool name tested |
| **36. Verify tests** | All subtasks | ✅ Complete | ⚠️ **UNKNOWN** | Cannot verify without running tests |
| **37. Final validation** | All subtasks | ✅ Complete | ❌ **FALSE** | Validation tests don't exist |

### Summary of Incomplete Work

- **13 out of 10 Phase 2 subtasks** are not actually complete
- **finish_reason detection entirely missing** (core Phase 2 feature)
- **CHANGELOG not updated** (Phase 1 requirement)
- **Validation tests claimed but don't exist**

---

## Recommendations

The spec should **NOT** be marked as finished. One of two approaches is needed:

### Option A: Complete Phase 2 Implementation

To finish the spec as originally designed:

1. **Implement finish_reason detection in CompletionSignalDetector**:
   ```python
   FINISH_REASONS = {"stop", "tool_calls", "length", "end_turn"}

   @classmethod
   def is_completion_signal(cls, tool_name: str, finish_reason: str | None = None) -> bool:
       # Check tool name OR finish_reason
       return cls.is_completion_tool(tool_name) or cls._is_finish_reason(finish_reason)

   @classmethod
   def _is_finish_reason(cls, finish_reason: str | None) -> bool:
       if not finish_reason:
           return False
       return finish_reason.lower() in cls.FINISH_REASONS
   ```

2. **Implement extraction methods in Handler**:
   ```python
   def _extract_finish_reason(self, full_response: dict) -> str | None:
       # Extract finish_reason from OpenAI/Anthropic format
       pass

   def _extract_metadata(self, full_response: dict) -> dict:
       # Extract metadata from response
       pass
   ```

3. **Update handler to use finish_reason**:
   ```python
   async def can_handle(self, context: ToolCallContext) -> bool:
       finish_reason = self._extract_finish_reason(context.full_response)
       metadata = self._extract_metadata(context.full_response)
       is_completion = CompletionSignalDetector.is_completion_signal(
           context.tool_name,
           finish_reason=finish_reason,
           metadata=metadata,
       )
       # ... rest of logic
   ```

4. **Write validation tests**:
   - Create `tests/validation/test_final_validation.py`
   - Add TestAttemptCompletionDetection
   - Add TestFinishReasonDetection
   - Add TestNoFalsePositives
   - Add TestReliableDetectionBenefits

5. **Update CHANGELOG**:
   - Add entry for Test Execution Reminder feature
   - Document Phase 2 improvements

### Option B: Update Spec to Match Reality

If finish_reason detection is not needed:

1. **Remove Phase 2 tasks** from tasks.md (tasks 28-37)
2. **Mark spec as ~75% complete** (Phase 1 only)
3. **Update completion documents** to remove Phase 2 claims:
   - COMPLETION_SUMMARY.md - remove Phase 2 section
   - FINAL_STATUS.md - update to Phase 1 complete only
   - Delete FINAL_VALIDATION_REPORT.md (validation never happened)
4. **Add CHANGELOG entry** for what was actually delivered
5. **Clarify completion documentation** to state:
   - Only tool name completion detection is implemented
   - finish_reason detection was not implemented
   - EoS subscriber only logs warnings (doesn't inject steering)

---

## Conclusion

The Test Execution Reminder spec is **NOT finished** as claimed:

1. ✅ **Phase 1 is complete**: Core functionality works (file modification tracking, test execution detection, tool name completion detection, steering injection, configuration support, handler registration)

2. ❌ **Phase 2 is incomplete**: finish_reason detection - the core improvement described in Phase 2 - is completely missing from the codebase

3. ❌ **Documentation is inaccurate**: Multiple completion documents claim 100% completion of features that don't exist

4. ❌ **CHANGELOG not updated**: Required documentation task was not completed

5. ❌ **Validation tests don't exist**: Tests claimed in FINAL_VALIDATION_REPORT.md cannot be found

**Estimated actual completion**: 70-75% (Phase 1 complete, Phase 2 incomplete)

**Action required**: The spec status must be updated to "incomplete" and uncompleted tasks marked as unfinished before resuming implementation work.

---

## Appendix: File Locations

### Spec Files
- `.kiro/specs/archive/test-execution-reminder/spec.json`
- `.kiro/specs/archive/test-execution-reminder/requirements.md`
- `.kiro/specs/archive/test-execution-reminder/design.md`
- `.kiro/specs/archive/test-execution-reminder/tasks.md`
- `.kiro/specs/archive/test-execution-reminder/COMPLETION_SUMMARY.md`
- `.kiro/specs/archive/test-execution-reminder/FINAL_STATUS.md`
- `.kiro/specs/archive/test-execution-reminder/FINAL_VALIDATION_REPORT.md`
- `.kiro/specs/archive/test-execution-reminder/PHASE2_IMPROVEMENTS.md`

### Implementation Files
- `src/services/test_execution_reminder/__init__.py`
- `src/services/test_execution_reminder/test_execution_reminder_handler.py`
- `src/services/test_execution_reminder/completion_signal_detector.py`
- `src/services/test_execution_reminder/file_modification_detector.py`
- `src/services/test_execution_reminder/test_runner_registry.py`
- `src/services/test_execution_reminder/session_state.py`
- `src/services/test_execution_reminder/eos_subscriber.py`

### Test Files
- `tests/unit/services/test_execution_reminder/test_completion_signal_detector.py`
- `tests/unit/services/test_execution_reminder/test_file_modification_detector.py`
- `tests/unit/services/test_execution_reminder/test_test_execution_reminder_handler.py`
- `tests/unit/services/test_execution_reminder/test_test_runner_registry.py`
- `tests/unit/services/test_execution_reminder/test_session_state.py`
- `tests/unit/services/test_execution_reminder/test_logging.py`
- `tests/unit/services/test_execution_reminder/test_reminder_eos_subscriber.py`
- `tests/property/test_test_execution_reminder_config_properties.py`
- `tests/property/test_file_modification_detection_properties.py`
- `tests/property/test_all_language_test_runner_detection_properties.py`
- `tests/property/test_python_test_runner_detection_properties.py`
- `tests/property/test_javascript_test_runner_detection_properties.py`
- `tests/property/test_test_runner_pattern_matching_properties.py`
- `tests/property/test_completion_signal_detection_properties.py`
- `tests/property/test_steering_injection_on_dirty_completion_properties.py`
- `tests/property/test_no_steering_on_clean_completion_properties.py`
- `tests/property/test_session_isolation_properties.py`
- `tests/property/test_ttl_cleanup_properties.py`
- `tests/property/test_disabled_feature_properties.py`
- `tests/property/test_error_handling_properties.py`
- `tests/property/test_multiple_test_runs_properties.py`
- `tests/property/test_state_transition_cycle_properties.py`
- `tests/property/test_state_transition_properties.py`
- `tests/property/test_clean_state_preservation_properties.py`
- `tests/property/test_pattern_priority_properties.py`
- `tests/integration/test_test_execution_reminder_integration.py`

### Documentation Files
- `docs/user_guide/test-execution-reminder.md` ✅ EXISTS
- `README.md` ✅ EXISTS (feature mentioned)
- `CHANGELOG.md` ❌ **MISSING** (no entry)
- `config/sample.env` ✅ EXISTS (env vars documented)
