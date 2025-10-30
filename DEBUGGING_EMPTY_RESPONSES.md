# Debugging Empty Streaming Responses from ZAI

## Current Issue

Client reports: "The model's response ended unexpectedly (no assistant messages). This may be a sign of rate limiting."

## Evidence from Logs

### Wire Capture (`logs/wire_capture.log`)
Shows streaming responses contain only empty deltas:
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion.chunk",
  "created": 1761854814,
  "model": "claude-3-opus-20240229",
  "choices": [{
    "index": 0,
    "delta": {},  // ← EMPTY!
    "finish_reason": null
  }]
}
```

Each request receives exactly 2 chunks, both with empty deltas, then stream ends.

### Proxy Log (`logs/proxy.log`)
Shows the request is being processed and streaming response is returned, but no errors are logged.

## Root Cause Analysis

The translation is working (chunks are in correct OpenAI format), but the chunks contain no content. This means:

1. **Either**: ZAI backend is sending events without content (ping events, metadata events, etc.)
2. **Or**: Our translation function is not extracting content from the ZAI response format
3. **Or**: ZAI backend is ending the stream prematurely without sending actual content

## Debugging Steps Added

Added logging to `src/connectors/anthropic.py` to capture:
- Raw chunks from ZAI backend before translation
- Translated chunk deltas after translation

## Resolution

**FOUND THE ISSUE**: ZAI backend is returning error events instead of content:

```
event: error
data: {"type": "error", "error": {"type": "1113", "message": "Insufficient balance or no resource package. Please recharge."}, "request_id": "..."}
```

### Root Cause
The ZAI API account has insufficient balance or no resource package. This is a **billing/account issue**, not a code issue.

### Why Client Shows "No Assistant Messages"
1. ZAI returns error events instead of content events
2. Our translation correctly converts error events to empty deltas (no content)
3. Client receives only empty chunks and reports "no assistant messages"

### Solution
**Recharge the ZAI API account** or ensure it has an active resource package.

### Code Status
The streaming translation fix is working correctly. The translation properly handles:
- ✅ Anthropic SSE format parsing
- ✅ Error event handling (now raises BackendError with clear message)
- ✅ Content event handling (would extract text if present)

### Improvements Made
Added proper error handling in `src/connectors/anthropic.py`:
- Detects error events in streaming responses
- Extracts error message and type from error events
- Raises `BackendError` with clear error message instead of silently returning empty responses
- Includes error details for debugging

Now when ZAI returns an error like "Insufficient balance", the client will receive a proper error message instead of "no assistant messages".

### Tests Added
Created `tests/unit/connectors/test_anthropic_error_handling.py` with 3 tests:
- ✅ Test error event handling in Anthropic connector
- ✅ Test generic error handling
- ✅ Test zai-coding-plan inherits error handling

All tests pass.

## Expected Anthropic SSE Format

Standard Anthropic streaming should include events like:
```
event: message_start
data: {"type":"message_start","message":{"role":"assistant"}}

event: content_block_delta  
data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello"}}

event: message_stop
data: {"type":"message_stop"}
```

If ZAI is sending a different format, we need to adjust the translation accordingly.
