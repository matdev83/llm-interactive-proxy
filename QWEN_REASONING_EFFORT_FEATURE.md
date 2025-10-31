# Qwen OAuth Reasoning Effort Feature

## Overview
Enhanced the Qwen OAuth connector to support reasoning effort levels by automatically appending " /think" to messages when reasoning effort is set to medium or high.

## Implementation Details

### Changes Made
1. **Modified `src/connectors/qwen_oauth.py`**:
   - Updated `chat_completions()` method to detect `reasoning_effort` parameter
   - When `reasoning_effort` is "medium" or "high", appends " /think" to the last client message
   - Only appends to user or system messages, not tool responses
   - Handles both Pydantic models and dict message formats

### How It Works
- The connector checks if `reasoning_effort` is set to "medium" or "high"
- It finds the last client message (user or system role, skipping tool responses)
- Appends " /think" to the content of that message
- This triggers Qwen's extended reasoning mode for more thoughtful responses

### Usage Example
```python
request = ChatRequest(
    model="qwen-turbo",
    messages=[
        ChatMessage(role="user", content="What is 2+2?")
    ],
    reasoning_effort="medium"  # or "high"
)
```

The message will be transformed to: "What is 2+2? /think"

### Test Coverage
Created comprehensive test suite in `tests/unit/test_qwen_oauth_reasoning_effort.py`:
- ✅ Test reasoning_effort="medium" appends " /think"
- ✅ Test reasoning_effort="high" appends " /think"
- ✅ Test reasoning_effort="low" does NOT append
- ✅ Test no reasoning_effort does NOT append
- ✅ Test skips tool response messages
- ✅ Test works with system messages
- ✅ Test works with multiple messages (only last user message modified)
- ✅ Test works with Pydantic ChatMessage objects

All 132 qwen-related tests pass, including the 8 new tests.

## Behavior
- **reasoning_effort="low"**: No modification (standard behavior)
- **reasoning_effort="medium"**: Appends " /think" to last client message
- **reasoning_effort="high"**: Appends " /think" to last client message
- **No reasoning_effort**: No modification (standard behavior)

## Notes
- The " /think" suffix is only appended to regular messages, not tool call responses
- The modification happens before the message is sent to the Qwen API
- This feature is specific to the Qwen OAuth connector and leverages Qwen's native reasoning capabilities
