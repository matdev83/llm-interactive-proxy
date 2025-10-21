# HTTP 502 Error Analysis Report - Mid-Session Interruption

## Problem Summary

**Issue**: Client receives HTTP 502 "Bad Gateway" error with no response body during mid-session, after several successful prompt/reply exchanges.

**Root Cause**: Gemini OAuth backend quota exhaustion (HTTP 429) occurring during streaming response generation, causing the proxy to terminate the connection abruptly without proper error handling.

## Detailed Analysis

### Timeline of Events (from logs)

1. **09:33:38 - 09:37:26**: Multiple successful streaming responses completed normally
   - Wire capture shows successful `stream_end` events with proper chunk counts
   - Examples: 14 chunks (6853 bytes), 20 chunks (9724 bytes)

2. **09:37:26**: New streaming request initiated
   - `stream_start` event logged in wire capture
   - Request begins processing normally

3. **09:37:40**: **CRITICAL FAILURE POINT**
   - **HTTP 429 "Resource Exhausted"** from Gemini API: 
     ```
     {'error': {'code': 429, 'message': 'Resource exhausted. Please try again later. Please refer to https://cloud.google.com/vertex-ai/generative-ai/docs/error-code-429 for more details.', 'status': 'RESOURCE_EXHAUSTED'}}
     ```
   - Backend marked as unusable: `Backend gemini-oauth-plan marked as unusable due to quota exceeded`
   - **BackendError exception raised in streaming generator**

4. **09:37:40+**: New request attempts continue but backend is now non-functional

### Technical Root Cause

The issue occurs in `src/connectors/gemini_oauth_base.py` in the `stream_generator()` method (lines 1701-1702):

```python
if response.status_code >= 400:
    self._handle_streaming_error(response)  # This raises BackendError
```

When a 429 quota exceeded error occurs **during streaming**:

1. The `_handle_streaming_error()` method detects the quota error
2. It calls `_mark_backend_unusable()` to disable the backend
3. It raises a `BackendError` with the quota exhausted message
4. **The streaming generator terminates abruptly**
5. The client connection is closed without a proper HTTP error response
6. Client receives **HTTP 502** because the upstream connection was severed

### Why It Happens Mid-Session

**Key Insight**: This is NOT a tool call handling issue - it's a **quota management issue** that manifests during streaming responses.

1. **Quota Accumulation**: Each request consumes quota from the Gemini API
2. **Session Success**: Initial requests succeed because quota is available
3. **Quota Depletion**: After several exchanges, the quota limit is reached
4. **Mid-Stream Failure**: The quota exhaustion occurs **during** a streaming response, not at the start
5. **Abrupt Termination**: The streaming generator raises an exception instead of gracefully handling the error

### Code Analysis - The Problem

In `gemini_oauth_base.py` line 1702, when `_handle_streaming_error()` is called:

```python
def _handle_streaming_error(self, response: requests.Response) -> None:
    # ... error detection logic ...
    if is_quota_error:
        self._mark_backend_unusable()
        raise BackendError(  # <-- THIS KILLS THE STREAM
            message=f"Gemini CLI OAuth quota exhausted: {error_detail}",
            code="quota_exceeded", 
            status_code=response.status_code,
        )
```

**The problem**: Raising `BackendError` in the middle of a streaming response causes the async generator to terminate, which closes the HTTP connection abruptly, resulting in a 502 error on the client side.

## Impact Assessment

### User Experience
- **Sudden disconnection** during active conversation
- **No error message** - just HTTP 502 with empty body
- **Session appears broken** - user doesn't know what happened
- **Requires manual intervention** to understand quota exhaustion

### System Behavior
- **Backend becomes permanently unusable** until manual restart
- **No graceful degradation** or failover to other backends
- **No user notification** about quota limits
- **Wire capture shows incomplete streams** (no proper `stream_end` events)

## Required Fixes

### 1. Graceful Streaming Error Handling (HIGH PRIORITY)

**Problem**: `BackendError` exceptions during streaming kill the connection abruptly.

**Solution**: Modify the streaming generator to yield proper error chunks instead of raising exceptions:

```python
# In stream_generator() around line 1702
if response.status_code >= 400:
    try:
        self._handle_streaming_error(response)
    except BackendError as e:
        # Instead of letting the exception kill the stream,
        # yield a proper error chunk that the client can handle
        error_chunk = self.translation_service.to_domain_stream_chunk(
            chunk={
                "error": {
                    "message": str(e.message),
                    "code": e.code,
                    "status_code": e.status_code
                }
            }, 
            source_format="error"
        )
        yield ProcessedResponse(content=error_chunk)
        return  # Graceful termination
```

### 2. Quota Monitoring and Proactive Management (MEDIUM PRIORITY)

**Problem**: No visibility into quota consumption until exhaustion.

**Solution**: 
- Implement quota usage tracking in `DailyRequestCounter`
- Add warning thresholds (e.g., 80%, 90% of quota)
- Proactive backend disabling before complete exhaustion

### 3. Better Error Communication (MEDIUM PRIORITY)

**Problem**: Client receives generic 502 with no context.

**Solution**:
- Ensure quota exhaustion errors are properly formatted as streaming chunks
- Include actionable error messages for users
- Add retry-after headers when appropriate

### 4. Backend Recovery Mechanism (LOW PRIORITY)

**Problem**: Backend remains unusable until manual restart.

**Solution**:
- Implement automatic quota reset detection
- Add manual backend re-enablement commands
- Consider failover to alternative backends

## Immediate Action Items

1. **Fix streaming error handling** to prevent abrupt connection termination
2. **Add proper error chunk generation** for quota exhaustion scenarios  
3. **Test the fix** with quota exhaustion simulation
4. **Update error handling documentation** for streaming scenarios

## Prevention Strategy

1. **Quota monitoring dashboard** to track usage patterns
2. **Rate limiting** to prevent rapid quota consumption
3. **User education** about quota limits and usage patterns
4. **Graceful degradation** when approaching quota limits

## Conclusion

The HTTP 502 error is caused by **improper exception handling during streaming responses** when quota exhaustion occurs. The fix requires modifying the streaming generator to handle quota errors gracefully by yielding error chunks instead of raising exceptions that terminate the connection abruptly.

This is **not a tool call issue** but rather a **streaming error handling and quota management issue** that happens to manifest during active conversations when quota limits are reached.