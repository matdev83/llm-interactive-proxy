# Root Cause Analysis: Streaming Error Bypass

## Problem Summary

Despite implementing fallback logic for replacement model failures, users were still seeing 401 errors stringified as SSE messages:

```
Error: 401 data: {"id": "chatcmpl-error-1772108993", ...}
data: [DONE]
```

Sessions were being interrupted instead of falling back to the original model.

## Root Cause

The fallback logic in `request_processor_service.py` was **only catching exceptions**, but for **streaming requests**, errors follow a different code path:

### Non-Streaming Requests
1. `BackendCompletionFlowService.call_completion()` catches errors
2. **Raises the exception** (line 1206)
3. Fallback logic in `request_processor_service.py` catches it ✅

### Streaming Requests  
1. `BackendCompletionFlowService.call_completion()` catches errors
2. **Returns `StreamingResponseEnvelope` with error embedded** (line 1202-1205)
3. Fallback logic in `request_processor_service.py` **never sees an exception** ❌
4. Error envelope flows all the way to the client with status_code=401

### The Critical Code Path

In `src/core/services/backend_completion_flow/service.py`:

```python
# Line 1201-1206
if stream:
    return await self._build_terminal_error_stream_envelope(
        error=normalized_exc,
        provider=current_backend,
    )
raise normalized_exc  # Only for non-streaming!
```

For streaming, `_build_terminal_error_stream_envelope()` creates a `StreamingResponseEnvelope` with:
- `status_code = 401` (or other error code)
- `content = async iterator that yields SSE-formatted error chunks`

This envelope is returned (not raised), bypassing the exception handler.

## The Fix

Modified `request_processor_service.py` to **detect error responses** in addition to catching exceptions:

```python
result = await self._backend_executor.execute(...)

# NEW: Check if result is an error response
if hasattr(result, "status_code") and result.status_code >= 400:
    # Convert error response to exception for fallback logic
    if result.status_code == 401:
        raise AuthenticationError("Backend returned 401 error")
    else:
        raise Exception(f"Backend returned error status: {result.status_code}")

return result
```

Now the fallback logic works for **both** streaming and non-streaming requests.

## Impact

- ✅ Streaming replacement model failures now trigger fallback to original model
- ✅ Sessions are no longer interrupted by OAuth rate limits on replacement models
- ✅ Error envelopes never reach clients when fallback is available
- ✅ Maintains B2BUA behavior (new backend attempt identity on fallback)

## Files Modified

1. `src/core/services/request_processor_service.py`
   - Added error response detection before returning result
   - Converts 4xx/5xx responses to exceptions to trigger existing fallback logic

## Related Issues

This fix addresses:
- Issue #1: OAuth token refresh errors interrupting sessions
- Issue #2: No graceful fallback for replacement model failures (streaming case)
- Issue #4: Stringified SSE errors reaching clients (prevented by fallback)
