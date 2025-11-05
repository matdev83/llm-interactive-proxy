# ZAI Backend Max Tokens Implementation

## Overview

Both ZAI connectors (`zai` and `zai-coding-plan`) now enforce a 200K (200,000 tokens) maximum output limit as specified by the ZAI API provider.

## Implementation Details

### Default Behavior
- **Default max_tokens**: 200,000 (200K)
- This is the maximum supported by ZAI's backend models
- Used when client doesn't explicitly specify max_tokens or provides invalid values (None, 0, negative)

### Client Override Rules
Clients can override the default by explicitly setting `max_tokens` in their request:

1. **Valid Range**: 1,024 to 200,000 tokens
   - Values below 1K are clamped to 1,024
   - Values above 200K are clamped to 200,000
   - Values within range are preserved as-is

2. **Invalid Values**: None, 0, or negative numbers
   - Automatically use the 200K default
   - Ensures requests never fail due to missing/invalid max_tokens

### Code Locations

#### ZaiCodingPlanBackend
- File: `src/connectors/zai_coding_plan.py`
- Method: `_prepare_payload()`
- Inherits from: `OpenAIConnector`

#### ZAIConnector
- File: `src/connectors/zai.py`
- Method: `_prepare_payload()`
- Inherits from: `OpenAIConnector`

## Examples

### Example 1: No max_tokens specified
```python
request = {
    "model": "zai-coding-plan:glm-4.6",
    "messages": [{"role": "user", "content": "Hello"}],
    # max_tokens not specified
}
# Result: max_tokens = 200000 (200K)
```

### Example 2: Explicit valid value
```python
request = {
    "model": "zai-coding-plan:glm-4.6",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 4096
}
# Result: max_tokens = 4096 (preserved)
```

### Example 3: Value below minimum
```python
request = {
    "model": "zai-coding-plan:glm-4.6",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 512
}
# Result: max_tokens = 1024 (clamped to minimum)
```

### Example 4: Value above maximum
```python
request = {
    "model": "zai-coding-plan:glm-4.6",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 200000
}
# Result: max_tokens = 200000 (clamped to maximum)
```

## Testing

Comprehensive test suite in `tests/unit/connectors/test_zai_max_tokens.py` covers:
- Default behavior (None, 0, negative values)
- Explicit valid values preservation
- Minimum boundary clamping
- Maximum boundary clamping
- Exact boundary values

All tests pass successfully.

## Benefits

1. **Prevents 422 Errors**: Ensures max_tokens is always valid
2. **Maximizes Output**: Uses 200K by default for agentic coding tasks
3. **Client Control**: Allows explicit override within valid range
4. **Robust**: Handles edge cases (None, 0, negative, out-of-range)
5. **Consistent**: Same logic across both ZAI connectors
