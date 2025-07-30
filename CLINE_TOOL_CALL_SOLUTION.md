# Cline Tool Call Support for Gemini CLI Batch Backend

## Problem

When Cline coding agent connects to the proxy server and gets served by the `google-cli-batch` backend, tool calls fail because:

1. **Incompatible Response Format**: The gemini-cli-batch backend returns raw text responses, but Cline expects structured tool call responses
2. **Missing Tool Call Conversion**: Cline tool calls are converted to markers for local processing, but the batch backend doesn't convert them back to proper tool call format
3. **Agent Detection**: The backend doesn't properly detect Cline agents and handle their specific response requirements

## Solution

Modified the `GeminiCliBatchConnector` to detect Cline agents and convert responses back to proper tool call format.

### Key Changes

1. **Import Required Functions**: Added import for `convert_cline_marker_to_openai_tool_call` in `src/connectors/gemini_cli_batch.py`

2. **Response Post-Processing**: Modified the `chat_completions` method to detect Cline agents and convert responses:
   - Check if agent is "cline" or "roocode"
   - Check if response contains Cline marker format
   - Convert markers back to proper OpenAI tool call format
   - Set appropriate `finish_reason="tool_calls"`

### How It Works

1. **Cline Sends Tool Call**: Cline sends structured tool calls to the proxy
2. **Proxy Processing**: Proxy converts tool calls to Cline markers for local command processing
3. **Batch Backend Execution**: gemini-cli-batch executes the prompt and returns raw text
4. **Response Conversion**: Modified connector detects Cline agent and converts response back to tool call format
5. **Cline Receives Proper Format**: Cline gets structured tool call responses it expects

### Example Flow

```
Cline → Proxy: {"tool_calls": [...]}
Proxy → Backend: "__CLINE_TOOL_CALL_MARKER__..."
Backend → Proxy: "__CLINE_TOOL_CALL_MARKER__File created successfully__END_CLINE_TOOL_CALL_MARKER__"
Proxy → Cline: {"tool_calls": [{"function": {"name": "attempt_completion", "arguments": "..."}}, "finish_reason": "tool_calls"]}
```

## Testing

Created comprehensive tests in `tests/unit/gemini_connector_tests/test_cline_tool_call_handling.py`:

1. **Cline Tool Call Conversion**: Verifies proper conversion from markers to tool calls
2. **Non-Cline Agent Handling**: Ensures other agents are unaffected
3. **Streaming Response Handling**: Confirms streaming responses work correctly

## Benefits

- ✅ Enables Cline to work with gemini-cli-batch backend
- ✅ Maintains compatibility with other agents
- ✅ Preserves existing functionality
- ✅ Proper error handling and edge case management
- ✅ Comprehensive test coverage

## Usage

Cline can now successfully use tool calls with gemini-cli-batch backend. The proxy automatically handles the conversion between Cline's expected format and the backend's raw text output.