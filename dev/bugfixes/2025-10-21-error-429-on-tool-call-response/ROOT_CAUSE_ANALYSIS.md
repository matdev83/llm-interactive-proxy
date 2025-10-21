# Root Cause Analysis: 429 Errors During Streaming

## Critical Discovery

After comparing our implementation with the working `gemini-cli` reference code, I found **fundamental differences in how we handle streaming requests** that are likely causing the 429 "Resource Exhausted" errors.

## Key Differences Between Our Code and gemini-cli

### 1. **CRITICAL: Duplicate Request Pattern**

**gemini-cli approach (working):**
```typescript
// Single request with alt=sse parameter for streaming
const response = await fetch(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(requestBody),
  // IMPORTANT: Uses ?alt=sse in URL params for streaming
});
```

**Our approach (problematic):**
```python
# NON-STREAMING REQUEST FIRST (line 1396-1403)
response = await asyncio.to_thread(
    auth_session.request,
    method="POST",
    url=url,
    params={"alt": "sse"},  # ❌ This makes a FULL request!
    json=request_body,
    headers={"Content-Type": "application/json"},
    timeout=int(DEFAULT_READ_TIMEOUT),
    # ❌ NO stream=True here - this is a complete request!
)

# THEN LATER: STREAMING REQUEST (line 1670-1679)
response = await asyncio.to_thread(
    auth_session.request,
    method="POST", 
    url=url,
    params={"alt": "sse"},  # ❌ SECOND identical request!
    json=request_body,
    headers={"Content-Type": "application/json"},
    timeout=int(DEFAULT_READ_TIMEOUT),
    stream=True,  # ❌ This makes ANOTHER request!
)
```

### 2. **Root Cause: We're Making TWO Requests Instead of One**

Looking at our code in `src/connectors/gemini_oauth_base.py`:

1. **Line 1396-1403**: We make a **complete non-streaming request** with `alt=sse` parameter
2. **Line 1670-1679**: We make **another identical request** with `stream=True`

**This means for every user request, we're actually hitting the Gemini API TWICE:**
- First request: Gets the full response (consumes quota)
- Second request: Gets the same response again in streaming mode (consumes more quota)

### 3. **Why This Causes 429 Errors**

The Gemini API has rate limiting and quota management that detects:
- **Duplicate requests** with identical payloads
- **Rapid successive requests** from the same client
- **Excessive quota consumption** due to duplicate processing

Our implementation triggers all three conditions because we're essentially **making the same request twice in rapid succession**.

### 4. **Why It Works Initially Then Fails Mid-Session**

- **Initial requests**: Work because quota is available for duplicate requests
- **Mid-session failure**: After several exchanges, the **doubled quota consumption** hits limits
- **Rate limiting**: Gemini API starts rejecting the duplicate requests with 429 errors

## Code Flow Analysis

### Our Problematic Flow:
```
1. User sends request
2. _chat_completions_code_assist_streaming() called
3. First API call made (lines 1396-1403) - CONSUMES QUOTA
4. Response processed and checked
5. stream_generator() called  
6. Second identical API call made (lines 1670-1679) - CONSUMES MORE QUOTA
7. Stream processing begins
8. Eventually: 429 error due to doubled quota usage
```

### gemini-cli Correct Flow:
```
1. User sends request
2. Single API call made with streaming enabled
3. Stream processing begins immediately
4. Single quota consumption per request
```

## Evidence from Logs

Looking at the wire capture logs, I can see:
- Multiple `stream_start` events for what should be single requests
- Successful responses followed by 429 errors
- Pattern suggests quota accumulation over time

## The Fix Required

We need to **eliminate the duplicate request pattern**. The solution is:

1. **Remove the first non-streaming request** (lines 1396-1403)
2. **Use only the streaming request** with proper error handling
3. **Handle response validation within the streaming generator**

### Proposed Code Change:

```python
async def _chat_completions_code_assist_streaming(self, request: dict) -> AsyncGenerator[ProcessedResponse, None]:
    """Stream Code Assist API responses - SINGLE REQUEST ONLY"""
    
    # Build request body
    request_body = self._build_code_assist_request_body(request)
    
    # Get auth session
    auth_session = await self._get_auth_session()
    if not auth_session:
        raise AuthenticationError("Failed to get authenticated session")
    
    url = f"{self.gemini_api_base_url}/v1internal:streamGenerateContent"
    
    # SINGLE REQUEST - no duplicate calls
    try:
        response = await asyncio.to_thread(
            auth_session.request,
            method="POST",
            url=url,
            params={"alt": "sse"},
            json=request_body,
            headers={"Content-Type": "application/json"},
            timeout=int(DEFAULT_READ_TIMEOUT),
            stream=True,  # ✅ Only streaming request
        )
    except requests.exceptions.RequestException as e:
        # Handle connection errors
        yield error_response
        return
    
    # Handle errors within streaming context
    if response.status_code >= 400:
        # Yield error chunk instead of raising exception
        yield error_response
        return
    
    # Process streaming response
    async for chunk in self._process_streaming_chunks(response):
        yield chunk
```

## Impact Assessment

### Current Impact:
- **2x quota consumption** per request
- **Rate limiting triggers** after several exchanges
- **429 errors** appear mid-session when limits hit
- **Poor user experience** with unexplained disconnections

### After Fix:
- **Normal quota consumption** (50% reduction)
- **No rate limiting issues** from duplicate requests
- **Stable mid-session performance**
- **Consistent behavior** matching gemini-cli

## Verification Plan

1. **Implement the single-request fix**
2. **Test with quota monitoring** to confirm 50% reduction in API calls
3. **Run extended sessions** to verify no mid-session 429 errors
4. **Compare behavior** with gemini-cli for consistency

## Conclusion

The 429 errors are caused by our **duplicate request pattern** that makes two identical API calls per user request, leading to:
- Doubled quota consumption
- Rate limiting triggers  
- Mid-session failures when limits are reached

This is a **fundamental architectural issue** in our streaming implementation that needs immediate correction.