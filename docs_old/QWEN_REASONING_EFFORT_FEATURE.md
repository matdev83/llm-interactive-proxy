# Qwen OAuth Reasoning Effort Feature

## Overview
Enhanced the Qwen OAuth connector to automatically append " /think" to messages to trigger Qwen's extended reasoning mode by default. The suffix is only skipped when reasoning effort is explicitly set to "low".

## Implementation Details

### Changes Made
1. **Modified `src/connectors/qwen_oauth.py`**:
   - Updated `chat_completions()` method to detect `reasoning_effort` parameter
   - **By default**, appends " /think" to the last client message
   - Only skips appending when `reasoning_effort` is explicitly set to "low"
   - Only appends to user or system messages, not tool responses
   - Handles both Pydantic models and dict message formats

### How It Works
- The connector checks if `reasoning_effort` is explicitly set to "low"
- If NOT "low" (including None, empty string, or any other value), it appends " /think"
- It finds the last client message (user or system role, skipping tool responses)
- Appends " /think" to the content of that message
- This triggers Qwen's extended reasoning mode for more thoughtful responses

### Usage Examples

**Default behavior (appends " /think"):**
```python
request = ChatRequest(
    model="qwen-turbo",
    messages=[
        ChatMessage(role="user", content="What is 2+2?")
    ]
    # No reasoning_effort specified - will append " /think"
)
```
Result: "What is 2+2? /think"

**Explicitly disable reasoning mode:**
```python
request = ChatRequest(
    model="qwen-turbo",
    messages=[
        ChatMessage(role="user", content="Simple question")
    ],
    reasoning_effort="low"  # Only "low" prevents appending
)
```
Result: "Simple question" (no modification)

**Explicit reasoning modes (also append):**
```python
request = ChatRequest(
    model="qwen-turbo",
    messages=[
        ChatMessage(role="user", content="Complex problem")
    ],
    reasoning_effort="high"  # or "medium"
)
```
Result: "Complex problem /think"

### Test Coverage
Created comprehensive test suite in `tests/unit/test_qwen_oauth_reasoning_effort.py`:
- ✅ Test default (no reasoning_effort) appends " /think"
- ✅ Test reasoning_effort="medium" appends " /think"
- ✅ Test reasoning_effort="high" appends " /think"
- ✅ Test reasoning_effort="low" does NOT append
- ✅ Test reasoning_effort=None appends " /think"
- ✅ Test reasoning_effort="" (empty string) appends " /think"
- ✅ Test skips tool response messages
- ✅ Test works with system messages
- ✅ Test works with multiple messages (only last user message modified)
- ✅ Test works with Pydantic ChatMessage objects

All qwen-related tests pass, including the 10 new tests.

## Behavior Summary
- **Default (no reasoning_effort)**: Appends " /think" ✅
- **reasoning_effort=None**: Appends " /think" ✅
- **reasoning_effort=""**: Appends " /think" ✅
- **reasoning_effort="low"**: Does NOT append ❌
- **reasoning_effort="medium"**: Appends " /think" ✅
- **reasoning_effort="high"**: Appends " /think" ✅
- **Any other value**: Appends " /think" ✅

## Notes
- The " /think" suffix is only appended to regular messages, not tool call responses
- The modification happens before the message is sent to the Qwen API
- This feature is specific to the Qwen OAuth connector and leverages Qwen's native reasoning capabilities
- The default behavior enables extended reasoning for better response quality
- Users can opt-out by explicitly setting `reasoning_effort="low"`
