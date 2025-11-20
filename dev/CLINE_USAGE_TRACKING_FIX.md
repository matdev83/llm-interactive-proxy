# Cline and ZenMux Backend Token Usage Tracking Fix

## Problem
When using the `cline` and `zenmux` backend connectors, clients were not seeing token usage data and cost information in responses. This affected the ability to track API usage and costs.

## Root Cause
The issue was in the response header filtering logic in `src/core/transport/fastapi/response_adapters.py`. The header sanitization functions were only allowing headers with `x-` and `access-control-` prefixes, which filtered out provider-specific headers like:
- `anthropic-*` headers (e.g., `anthropic-ratelimit-*`)
- `openai-*` headers (e.g., `openai-organization`, `openai-processing-ms`)
- `zenmux-*` headers (e.g., `zenmux-cost`, `zenmux-model-id`)

While the usage data was correctly included in the response body's `usage` field, some clients also rely on provider-specific headers for additional metadata.

## Solution
Updated the header filtering logic to allow provider-specific headers:

### Changes Made

1. **Updated `_sanitize_headers()` function** (line ~305):
   - Added `anthropic-`, `openai-`, and `zenmux-` to the allowed header prefixes
   - This ensures provider-specific headers are forwarded to clients

2. **Updated `_create_json_response()` function** (line ~365):
   - Added `anthropic-`, `openai-`, and `zenmux-` to the allowed header prefixes
   - Ensures consistency in header filtering across the response pipeline

### Code Changes
```python
# Before
allowed_prefixes = ("x-", "access-control-")

# After
allowed_prefixes = ("x-", "access-control-", "anthropic-", "openai-", "zenmux-")
```

## Token Usage Flow

The token usage information flows through the system as follows:

1. **Backend Response**: The backend (Cline, OpenAI, Anthropic, etc.) returns usage data in the response body
2. **Translation Service**: Converts the backend response to domain format, extracting usage information
3. **ResponseEnvelope**: Contains both:
   - `usage` field with token counts (prompt_tokens, completion_tokens, total_tokens)
   - `headers` field with provider-specific headers
4. **Response Adapter**: Converts ResponseEnvelope to FastAPI response:
   - Merges `usage` into the response body (line 217)
   - Forwards allowed headers to the client
5. **Client**: Receives both usage data in body and provider headers

## Token Counting After Transformations

### ✅ FIXED: Automatic Usage Recalculation

The proxy now **automatically recalculates** token usage when content transformations are detected:

- **Backend transformations** (before LLM processing): Usage is accurate ✓
- **Proxy transformations** (after LLM response): Usage is **recalculated** to match actual content ✓

### How It Works

1. Backend processes request and returns usage based on original content
2. Proxy applies transformations (pytest compression, filtering, etc.)
3. **Proxy recalculates completion tokens** based on actual transformed content
4. **Prompt tokens are preserved** (input wasn't transformed)
5. Client receives accurate usage matching the actual content

### Example
```
Backend returns: 5000 chars, usage: {prompt_tokens: 100, completion_tokens: 1250, total_tokens: 1350}
Proxy compresses to: 1500 chars (70% reduction)
Proxy recalculates: {prompt_tokens: 100, completion_tokens: 375, total_tokens: 475}
Client receives: 1500 chars with accurate usage ✓
```

### Recalculation Logic

- **Threshold**: Only recalculates if difference is >5% AND >10 tokens
- **Method**: Uses tiktoken to count tokens in actual content
- **Logging**: Logs recalculation for transparency
- **Preservation**: Always preserves prompt_tokens (input unchanged)

### Impact
- **Cline/ZenMux**: Usage data accurately reflects transformed content ✓
- **Cost tracking**: Accurate even with compression/filtering ✓
- **Token limits**: Reported usage matches actual content received ✓

## Testing

Added comprehensive tests to verify the fix:

1. **`tests/unit/connectors/test_cline_usage_headers.py`**:
   - Verifies Cline connector includes headers in ResponseEnvelope
   - Tests that headers are available for usage tracking

2. **`tests/unit/connectors/test_cline_usage_flow.py`**:
   - Tests end-to-end flow from backend to client response
   - Verifies usage data appears in final client response
   - Confirms token counts reflect post-transformation values

3. **`tests/unit/core/transport/test_response_headers_forwarding.py`**:
   - Tests Anthropic-specific headers are forwarded
   - Tests OpenAI-specific headers are forwarded
   - Tests ZenMux-specific headers are forwarded
   - Tests custom x- headers are forwarded
   - Verifies hop-by-hop headers are filtered
   - Tests usage data in response body
   - Tests complete Cline response with usage and headers

4. **`tests/unit/connectors/test_zenmux_usage_tracking.py`**:
   - Verifies ZenMux connector includes headers in ResponseEnvelope
   - Tests end-to-end flow from ZenMux backend to client response
   - Tests ZenMux-specific headers are preserved

## Verification

To verify the fix works:

1. Make a request through the Cline backend
2. Check the response includes:
   - `usage` field in the response body with `prompt_tokens`, `completion_tokens`, and `total_tokens`
   - Provider-specific headers (e.g., `x-request-id`, `x-ratelimit-*`)

Example response:
```json
{
  "id": "chatcmpl-123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-4",
  "choices": [...],
  "usage": {
    "prompt_tokens": 25,
    "completion_tokens": 15,
    "total_tokens": 40
  }
}
```

With headers:
```
x-request-id: req-123
x-ratelimit-limit: 1000
x-ratelimit-remaining: 999
```

## Impact

- **Cline Backend**: Now properly reports token usage to clients
- **ZenMux Backend**: Now properly reports token usage and forwards ZenMux-specific headers
- **Anthropic Backend**: Headers like `anthropic-ratelimit-*` are now forwarded
- **OpenAI Backend**: Headers like `openai-organization` are now forwarded
- **All Backends**: Usage data in response body is preserved and forwarded
- **No Breaking Changes**: Existing functionality is preserved, only additional headers are now forwarded

## Files Modified

1. `src/core/transport/fastapi/response_adapters.py` - Updated header filtering logic and added usage recalculation
2. `src/core/services/response_manager_service.py` - Updated pytest compression to return token counts
3. `src/core/utils/usage_recalculation.py` - New utility for recalculating usage after transformations
4. `src/core/utils/token_count.py` - Existing token counting utility (used by recalculation)

## Files Added

1. `tests/unit/connectors/test_cline_usage_headers.py` - Tests for Cline header forwarding
2. `tests/unit/connectors/test_cline_usage_flow.py` - Tests for Cline end-to-end usage flow
3. `tests/unit/connectors/test_zenmux_usage_tracking.py` - Tests for ZenMux usage tracking
4. `tests/unit/core/transport/test_response_headers_forwarding.py` - Tests for provider header forwarding
5. `tests/unit/core/utils/test_usage_recalculation.py` - Tests for usage recalculation utility
6. `tests/unit/core/transport/test_usage_recalculation_integration.py` - Integration tests for usage recalculation
7. `src/core/utils/usage_recalculation.py` - Usage recalculation utility module
