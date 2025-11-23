# Streaming Regression Fix Summary

## Issue Description
The proxy was experiencing streaming regression with the following symptoms:
- Very slow processing of requests  
- Client receiving responses only after a very long delay (buffering issue)
- Initial stack traces showing `NameError: name 'response' is not defined` (resolved by cache clear)

## Root Cause Analysis

### Issue 1: Stale Bytecode Cache (RESOLVED)
The initial `NameError: name 'response' is not defined` was caused by stale Python bytecode cache.

1. The error message `NameError: name 'response' is not defined` at line 466 in `response_processor_service.py` is misleading
2. Line 466 contains `cancel_callback=None,` which doesn't reference any `response` variable
3. All tests pass successfully
4. The code compiles without syntax errors
5. Recent commit 15809f2e added `cancel_callback` parameter to streaming methods

## Solution

### Immediate Fix
1. Clear all Python bytecode caches:
   ```powershell
   Get-ChildItem -Recurse -Filter "*.pyc" | Remove-Item -Force
   Get-ChildItem -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
   ```

2. Restart the proxy server to ensure it loads the latest code

### Verification
Run the streaming regression tests to confirm the fix:
```powershell
./.venv/Scripts/python.exe -m pytest tests/streaming_regression/test_streaming_core.py -v
```

All tests should pass (they do in the current codebase).

## Prevention

To prevent this issue in the future:
1. Always restart the proxy after pulling new code
2. Clear Python caches when experiencing unexplained errors
3. Use `git clean -fdx` to remove all untracked files including caches (be careful with this command)

## Technical Details

The recent changes in commit 15809f2e added `cancel_callback` parameter to:
- `IStreamNormalizer.process_stream()` interface
- `StreamNormalizer.process_stream()` implementation  
- `_PassthroughStreamNormalizer.process_stream()` implementation
- `ResponseProcessor.process_streaming_response()` call site

All implementations were updated correctly, but the running proxy instance was using old bytecode.

## Files Affected
- `src/core/services/response_processor_service.py` - Added cancel_callback parameter
- `src/core/services/streaming/stream_normalizer.py` - Updated to accept cancel_callback
- `src/core/interfaces/streaming_response_processor_interface.py` - Updated interface
- `src/connectors/streaming_utils.py` - Updated passthrough normalizer

## Status
✅ Code is correct
✅ Tests pass
⚠️ Proxy needs restart with clean cache


### Issue 2: Streaming Buffering (CURRENT ISSUE)

After clearing the cache, the proxy no longer crashes but responses are heavily buffered. Analysis shows:

**Timeline from logs:**
- Request sent to Gemini: 10:04:22
- Response received from Gemini: 10:04:38 (16 seconds)
- Client receives response: Much longer delay

**Potential Buffering Points:**

1. **Angel Service Buffering** (lines 738-755 in backend_request_manager_service.py)
   - Status: Angel is DISABLED (angel_model = None)
   - Not the cause

2. **Prefetch Buffering** (lines 554-562 in backend_request_manager_service.py)
   - Only buffers first chunk to check for empty stream
   - Should not cause significant delay

3. **Response Processor Streaming** (response_processor_service.py)
   - Processes stream through normalizer
   - May be buffering chunks

4. **FastAPI StreamingResponse** (response_adapters.py)
   - Has `await asyncio.sleep(0)` after each yield
   - Should prevent buffering

**Next Steps:**
1. Add debug logging to track when chunks are yielded at each stage
2. Check if middleware is buffering
3. Verify FastAPI is actually streaming incrementally
4. Check if the issue is specific to gemini-oauth-plan backend

## Diagnostic Commands

Check if chunks are being logged:
```powershell
Get-Content logs/proxy.log | Select-String -Pattern "yield|chunk" | Select-Object -Last 50
```

Check timing of stream processing:
```powershell
Get-Content logs/proxy.log | Select-String -Pattern "stream" | Select-Object -Last 30
```
