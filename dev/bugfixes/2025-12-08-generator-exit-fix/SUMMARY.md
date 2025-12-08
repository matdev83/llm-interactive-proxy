# Fix: GeneratorExit RuntimeError in Streaming Pipeline

## Problem

When clients disconnected early during streaming, the following errors occurred:

```
RuntimeError: aclose(): asynchronous generator is already running
RuntimeError: async generator ignored GeneratorExit
```

This happened in `src/core/ports/streaming_orchestrator.py` when:
1. Client breaks the streaming connection early
2. Python raises `GeneratorExit` to signal generator shutdown
3. The outer exception handler tried to process this, interfering with the `contextlib.aclosing()` cleanup

## Root Cause

The `process_stream` method used `contextlib.aclosing()` to ensure proper cleanup of async generators. However, when `GeneratorExit` was raised during the `yield` inside the context manager, the exception handling tried to work with a generator that was already in the process of closing, causing the "asynchronous generator is already running" error.

## Solution

Added nested exception handling to catch `GeneratorExit` early before it reaches the context manager cleanup:

```python
try:
    async with closing_context as managed_stream:
        # ... pipeline setup ...
        
        # Step 4: Yield formatted bytes
        try:
            async for chunk_bytes in assembled_stream:
                yield chunk_bytes
        except GeneratorExit:
            # Client disconnected - catch early to avoid interfering
            # with context manager cleanup
            if stream_id:
                logger.debug("Client disconnected during streaming", ...)
            raise

except GeneratorExit:
    # Re-raise to allow proper cleanup without error logging
    raise
except Exception as e:
    # Log actual errors
    logger.error("Error in streaming pipeline", ...)
    raise
```

## Changes Made

1. **File Modified**: `src/core/ports/streaming_orchestrator.py`
   - Added nested try-except to catch `GeneratorExit` before context manager cleanup
   - Added outer `GeneratorExit` handler to re-raise without error logging
   - Added type ignore comment for mypy compatibility with `contextlib.aclosing()`

## Testing

- Verified existing test passes: `tests/unit/test_streaming_orchestrator_aclose.py`
- All streaming tests pass: 98 tests in `tests/unit/streaming/` and `tests/property/test_streaming_*.py`
- No regressions detected

## Impact

- ✅ Eliminates RuntimeError when clients disconnect during streaming
- ✅ Proper cleanup still occurs via context manager
- ✅ Debug logging for client disconnects when stream_id is present
- ✅ No impact on normal streaming behavior
