# TODO List - Tool Call Processing Fixes

## 1. ✅Current Issue: Tool Call Lifecycle Double-Registration

**Priority:** P0 - BLOCKING
**Status:** COMPLETED

### Resolution
- Modified `ToolCallReactorMiddleware.process` to only process tool calls when the response is complete (checked via `finish_reason` or `is_done`). This prevents processing partial tool calls which were causing premature lifecycle registration.
- Updated `_should_reset_stream_state` to avoid resetting state on `finish_reason` during streaming, ensuring deduplication persists until the stream is explicitly done.

### Problem

Tool calls are being registered as "detected" before they're complete, causing them to be skipped when actually ready to process.

### Evidence from logs

```
2025-11-25 10:56:21,873 [DEBUG] ToolCallRepairProcessor captured tool call(s): [{'id': 'call_53303b9bde5a4de88c343ac737e45a32', 'type': 'function', 'function': {'name': 'command'...
2025-11-25 10:56:21,874 [DEBUG] Skipping already-processed tool call (signature=call_53303b9bde5a4de88c343ac737e45a32)
```

### Root Cause

In `tool_call_reactor_middleware.py` line 167:

- `register_detection()` is called for EVERY tool call seen
- If a tool call was seen in a previous chunk (even incomplete), `is_new = False`
- This causes the complete tool call to be skipped (line 169)

### The Issue Chain

1. Chunk 1: `<execute_command>` starts → Tool call registered in lifecycle
2. Chunk 2: `<command>...</command>` → Tool call still incomplete
3. Chunk 3: `</execute_command>` → Tool call NOW complete and captured
4. But lifecycle says "not new" → SKIPPED!

### Solution

**Option A:** ToolCallRepairProcessor should only register tool calls in lifecycle AFTER they're complete
**Option B:** Change lifecycle to track "partial" vs "complete" states
**Option C:** Only call `register_detection()` for buffered calls that are complete

### Files to Fix

**Status:** DONE

### Recent Fix

Added all XML tool tags to `BUFFERED_TOOL_TAGS` in response_adapters.py

### Verification Needed

- Run integration test with real Gemini session
- Verify `<ask_followup_question>` no longer leaks
- Check wire_capture.log for clean tool call emission

---

## Notes

- All issues are related to the P0 architectural gaps identified in streaming-refactor assessment
- Issue #1 is the immediate blocker causing client failures
- Issue #2 affects UX clarity but doesn't break functionality
