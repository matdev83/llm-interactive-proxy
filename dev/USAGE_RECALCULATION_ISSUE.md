# Token Usage Recalculation After Content Transformations - Issue Analysis

## Critical Issue Identified

The proxy currently does **NOT** recalculate token usage after content transformations, leading to inaccurate usage reporting.

## Problem Flow

1. **Backend processes request** → Returns response with usage: `{prompt_tokens: 100, completion_tokens: 500, total_tokens: 600}`
2. **Proxy applies transformations**:
   - Pytest output compression (removes PASSED lines, timing info)
   - Content filtering
   - Other middleware modifications
3. **Proxy forwards response** → Client receives transformed content BUT original usage counts
4. **Result**: Token counts don't reflect actual content received by client

## Example Scenario

```
Backend Response:
- Content: 5000 characters of pytest output
- Usage: {prompt_tokens: 100, completion_tokens: 1250, total_tokens: 1350}

After Pytest Compression (70% reduction):
- Content: 1500 characters (compressed)
- Usage: {prompt_tokens: 100, completion_tokens: 1250, total_tokens: 1350}  ← WRONG!
- Actual tokens in compressed content: ~375 tokens

Client sees:
- Small compressed output
- Large token count that doesn't match
- Inaccurate cost calculation
```

## Current Behavior

### What Works
- **Cline/ZenMux/OpenAI connectors**: Headers are forwarded ✓
- **Usage in response body**: Backend usage is included ✓
- **Token counting utility**: `count_tokens()` exists and works ✓

### What's Broken
- **Usage recalculation**: NOT done after transformations ✗
- **Response manager**: Calculates tokens for logging only ✗
- **Middleware**: Doesn't update usage field ✗

## Where Transformations Happen

1. **`response_manager_service.py`**:
   - `_filter_pytest_output_with_metrics()` - Compresses pytest output
   - Calculates `final_tokens` but doesn't update usage
   - Returns only the filtered string

2. **Middleware chain**:
   - Various middleware can modify content
   - No mechanism to update usage after modifications

## Current Token Calculation

```python
# In response_manager_service.py (lines 703-746)
from src.core.utils.token_count import count_tokens

original_tokens = count_tokens(output)
# ... filtering happens ...
final_tokens = count_tokens(filtered_output)
tokens_filtered = original_tokens - final_tokens

# BUT: This is only logged, not used to update response.usage!
logger.info(f"Filtered: {tokens_filtered} tokens")
return filtered_output  # Just the string, no usage update
```

## Impact

### For Cline Backend
- ✓ Headers forwarded
- ✓ Usage in response body
- ✗ Usage doesn't reflect proxy transformations
- **Impact**: Medium - Usage is present but inaccurate after transformations

### For ZenMux Backend
- ✓ Headers forwarded
- ✓ Usage in response body
- ✗ Usage doesn't reflect proxy transformations
- **Impact**: Medium - Usage is present but inaccurate after transformations

### For All Backends
- ✗ Token counts don't match transformed content
- ✗ Cost calculations are inaccurate
- ✗ Usage tracking is misleading

## Solution Required

### Option 1: Recalculate Usage After Transformations (Recommended)
Update the response flow to recalculate token usage after all content transformations:

1. **Track original usage** from backend
2. **Apply transformations** (compression, filtering, etc.)
3. **Recalculate completion tokens** based on final content
4. **Update usage field** in response
5. **Preserve prompt tokens** (input wasn't transformed)

### Option 2: Disable Transformations for Usage Accuracy
- Don't apply transformations when accurate usage is required
- Add flag to disable compression/filtering
- **Downside**: Clients receive verbose output

### Option 3: Report Both Original and Transformed Usage
- Include both `original_usage` and `transformed_usage` in response
- Let clients decide which to use
- **Downside**: More complex API

## Recommended Implementation

### 1. Update Response Manager

```python
def _filter_pytest_output_with_metrics(self, output: str, original_usage: dict | None = None) -> tuple[str, dict]:
    """Filter pytest output and return updated usage."""
    from src.core.utils.token_count import count_tokens
    
    original_tokens = count_tokens(output)
    # ... filtering logic ...
    final_tokens = count_tokens(filtered_output)
    
    # Recalculate usage if provided
    updated_usage = None
    if original_usage:
        # Preserve prompt tokens (input wasn't transformed)
        prompt_tokens = original_usage.get("prompt_tokens", 0)
        
        # Recalculate completion tokens based on actual output
        completion_tokens = final_tokens
        
        updated_usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
    
    return filtered_output, updated_usage
```

### 2. Update Response Flow

Ensure that when content is transformed, usage is recalculated and updated in the ResponseEnvelope before it's sent to the client.

### 3. Add Metadata

Include transformation metadata:
```json
{
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 375,
    "total_tokens": 475
  },
  "metadata": {
    "original_completion_tokens": 1250,
    "compression_applied": true,
    "compression_ratio": 0.70
  }
}
```

## Testing Requirements

1. Test that usage is recalculated after pytest compression
2. Test that usage is recalculated after content filtering
3. Test that prompt tokens are preserved
4. Test that completion tokens match actual output
5. Test that total tokens = prompt + completion

## Priority

**HIGH** - This affects billing accuracy and usage tracking for all backends when transformations are applied.

## Related Files

- `src/core/services/response_manager_service.py` - Where transformations happen
- `src/core/utils/token_count.py` - Token counting utility
- `src/core/domain/responses.py` - ResponseEnvelope definition
- `src/core/transport/fastapi/response_adapters.py` - Where usage is merged into response
