# Anthropic/ZAI Streaming Translation Fix

## Problem

The Anthropic connector (and by inheritance, the zai-coding-plan connector) was not translating streaming chunks to the internal domain format. This caused Anthropic-formatted SSE chunks to flow through the system untranslated, breaking cross-API compatibility.

### Root Cause

**OpenAI Connector** (`src/connectors/openai.py` lines 629-637):
- ✅ Translates each streaming chunk using `translation_service.to_domain_stream_chunk()`
- Converts OpenAI/Responses API format → domain format (OpenAI-compatible)

**Anthropic Connector** (`src/connectors/anthropic.py` lines 530-540):
- ❌ Did NOT translate streaming chunks
- Just passed through raw Anthropic SSE chunks wrapped in `ProcessedResponse`

**zai-coding-plan Connector**:
- Inherits from `AnthropicBackend`
- Does not override `_handle_streaming_response()`
- Therefore inherited the broken streaming behavior

## Solution

### 1. Fixed Anthropic Connector Streaming (`src/connectors/anthropic.py`)

Updated the `event_stream()` function to translate each chunk:

```python
async def event_stream() -> AsyncGenerator[ProcessedResponse, None]:
    try:
        async for chunk in response.aiter_text():
            _capture_message_id(chunk)
            
            # Translate Anthropic SSE chunk to domain format
            domain_chunk = self.translation_service.to_domain_stream_chunk(
                chunk, "anthropic"
            )
            yield ProcessedResponse(content=domain_chunk)
        
        # Translate final [DONE] marker
        done_chunk = self.translation_service.to_domain_stream_chunk(
            "data: [DONE]\n\n", "anthropic"
        )
        yield ProcessedResponse(content=done_chunk)
```

### 2. Enhanced Translation Function (`src/core/domain/translation.py`)

Updated `anthropic_to_domain_stream_chunk()` to handle SSE format:

**Before**: Only accepted parsed JSON dicts
**After**: Accepts both SSE-formatted strings and JSON dicts

Key improvements:
- Parses multi-line SSE events (with `event:` and `data:` lines)
- Extracts JSON from `data:` lines
- Handles all Anthropic event types:
  - `message_start` → sets role
  - `content_block_delta` → extracts text content
  - `message_delta` → maps stop_reason to finish_reason
  - `message_stop` → marks completion
- Maps Anthropic stop reasons to OpenAI equivalents:
  - `end_turn` → `stop`
  - `max_tokens` → `length`
  - `tool_use` → `tool_calls`
- Handles `[DONE]` markers
- Backward compatible with dict format

## Tests Created

### Translation Layer Tests (`tests/unit/core/domain/test_translation_anthropic_streaming.py`)

16 comprehensive tests covering:
- SSE content deltas
- Message start/stop events
- Stop reason mapping
- [DONE] marker handling
- Event line parsing
- Multi-line SSE format
- Invalid JSON handling
- Backward compatibility with dict format
- OpenAI structure preservation

### Connector Tests (`tests/unit/connectors/test_anthropic_streaming_translation.py`)

4 integration tests covering:
- End-to-end Anthropic streaming translation
- SSE format handling in connector
- [DONE] marker translation
- zai-coding-plan inheritance verification

## Impact

### Fixed
- ✅ Anthropic connector now emits domain-formatted chunks
- ✅ zai-coding-plan connector inherits the fix automatically
- ✅ Cross-API translation works correctly for streaming
- ✅ Downstream processors receive consistent OpenAI-style format

### Verified
- ✅ All 20 new tests pass
- ✅ All 15 existing translation tests still pass
- ✅ Backward compatibility maintained

## Why Tests Didn't Catch This

The existing tests mocked the translation service or didn't verify the actual format of streaming chunks. The new tests:
1. Test the actual translation function with SSE input
2. Test the connector's streaming handler end-to-end
3. Verify the output format matches OpenAI structure
4. Ensure zai-coding-plan inherits the correct behavior

## Files Modified

1. `src/connectors/anthropic.py` - Added streaming translation
2. `src/core/domain/translation.py` - Enhanced SSE parsing
3. `tests/unit/connectors/test_anthropic_streaming_translation.py` - New connector tests
4. `tests/unit/core/domain/test_translation_anthropic_streaming.py` - New translation tests
