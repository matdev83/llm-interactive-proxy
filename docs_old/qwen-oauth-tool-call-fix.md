# Qwen OAuth Tool Call Compatibility Fix

## Problem

The qwen-oauth backend was not properly compatible with KiloCode's tool call expectations. Tool calls were being displayed as plain text in the KiloCode UI instead of being recognized and executed as actual tool invocations.

## Root Cause Analysis

After thorough investigation comparing wire captures from both qwen-oauth and gemini-oauth-plan backends, the issue was identified:

### How Gemini-OAuth-Plan Works (Correctly)
- Sends complete tool calls as XML in a **single chunk**
- Each tool call chunk has `finish_reason: "STOP"` (uppercase)
- Example:
  ```json
  {
    "delta": {
      "content": "<read_file>\n<args>\n  <file>\n    <path>test.py</path>\n  </file>\n</args>\n</read_file>"
    },
    "finish_reason": "STOP"
  }
  ```

### How Qwen-OAuth Was Working (Incorrectly)
- Streams tool calls across **multiple chunks**
- Each chunk has `finish_reason: null` during streaming
- Final chunk has `finish_reason: "stop"` (lowercase)
- Example:
  ```json
  // Chunk 1
  {"delta": {"content": "<read"}, "finish_reason": null}
  // Chunk 2
  {"delta": {"content": "_file>\n<"}, "finish_reason": null}
  // Chunk 3
  {"delta": {"content": "args>..."}, "finish_reason": null}
  // ... more chunks ...
  ```

**KiloCode expects tool calls to be sent as complete XML blocks in a single chunk with `finish_reason="STOP"`**, similar to how gemini-oauth-plan works.

## Solution

Modified the `_handle_streaming_response` method in `src/connectors/qwen_oauth.py` to:

1. **Detect Tool Call Start**: Recognize when a tool call begins by detecting opening tags like `<read_file>`, `<write_to_file>`, etc.
   - Handles both complete tags and partial tags (e.g., `<read` at the start of a chunk)

2. **Buffer Tool Call Content**: Accumulate all chunks that are part of the tool call into a buffer

3. **Detect Tool Call End**: Recognize when the tool call is complete by detecting the closing tag (e.g., `</read_file>`)

4. **Send Complete Tool Call**: Once complete, send the entire tool call as a single chunk with `finish_reason="STOP"`

5. **Maintain Deduplication**: Continue to deduplicate chunks to handle the Qwen API bug where duplicate chunks are sometimes sent

## Supported Tool Tags

The fix recognizes the following KiloCode tool tags:
- `read_file`
- `list_files`
- `write_to_file`
- `search_files`
- `execute_command`
- `list_code_definition_names`
- `search_symbol`
- `grep_search`
- `file_search`
- `use_mcp_tool`
- `patch_file`
- `attempt_completion`
- `ask_followup_question`

## Testing

Comprehensive unit tests were added in `tests/unit/connectors/test_qwen_oauth_tool_call_buffering.py`:

1. **test_tool_call_buffering_combines_chunks**: Verifies that tool calls streamed across multiple chunks are combined into one
2. **test_non_tool_call_chunks_pass_through**: Ensures regular text chunks pass through without buffering
3. **test_multiple_tool_calls_buffered_separately**: Tests that multiple tool calls in sequence are each buffered separately
4. **test_deduplication_still_works**: Confirms that chunk deduplication still works alongside tool call buffering

All tests pass successfully.

## Impact

This fix ensures that:
- Tool calls from qwen-oauth are properly recognized by KiloCode
- Tool execution happens automatically instead of displaying XML as text
- The user experience with qwen-oauth matches that of gemini-oauth-plan
- Existing deduplication functionality continues to work

## Files Modified

- `src/connectors/qwen_oauth.py`: Added tool call buffering logic to `_handle_streaming_response` method
- `tests/unit/connectors/test_qwen_oauth_tool_call_buffering.py`: Added comprehensive test coverage

## Future Considerations

If additional tool tags are added to KiloCode, they should be added to the `tool_tags` list in the `_handle_streaming_response` method to ensure they are properly buffered.
