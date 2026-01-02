# Exception Hygiene Linter

This linter enforces proper exception handling standards that were established during the exception hygiene orchestration session.

## What it detects

1. **EXH001**: Missing `exc_info=True` in `logger.error()`/`logger.warning()` calls within exception handlers
2. **EXH002**: Overly broad exception handlers (`except Exception:`)
3. **EXH003**: Silent exception handlers (`except: pass`)
4. **EXH004**: Incorrect `exc_info` usage (`exc_info=e` instead of `exc_info=True`)

## What it allows

- `logger.exception()` calls (which implicitly include `exc_info=True`)
- Cleanup methods (`__exit__`, `__del__`, `close()`, `shutdown()`, etc.)
- Exception handlers that re-raise
- Circuit breaker and fail-open patterns (when documented with comments)

## How to suppress findings

Use inline comments to suppress specific findings:

```python
try:
    risky_operation()
# exception-hygiene: ignore=EXH001
except ValueError:
    logger.error("Failed")  # Intentionally no exc_info for this case
```

Or suppress all checks:

```python
try:
    risky_operation()
# exception-hygiene: ignore=ALL
except Exception:
    pass  # Circuit breaker - intentionally silent
```

## Current status

The linter is now active and has identified several areas for improvement in the codebase. These findings can be addressed incrementally through additional exception hygiene orchestration sessions.
