# Claude Tool Call ID Fix for Gemini OAuth Antigravity Backend

## Problem

When using the `gemini-oauth-antigravity` backend with Claude models (e.g., `claude-sonnet-4-5`), the second tool call was failing with the error:

```
API Validation Error:
{"type":"error","error":{"type":"invalid_request_error","message":"messages.1.content.0.tool_use.id: Field required"},"request_id":"req_vrtx_011CViStuZWTv3Td2BtwnSr9"}
```

### Root Cause Analysis

After extensive investigation and trial-and-error, the root cause was identified:

1. **First tool call works fine** - Claude makes a tool call, proxy handles it correctly
2. **Second request fails** - When client sends back the assistant message (containing the original tool call) + tool result
3. **The tool call ID is lost during translation**

The flow is:
1. Client sends OpenAI format: `tool_calls` array with `id`, `function.name`, `function.arguments`
2. Proxy converts to canonical domain format (preserves IDs)
3. Translation service converts to Gemini format using `from_domain_to_gemini_request()`
4. **PROBLEM**: Gemini's `functionCall` structure only includes `name` and `args`, NOT the `id`
5. Antigravity receives Gemini format request
6. Antigravity internally converts to Anthropic format for Claude models
7. **FAILURE**: Anthropic's `tool_use` blocks require an `id` field, but it's not available in the Gemini format

The key insight: **The Antigravity API expects Gemini Code Assist format (with `contents`, `generationConfig`, etc.), NOT Anthropic format directly**. It handles the Anthropic conversion internally, but it needs the tool call IDs to be preserved in the Gemini format.

## Solution

Modified the Gemini translation layer to **preserve tool call IDs** in the `functionCall` structure.

### Changes in `src/core/domain/translation.py`

In the `from_domain_to_gemini_request()` method, added ID preservation when building functionCall parts (around line 2359):

```python
# Build the functionCall part
function_call_part: dict[str, Any] = {
    "functionCall": {"name": fn, "args": args_val}
}

# Preserve tool call ID if present (needed for Claude via Antigravity)
if "id" in tc_dict:
    function_call_part["functionCall"]["id"] = tc_dict["id"]
```

### How It Works

**Before the fix:**
```python
functionCall: {
    "name": "execute_command",
    "args": {"command": "git status"}
}
```

**After the fix:**
```python
functionCall: {
    "name": "execute_command",
    "args": {"command": "git status"},
    "id": "call_abc123"  # NOW PRESERVED!
}
```

When Antigravity receives this Gemini format and internally converts to Anthropic format for Claude, it can now extract the ID and include it in the `tool_use` block, satisfying Anthropic's API requirements.

## Why This Works

1. **Doesn't break Gemini models** - Standard Gemini API ignores unknown fields in functionCall
2. **Enables Antigravity's Claude support** - Antigravity can now extract IDs when converting to Anthropic format
3. **Minimal change** - Single small addition to the translation layer
4. **Universal fix** - Works for all backends that might need tool call IDs in the future

## Testing

The fix was developed through:
- Analysis of log files showing the API error
- CBOR wire capture inspection showing the missing IDs
- Understanding the translation flow from OpenAI → Gemini → Anthropic
- Trial and error with the Antigravity API format

## Scope and Safety

The fix is **safe and backward compatible**:
- Only adds an `id` field to `functionCall` when it exists in the source
- Gemini API ignores extra fields, so no impact on pure Gemini models
- Enables Claude support via Antigravity without special-casing
- No changes to connector-specific code

## Files Modified

- `src/core/domain/translation.py`: Added tool call ID preservation in `from_domain_to_gemini_request()` method (lines 2363-2365)

## Next Steps

Test with the same scenario:
- Backend: `gemini-oauth-antigravity`
- Model: `claude-sonnet-4-5`
- Test flow: Make a tool call, then send back the tool result
- Expected: Second tool call should now work without the "Field required" error
