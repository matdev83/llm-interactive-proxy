# Exception Hygiene Fix Task - Iteration 35/72

You are tasked with fixing 3 exception hygiene issues detected by our linter.

## Your Responsibilities

1. **Read the affected files** to understand the context
2. **Fix each issue** according to the rules below
3. **Run tests** to ensure no regressions
4. **Commit the changes** with a descriptive message

## Issues to Fix


### File: `src\core\services\async_usage_write_queue.py`

- **Line 236** - EXH001: Missing exc_info=True in logger call within exception handler

### File: `src\core\services\backend_lifecycle_manager.py`

- **Line 404** - EXH001: Missing exc_info=True in logger call within exception handler

### File: `src\core\services\backend_non_streaming_response_handler.py`

- **Line 228** - EXH001: Missing exc_info=True in logger call within exception handler


## Fix Guidelines

### EXH001: Missing exc_info=True

**Problem:** Logger calls in exception handlers are missing `exc_info=True`, losing stack trace information.

**Fix:**
```python
# BEFORE
except SomeException as e:
    logger.error("Operation failed")
    
# AFTER
except SomeException as e:
    logger.error("Operation failed", exc_info=True)
```

**Note:** If the logger call is `logger.exception()`, it already includes exc_info implicitly - no change needed.

### EXH003: Silent Exception Handler

**Problem:** Exception handlers with just `pass` and no logging make debugging impossible.

**Fix:** Add appropriate logging:
```python
# BEFORE
except SomeException:
    pass
    
# AFTER (if this is truly expected and should be silent)
except SomeException:
    # Intentionally ignoring error - this is expected in cleanup
    pass
    
# AFTER (if this might indicate a problem)
except SomeException as e:
    logger.warning("Unexpected error during cleanup", exc_info=True)
```

**Judgment required:** You need to determine if the silent handler is:
1. Intentional (cleanup, optional operations) - add comment explaining why
2. Potentially masking bugs - add logging

### EXH004: Incorrect exc_info Usage

**Problem:** Using `exc_info=variable` instead of `exc_info=True`

**Fix:**
```python
# BEFORE
except SomeException as e:
    logger.error("Failed", exc_info=e)  # WRONG - doesn't work
    
# AFTER
except SomeException as e:
    logger.error("Failed", exc_info=True)  # CORRECT
```

## Testing Requirements

**Before making changes:**
1. Identify which test files cover the code you're modifying
2. Run those tests to establish baseline: `pytest <test_file> -v`

**After making changes:**
1. Run the same tests again to verify no regressions
2. If tests fail, fix the issue or revert your changes
3. Only commit if all tests pass

**Test discovery:**
- For `src/connectors/foo.py`, look for `tests/unit/test_foo.py` or `tests/integration/test_foo*.py`
- For `src/core/services/bar.py`, look for `tests/unit/test_bar.py`
- If you can't find specific tests, run: `pytest tests/unit -v -k "keyword"` where keyword relates to the module

## Commit Requirements

**Create exactly ONE commit** for this batch of fixes.

**Commit message format:**
```
fix(exception-hygiene): Fix {count} issues in {file_count} files (iteration {iteration})

- EXH001: {count_exh001} missing exc_info=True
- EXH003: {count_exh003} silent handlers  
- EXH004: {count_exh004} incorrect exc_info usage

Affected files:
- {filename1}
- {filename2}
...
```

**Example:**
```
fix(exception-hygiene): Fix 3 issues in 2 files (iteration 1)

- EXH001: 2 missing exc_info=True
- EXH003: 1 silent handler

Affected files:
- src/connectors/openai.py
- src/core/services/rate_limiter.py
```

## Important Constraints

1. **NO cosmetic changes** - only fix the specific issues listed
2. **NO refactoring** - keep the surrounding code as-is
3. **NO formatting changes** - ruff/black will handle that in CI
4. **Test must pass** - if tests fail, you must fix or revert
5. **One commit only** - don't create multiple commits

## Success Criteria

- ✅ All {len(batch)} issues are fixed correctly
- ✅ All relevant tests pass
- ✅ Exactly one commit is created
- ✅ Commit message follows the format above

## Workflow Summary

1. Read all affected files to understand context
2. Make fixes following the guidelines above
3. Run relevant tests (before and after)
4. Commit with proper message format
5. Report back with commit hash and test results

Good luck! Focus on correctness and minimal changes.
