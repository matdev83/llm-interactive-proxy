# Gemini OAuth Antigravity Backend - Fix Failure Report

**Date:** November 28, 2025  
**Session Duration:** Full day (~10+ hours)  
**Status:** UNRESOLVED - Multiple critical issues persist

---

## Executive Summary

Despite multiple attempts over a full day, the following critical issues with the `gemini-oauth-antigravity` backend connector remain unfixed:

1. **Usage data leaking into message content** - JSON chunks containing usage info appear in session history
2. **Regular message content not displayed** - Only tool call results are rendered
3. **File edit tool calls failing** - SEARCH/REPLACE markers may be getting corrupted
4. **Token usage not properly reported** - Billing info not in OpenRouter standard format

---

## Diagnostic Resources

- **Log file:** `var/logs/proxy-2005.log`
- **CBOR capture:** `var/wire_captures_cbor/proxy-2005.cbor`
- **Analysis tool:** `scripts/inspect_cbor_capture.py`

### How to Analyze CBOR Captures

```bash
# Basic inspection
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/proxy-2005.cbor --analyze

# Show specific entries
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/proxy-2005.cbor --entries 20

# Filter by direction
./.venv/Scripts/python.exe scripts/inspect_cbor_capture.py var/wire_captures_cbor/proxy-2005.cbor --direction proxy_to_client --entries 20
```

---

## Issue 1: Usage Data Leaking Into Session Content

### Symptom

JSON chunks like this appear in the message history sent to the backend:

```json
{"id": "chatcmpl-f9234981ed334be0", "object": "chat.completion.chunk", "created": 1764356748, "model": "gemini-3-pro-high", "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 19369, "completion_tokens": 516, "total_tokens": 19885}}
```

### Root Cause Analysis (Incomplete)

The stop chunk with usage data is being serialized as a STRING and stored in `delta.content` instead of being emitted as a top-level SSE chunk. This corrupted content then gets accumulated into the conversation history.

### What Was Tried

1. **Created `StopChunkWithUsage` wrapper class** - A dict subclass that raises `UsageChunkLeakError` when `str()` is called on it. This was supposed to catch accidental stringification.

2. **Fixed `_normalize_content()` in `response_adapters.py`** - Added check to preserve `StopChunkWithUsage` instances:
   ```python
   if isinstance(content, StopChunkWithUsage):
       return content
   ```

3. **Fixed `_chunk_signals_done()` in `response_adapters.py`** - Added detection for chunks with `finish_reason: stop/tool_calls/length`:
   ```python
   if isinstance(content, dict):
       choices = content.get("choices", [])
       if choices and isinstance(choices, list):
           first_choice = choices[0]
           if isinstance(first_choice, dict):
               fr = first_choice.get("finish_reason")
               if fr in ("stop", "tool_calls", "length"):
                   return True
   ```

4. **Wrapped final chunk in `StopChunkWithUsage`** in `gemini_oauth_base.py` connector at lines 3584 and 3603.

### Why It Failed

The `StopChunkWithUsage` protection is being bypassed somewhere in the pipeline. Possible locations:

1. **`non_streaming_adapter.py` lines 112-116:**
   ```python
   elif isinstance(chunk.content, dict):
       final_content += json.dumps(chunk.content)
   ```
   This converts dict to JSON string - `StopChunkWithUsage` IS a dict subclass.

2. **`non_streaming_adapter.py` line 124:**
   ```python
   final_content += str(chunk.content)
   ```
   This calls `str()` on ProcessedResponse content.

3. **`content_accumulation_processor.py` lines 189-190:**
   ```python
   else:
       chunk_text = json.dumps(raw_chunk)
   ```
   Fallback JSON serialization.

4. **`streaming_contracts.py` line 461:**
   ```python
   delta["content"] = json.dumps(self.content)
   ```
   If the stop chunk doesn't have `choices` key (impossible but defensive).

5. **The wire capture shows Entry 8 (P->B) with content:**
   ```json
   "delta": {"role": "assistant", "content": "{\"id\": \"chatcmpl-c0ca3ba226784841\", ...\"usage\": ...}"}
   ```
   This proves the JSON is being EMBEDDED in delta.content somewhere.

### Key Observation

CBOR capture analysis showed:
- Entry 7 (B->P): Backend sends correct stop chunk with usage
- Entry 8 (P->B): Proxy sends TRANSFORMED chunk where usage JSON is IN `delta.content`

Something between receiving the backend response and sending to client is WRAPPING the entire chunk as content of another chunk.

---

## Issue 2: Regular Message Content Not Displayed

### Symptom

Client (KiloCode) only sees tool call results, not the regular text content from the LLM.

### Likely Cause

Related to Issue 1 - the content accumulation/streaming pipeline is broken. The regular text content may be:
1. Being filtered out incorrectly
2. Not being properly extracted from the Gemini response format
3. Getting lost during format translation

### Investigation Needed

1. Check `TranslationService.to_domain_stream_chunk()` for Gemini format
2. Check content extraction in `content_accumulation_processor.py`
3. Verify delta.content is being properly populated in non-tool-call chunks

---

## Issue 3: File Edit Tool Calls Failing

### Symptom

Tool calls containing SEARCH/REPLACE diff markers are failing. File creation works.

### Suspected Cause

The SEARCH/REPLACE markers use patterns like:
```
>>>>>>>>>>> SEARCH
content to find
===========
replacement content
<<<<<<<<<<< REPLACE
```

These may be:
1. Getting corrupted by regex/string processing
2. Triggering some escape sequence handling
3. Being parsed as special delimiters somewhere

### Investigation Needed

1. Search for regex patterns that might match `>>>>>>` or `<<<<<<`
2. Check `tool_call_repair_service.py` for any processing of tool arguments
3. Look for any string replacement/escaping that might affect these markers
4. Check if content is being double-escaped (JSON within JSON)

### Key Files to Examine

- `src/core/services/tool_call_repair_service.py`
- `src/core/services/streaming/tool_call_repair_processor.py`

---

## Issue 4: Token Usage Not Properly Reported

### Symptom

Token usage/billing information is not being reported to clients in the standard OpenRouter format.

### Expected Format (OpenRouter Standard)

According to OpenRouter docs, usage should be in the response as:
```json
{
  "usage": {
    "prompt_tokens": 123,
    "completion_tokens": 456,
    "total_tokens": 579
  }
}
```

### Investigation Needed

1. Check how usage is being extracted from Gemini responses
2. Verify usage is being properly propagated through the pipeline
3. Ensure final SSE chunk contains usage at top level (not in delta)

---

## Code Changes Made (May Need Reverting/Revision)

### Files Modified

1. **`src/core/transport/fastapi/response_adapters.py`**
   - `_normalize_content()` - Added StopChunkWithUsage preservation
   - `_chunk_signals_done()` - Added finish_reason detection

2. **`src/core/services/translation_service.py`**
   - Added `_extract_content_from_domain_chunk()` helper
   - Modified `from_domain_to_anthropic_stream_chunk()`
   - Modified `from_domain_to_gemini_stream_chunk()`
   - Added `_dict_to_canonical_stream_chunk()`
   - Modified `to_domain_stream_chunk()` to return CanonicalStreamChunk

3. **`src/anthropic_converters.py`**
   - Changed `anthropic_to_openai_request()` return type to CanonicalChatRequest

4. **`src/core/app/controllers/anthropic_controller.py`**
   - Updated to handle CanonicalChatRequest

5. **`src/core/services/usage_tracking_service.py`**
   - Fixed syntax error (missing logger.debug call)

### Tests Created

- `tests/regression/test_stop_chunk_wrapper_preservation.py` - 12 tests for StopChunkWithUsage
- Modified `scripts/verify_gemini_antigravity_fixes.py`

---

## Reflections on Why Fixes Failed

### 1. Incomplete Understanding of Data Flow

The streaming pipeline is complex with multiple layers:
```
Connector -> ProcessedResponse -> ResponseAdapters -> StreamingContent -> SSEAssembler -> Client
```

The fix was applied in one layer (`_normalize_content`, `_chunk_signals_done`) but the leak happens in a different layer. Need to trace the EXACT code path where the stop chunk gets stringified.

### 2. Dict Subclass Gotcha

`StopChunkWithUsage(dict)` passes `isinstance(x, dict)` checks. Many places in the code use:
```python
if isinstance(chunk, dict):
    # process as dict
```

This means `StopChunkWithUsage` is treated as a regular dict in many places, bypassing the protective `__str__` override.

### 3. Multiple Code Paths

The same chunk can flow through different paths depending on:
- Whether it's streaming or non-streaming
- Whether it has tool_calls
- Whether it's marked is_done
- The format (OpenAI vs Anthropic vs Gemini)

The fix may have addressed one path but not others.

### 4. Insufficient Tracing

We identified the SYMPTOM (JSON in delta.content) but didn't trace the EXACT line where this happens. Need to add logging/breakpoints to find the precise location.

### 5. Test-Reality Gap

The unit tests pass because they test individual components in isolation. The actual failure happens in the integration of multiple components during real streaming.

---

## Recommended Next Steps

### Immediate Actions

1. **Add comprehensive tracing** in the streaming pipeline to log every transformation of the stop chunk
2. **Use debugger** or print statements to find the EXACT line where the JSON gets embedded in delta.content
3. **Compare working vs broken** - If other backends work correctly, diff their code paths

### Specific Areas to Investigate

1. **`_convert_to_streaming_content()` in response_adapters.py** (lines 1128-1204) - This is where ProcessedResponse becomes StreamingContent

2. **`SSEAssembler.assemble_stream()` in sse_assembler.py** - This is where StreamingContent becomes bytes

3. **`StreamingContent.to_bytes()` in streaming_contracts.py** - The actual serialization logic

4. **Search for ALL places where `json.dumps` is called on chunk content**

### Testing Approach

1. Create a minimal reproduction test that:
   - Creates a StopChunkWithUsage
   - Passes it through the FULL pipeline (not just individual components)
   - Verifies the output bytes

2. Run with real KiloCode client and capture BOTH proxy logs AND wire captures

3. Compare byte-by-byte what backend sends vs what client receives

---

## Additional Context

### Client: KiloCode

KiloCode is a VS Code extension that:
- Uses OpenAI-compatible API
- Parses XML tool calls from content
- May have specific expectations about SSE format

### Backend: gemini-oauth-antigravity

- Uses Google's Code Assist API
- OAuth authentication
- Returns Gemini-format responses that get translated to OpenAI format

### Key Configuration

The connector is configured in the proxy config and uses:
- `gemini_api_base_url` for the endpoint
- OAuth credentials loaded at startup
- TranslationService for format conversion

---

## Files Reference

### Core Streaming Pipeline
- `src/core/ports/streaming_contracts.py` - StreamingContent, StopChunkWithUsage
- `src/core/ports/sse_assembler.py` - SSEAssembler
- `src/core/transport/fastapi/response_adapters.py` - Domain to FastAPI conversion
- `src/core/services/streaming/content_accumulation_processor.py` - Content buffering
- `src/core/services/streaming/non_streaming_adapter.py` - Stream to non-stream conversion

### Gemini Connector
- `src/connectors/gemini_oauth_base.py` - Base Gemini OAuth connector
- `src/connectors/gemini_oauth_antigravity.py` - Antigravity-specific connector

### Translation
- `src/core/services/translation_service.py` - Format translation
- `src/core/domain/translation.py` - Translation logic

---

## Contact/Handoff Notes

The user has been working on this all day and is frustrated. The issue is critical for production use. Focus on:
1. Actually finding WHERE the stringification happens (not just adding guards)
2. Testing with the real client/backend combination
3. Not breaking other backend connectors

The `StopChunkWithUsage` protection concept is sound but not being triggered because `json.dumps(dict)` doesn't call `__str__`. May need to override `__iter__` or use a different protection mechanism.


