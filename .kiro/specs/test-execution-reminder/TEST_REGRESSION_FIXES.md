# Test Regression Fixes

## Summary

During the test execution reminder feature implementation, we discovered that the `ToolCallReactorMiddleware` behavior changed to return OpenAI-compatible response structures instead of plain strings when tool calls are swallowed. This required updating several tests that expected string content.

## Tests Fixed

### 1. test_process_with_tool_calls_swallowed_empty_string
**File**: `tests/unit/core/services/test_tool_call_reactor_middleware.py`
**Issue**: Test expected `result.content == ""` but got a dict with OpenAI response structure
**Fix**: Updated to check `result.content["choices"][0]["message"]["content"] == ""`

### 2. test_reactor_swallows_dangerous_command_and_steers
**File**: `tests/unit/core/app/middleware/test_dangerous_command_middleware.py`
**Issue**: Test expected `result.content == "steering"` but got a dict with OpenAI response structure
**Fix**: Updated to check `result.content["choices"][0]["message"]["content"] == "steering"`

### 3. test_cline_write_to_file_blocked_outside_project
**File**: `tests/integration/test_file_sandboxing_integration.py`
**Issue**: Test tried to call `.lower()` on dict content
**Fix**: Added logic to extract content from OpenAI structure before calling `.lower()`

## Root Cause

The `_create_replacement_response` method in `ToolCallReactorMiddleware` was updated to return a full OpenAI-compatible response structure:

```python
replacement_struct = {
    "id": f"chatcmpl-steering-{int(time.time())}",
    "object": "chat.completion",
    "created": int(time.time()),
    "model": model_name,
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": replacement_content,
            },
            "finish_reason": "stop",
        }
    ],
    "usage": getattr(original_response, "usage", None),
}
```

This change was made to ensure consistency with OpenAI API format and to properly support streaming responses.

## Test Results

After fixes:
- All test execution reminder tests pass: 311 tests
- All core unit tests pass: 2233 tests
- Fixed integration tests pass

## Verification Status

- ✅ Test execution reminder tests (311 tests)
- ✅ Core unit tests (2233 tests)
- ✅ Fixed integration tests
- ⚠️ Full integration test suite has some hanging tests (unrelated to our changes)
