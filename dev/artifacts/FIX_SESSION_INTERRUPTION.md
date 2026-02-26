# Fix: Premature Session Termination Issue

## Problem

Agent sessions (like OpenCode) were being interrupted prematurely, with the agent stopping as if it received an end-of-session marker, even though the task was not complete and more tool calls were needed.

## Root Cause

The proxy was including `usage` data (token counts) in streaming response chunks that had `finish_reason: "tool_calls"`. 

According to OpenAI's streaming API specification, the presence of `usage` data in a streaming chunk signals that this is the **final chunk** of the response. Many agents interpret this as "the conversation is complete" and stop processing, even if the finish_reason is "tool_calls" (which should trigger another round of interaction).

### Example of the problematic chunk:

```json
{
  "id": "chatcmpl-3680c45d3624436e",
  "choices": [{
    "index": 0,
    "delta": {
      "role": "assistant",
      "tool_calls": [{"id": "call_...", "function": {"name": "bash", ...}}]
    },
    "finish_reason": "tool_calls"
  }],
  "usage": {  // <-- This signals "session complete" to agents!
    "prompt_tokens": 59384,
    "completion_tokens": 0,
    "total_tokens": 59384
  }
}
```

When agents see this, they interpret it as:
1. "Here are some tool calls to execute" (from finish_reason)
2. "And this is the final message" (from usage presence)
3. Result: Session ends prematurely

## Solution

Modified `src/core/transport/fastapi/adapters/streaming/content_converter.py` to **exclude** usage data from streaming chunks when `finish_reason` is `"tool_calls"`.

Usage data is now only included for truly final responses:
- `finish_reason: "stop"` - Normal conversation end
- `finish_reason: "length"` - Max tokens reached
- `finish_reason: "content_filter"` - Content policy violation

### Changes Made

1. **Lines 735-766**: Added logic to check finish_reason before applying usage to enriched payload
2. **Lines 792-807**: Added logic to check finish_reason before synthesizing/overriding usage
3. Added debug logging when usage is excluded from tool_calls responses

## Testing

- All 43 existing streaming adapter tests pass
- Verified that usage exclusion logic works correctly for tool_calls
- Verified that usage is still included for "stop", "length", and other final responses

## Impact

After this fix:
- Tool call responses no longer include usage data
- Agents correctly continue the session after executing tools
- The `[DONE]` sentinel is still sent (ending the current SSE stream)
- But agents understand they should send tool results back for another turn
- Usage data is still tracked internally and reported at true conversation end

## Before Fix

```
Agent -> Proxy: [User prompt]
Proxy -> Backend: [Forwarded]
Backend -> Proxy: [Tool calls + usage]  
Proxy -> Agent: [Tool calls + usage]  <-- Agent sees usage, thinks session is done
Agent: <STOPS> ❌
```

## After Fix

```
Agent -> Proxy: [User prompt]
Proxy -> Backend: [Forwarded]
Backend -> Proxy: [Tool calls + usage]  
Proxy -> Agent: [Tool calls WITHOUT usage]  <-- Agent knows to continue
Agent: <Executes tools, sends results back> ✓
... conversation continues ...
```

## Files Modified

- `src/core/transport/fastapi/adapters/streaming/content_converter.py`

## Date

2026-02-26
