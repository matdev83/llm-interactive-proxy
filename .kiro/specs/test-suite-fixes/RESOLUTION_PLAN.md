# Test Suite Fixes - Resolution Plan

## Summary

43 failing tests, 4 root causes, straightforward fixes.

## Root Causes

### 1. Missing Logging Imports (12 mypy errors)
- **Files**: `turn_counter_service.py`, `structured_wire_capture_service.py`
- **Fix**: Add `import logging` at top of each file
- **Impact**: Fixes all 12 mypy errors

### 2. Structlog Mock Method Name (1 test)
- **File**: `tests/unit/core/test_logging_utils.py`
- **Issue**: Mock uses `is_enabled_for` but structlog uses `isEnabledFor`
- **Fix**: Change mock method name to `isEnabledFor`
- **Impact**: Fixes 1 test

### 3. Assessment Service Integration (30+ tests)
- **Files**: Multiple test files in `tests/behavior/`, `tests/integration/`
- **Issues**: 
  - Async handling in turn counter tests
  - State isolation between sessions
  - Steering message injection timing
- **Fix**: Review and fix test setup/teardown, ensure proper async handling
- **Impact**: Fixes ~30 tests

### 4. Minor Quality Issues (2-3 tests)
- **Issues**:
  - Ruff linting errors in src
  - Unapproved markdown files in project root (todo.md)
  - Tool call reactor deduplication
- **Fix**: Run ruff --fix, remove todo.md, fix deduplication logic
- **Impact**: Fixes 2-3 tests

## Execution Order

1. **Quick wins first** (Tasks 1-2): Fix imports and mock - 5 minutes
2. **Assessment tests** (Task 3): Review and fix - 30-60 minutes
3. **Quality cleanup** (Task 4): Linting and cleanup - 10 minutes
4. **Verification** (Task 5): Run full suite - 5 minutes

## Expected Outcome

- Before: 43 failed, 5893 passed
- After: 0 failed, 5936 passed
- Time estimate: 1-2 hours total
