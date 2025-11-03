# Gemini Function Call/Response Matching Fix

## Problem

The Droid/Factory client using `gemini-oauth-plan` backend was experiencing errors:

```
Error: API error: {'error': {'code': 400, 'message': 'Please ensure that the number of function response parts is equal to the number of function call parts of the function call turn.', 'status': 'INVALID_ARGUMENT'}}
```

## Root Cause

The Gemini API has strict requirements for function calling:

1. **Function call messages must NOT contain text content**: When an assistant message includes `functionCall` parts, it should NOT have any `text` parts in the same message.

2. **Function responses must be grouped**: All `functionResponse` parts must be in a single "user" role message, with the count matching the number of `functionCall` parts from the previous assistant message.

The proxy's translation layer was violating both rules:

### Issue 1: Mixed Content in Assistant Messages
When converting OpenAI-format messages to Gemini format, the code was adding BOTH `functionCall` parts AND `text` parts to the same assistant message:

```python
# BEFORE (incorrect):
# Assistant message with tool_calls
parts.append({"functionCall": {...}})  # Tool call
parts.append({"text": "Let me check..."})  # Text content - WRONG!
```

### Issue 2: Separate Tool Response Messages
Each tool response was creating a separate "user" message instead of grouping them:

```python
# BEFORE (incorrect):
# Message 1: {"role": "user", "parts": [{"functionResponse": {...}}]}
# Message 2: {"role": "user", "parts": [{"functionResponse": {...}}]}
# This creates 2 separate messages with 1 response each
```

## Solution

### Fix 1: Exclude Text Content from Tool Call Messages
Modified `src/core/domain/translation.py` to skip text content when an assistant message has tool calls:

```python
# AFTER (correct):
has_tool_calls = message.role == "assistant" and getattr(message, "tool_calls", None)
if has_tool_calls:
    # Add functionCall parts only
    parts.append({"functionCall": {...}})

# Only add text content if there are NO tool calls
if not has_tool_calls:
    if isinstance(message.content, str):
        parts.append({"text": message.content})
```

### Fix 2: Group Consecutive Tool Responses
Modified the message processing loop to collect all consecutive tool messages and combine them into a single "user" message:

```python
# AFTER (correct):
if message.role == "tool":
    # Collect ALL consecutive tool messages
    tool_messages = [message]
    j = i + 1
    while j < len(request.messages) and request.messages[j].role == "tool":
        tool_messages.append(request.messages[j])
        j += 1
    
    # Add all as functionResponse parts in ONE message
    for tool_msg in tool_messages:
        parts.append({"functionResponse": {...}})
```

## Result

Now the proxy correctly formats function calling conversations for Gemini:

```
Turn 1 (user):     {"role": "user", "parts": [{"text": "What's the weather?"}]}
Turn 2 (model):    {"role": "model", "parts": [{"functionCall": {...}}]}  # No text!
Turn 3 (user):     {"role": "user", "parts": [{"functionResponse": {...}}, {"functionResponse": {...}}]}  # Grouped!
Turn 4 (model):    {"role": "model", "parts": [{"text": "The weather is..."}]}
```

## Testing

Created comprehensive tests in `tests/unit/core/domain/test_gemini_function_call_fix.py`:

- ✅ Assistant messages with tool_calls exclude text content
- ✅ Multiple tool responses are grouped in a single message
- ✅ Single tool call/response works correctly
- ✅ Regular assistant messages (without tool calls) still include text

All existing tests continue to pass, confirming backward compatibility.

## Impact

This fix resolves the Gemini API error for clients like Droid/Factory that use function calling with the `gemini-oauth-plan` backend. The fix is applied at the translation layer, so it benefits all Gemini backends:

- `gemini-oauth-plan`
- `gemini-oauth-free`
- `gemini-cli-acp`
- `gemini-cloud-project`
