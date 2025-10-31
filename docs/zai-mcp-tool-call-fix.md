# ZAI Coding Plan MCP Tool Call Fix

## Problem

When using the `zai-coding-plan` backend with Cline-fork agents (like KiloCode), MCP tool calls were being rendered as text in message bodies instead of being recognized as proper tool calls. This caused the backend to send XML-formatted tool invocations in the message content rather than as structured `tool_calls` in the OpenAI API format.

### Example of the Issue

**Before Fix:**
```json
{
  "role": "assistant",
  "content": "I will patch the file.\n\n<use_mcp_tool tool_name=\"patch_file\"><path>test.py</path><content>new content</content></use_mcp_tool>"
}
```

The XML tool invocation was sent as plain text, which the backend couldn't recognize as a tool call.

**After Fix:**
```json
{
  "role": "assistant",
  "content": "I will patch the file.",
  "tool_calls": [
    {
      "id": "call_abc123",
      "type": "function",
      "function": {
        "name": "patch_file",
        "arguments": "{\"path\": \"test.py\", \"content\": \"new content\"}"
      }
    }
  ]
}
```

The XML is extracted and converted to proper OpenAI-style tool calls.

## Root Cause

The `zai-coding-plan` backend inherits from `OpenAIConnector`, which doesn't have the Codex-specific logic to parse XML-formatted tool invocations from message content. The `ToolCallCommandProcessor` only handles textual tool **results** (responses), not textual tool **invocations** (calls).

## Solution

Added a new method `_extract_mcp_tool_calls_from_messages()` to the `ZaiCodingPlanBackend` class that:

1. **Scans assistant messages** for XML-formatted MCP tool invocations
2. **Extracts tool calls** using regex pattern matching
3. **Converts to OpenAI format** with proper `tool_calls` structure
4. **Removes XML from content** to avoid duplication
5. **Preserves remaining text** in the message content

### Implementation Details

The fix is applied in the `_prepare_payload()` method before the payload is sent to the backend:

```python
def _extract_mcp_tool_calls_from_messages(self, messages: list[Any]) -> list[Any]:
    """Extract MCP tool calls from message content and convert to tool_calls format."""
    # Pattern: <use_mcp_tool tool_name="...">...</use_mcp_tool>
    mcp_pattern = re.compile(
        r'<use_mcp_tool\s+tool_name="([^"]+)"[^>]*>(.*?)</use_mcp_tool>',
        re.DOTALL,
    )
    
    # For each assistant message:
    # 1. Find all MCP tool invocations
    # 2. Extract tool name and arguments from nested XML tags
    # 3. Create OpenAI-style tool_calls
    # 4. Remove XML from content
    # 5. Preserve any remaining text
```

### Key Features

- **Non-invasive**: Only processes assistant messages with XML content
- **Preserves existing tool_calls**: Doesn't overwrite if already present
- **Handles multiple tools**: Can extract multiple tool calls from one message
- **Preserves context**: Keeps non-XML text in the message content
- **Structured arguments**: Parses nested XML tags into JSON arguments

## Testing

Created comprehensive unit tests in `tests/unit/test_zai_mcp_tool_extraction.py`:

- ✅ Single MCP tool call extraction
- ✅ Multiple MCP tool calls in one message
- ✅ Preservation of non-assistant messages
- ✅ Preservation of existing tool_calls
- ✅ Messages without MCP tools unchanged
- ✅ Remaining content preserved after extraction
- ✅ Empty content handling
- ✅ Complex nested arguments

All tests pass, and existing backend tests remain unaffected.

## Impact

This fix enables Cline-fork agents (like KiloCode) to properly use MCP tools through the `zai-coding-plan` backend. The tool calls are now recognized by the coding agent and executed correctly, rather than being rendered as text in message bodies.

## Future Considerations

1. **Generalization**: This pattern could be extracted into a reusable middleware for other OpenAI-compatible backends that need to support Cline-style XML tool invocations.

2. **Performance**: The regex-based extraction is efficient for typical message sizes, but could be optimized further if needed for very large messages.

3. **Error Handling**: Currently assumes well-formed XML. Could add validation and error recovery for malformed tool invocations.

4. **Tool Schema Validation**: Could validate extracted tool calls against the available tool schemas before sending to the backend.
