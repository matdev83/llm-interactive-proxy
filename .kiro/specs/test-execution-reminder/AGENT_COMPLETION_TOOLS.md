# Agent Completion Tools Reference

## Overview

This document catalogs the completion tools used by popular coding agents. The Test Execution Reminder system uses this information to reliably detect when agents signal task completion.

## Detection Methods

The system uses two complementary detection methods:

1. **Primary**: Actual completion tool names from agent source code
2. **Secondary**: Streaming `finish_reason` markers from LLM APIs

## Supported Agents

### Cline

**Source**: `dev/thrdparty/cline/src/shared/tools.ts`

**Completion Tool**: `attempt_completion`

**Tool Definition**:
```typescript
export enum ClineDefaultTool {
    ATTEMPT = "attempt_completion"
}
```

**Usage**: Required tool for task completion. Cline cannot complete a task without calling this tool.

**Detection**: Primary method (tool name matching)

**Status**: Fully supported

---

### Roo-Code (Kilo Code)

**Source**: `dev/thrdparty/Roo-Code/src/shared/tools.ts`

**Completion Tool**: `attempt_completion`

**Tool Definition**:
```typescript
interface AttemptCompletionToolUse {
    tool: "attempt_completion"
    result?: string
    command?: string
}
```

**Usage**: Required tool for task completion. Roo-Code uses the same tool interface as Cline.

**Detection**: Primary method (tool name matching)

**Status**: Fully supported

---

### OpenHands (formerly OpenDevin)

**Source**: Research from agent documentation and API specifications

**Completion Tool**: `finish`

**Tool Definition**: Standard completion tool in OpenHands agent framework

**Usage**: Signals task completion in OpenHands workflows

**Detection**: Primary method (tool name matching)

**Status**: Fully supported

---

### Generic Agents

**Completion Tools**: Various generic names

**Supported Tools**:
- `finish_task`
- `task_complete`
- `mark_complete`
- `complete`
- `done`

**Usage**: Generic completion tools that may be used by custom or less common agents

**Detection**: Primary method (tool name matching)

**Status**: Fully supported

---

### Agents Using finish_reason

**Agents**: Any agent using standard LLM APIs (OpenAI, Anthropic, etc.)

**Detection Method**: Secondary (streaming finish_reason markers)

**Supported finish_reason Values**:
- `stop`: Normal completion (OpenAI, Anthropic)
- `tool_calls`: Completed with tool calls (OpenAI)
- `length`: Maximum token limit reached (OpenAI, Anthropic)
- `end_turn`: Anthropic's completion marker

**Usage**: Fallback detection for agents that don't use explicit completion tools

**Status**: Fully supported

## Detection Logic

The `CompletionSignalDetector` checks for completion signals in this order:

1. **Check tool name** against `COMPLETION_TOOLS` set
   - Performs case-insensitive matching
   - Normalizes underscores and hyphens
   - Returns `True` if match found

2. **Check finish_reason** against `FINISH_REASONS` set
   - Extracts from streaming response
   - Checks metadata dictionary
   - Returns `True` if match found

3. **Return False** if no completion signal detected

## Adding New Agents

To add support for a new agent's completion tool:

1. **Research**: Examine the agent's source code to find the completion tool name
2. **Add to COMPLETION_TOOLS**: Update the set in `CompletionSignalDetector`
3. **Test**: Verify detection works with the new tool name
4. **Document**: Add entry to this document

Example:
```python
# In src/services/test_execution_reminder/completion_signal_detector.py
COMPLETION_TOOLS = {
    "attempt_completion",  # Cline, Roo-Code
    "finish",              # OpenHands
    "your_new_tool",       # Your Agent
    # ... other tools
}
```

## Research Sources

### Analyzed Agents

1. **Cline**: `dev/thrdparty/cline/`
   - File: `src/shared/tools.ts`
   - Tool: `attempt_completion`
   - Status: Confirmed

2. **Roo-Code**: `dev/thrdparty/Roo-Code/`
   - File: `src/shared/tools.ts`
   - Tool: `attempt_completion`
   - Status: Confirmed

3. **OpenHands**: Documentation and API research
   - Tool: `finish`
   - Status: Confirmed

### Agents To Research

The following agents have not yet been analyzed for completion tools:

- **Aider**: Popular AI pair programming tool
- **Cursor**: AI-powered code editor
- **Codex**: OpenAI's code generation system
- **Gemini CLI**: Google's command-line coding assistant
- **OpenCode**: Open-source coding agent
- **Crush**: AI coding assistant

If you have access to these agents' source code, please contribute completion tool information.

## API Specifications

### OpenAI finish_reason Values

From [OpenAI API Documentation](https://platform.openai.com/docs/api-reference/chat/object):

- `stop`: Natural stop point or provided stop sequence
- `length`: Maximum token limit reached
- `tool_calls`: Model called a tool
- `content_filter`: Content filtered by moderation

### Anthropic stop_reason Values

From [Anthropic API Documentation](https://docs.anthropic.com/claude/reference/messages_post):

- `end_turn`: Natural completion
- `max_tokens`: Maximum token limit reached
- `stop_sequence`: Custom stop sequence reached
- `tool_use`: Model used a tool

## Testing

All completion tools are tested in:

- **Unit Tests**: `tests/unit/services/test_execution_reminder/test_completion_signal_detector.py`
- **Property Tests**: `tests/property/test_completion_signal_detection_properties.py`
- **Integration Tests**: `tests/integration/test_test_execution_reminder_integration.py`

Each test verifies:
1. Tool name detection (case-insensitive, normalized)
2. finish_reason detection (from response and metadata)
3. Combined detection (tool name + finish_reason)
4. Edge cases (empty strings, None values, etc.)

## Version History

### Phase 2 (December 2025)

- **Added**: Evidence-based detection using actual agent tool names
- **Added**: Streaming finish_reason detection
- **Removed**: Unreliable pattern matching against model output
- **Added**: Support for Cline, Roo-Code, OpenHands
- **Added**: Generic completion tools

### Phase 1 (December 2025)

- **Initial**: Pattern matching against model output (deprecated)
- **Initial**: Generic completion tool names

## Contributing

To contribute completion tool information:

1. **Find the agent's source code**: Look for tool definitions
2. **Identify the completion tool**: Find the tool name used for task completion
3. **Test the tool name**: Verify it works with the detector
4. **Update this document**: Add the agent to the "Supported Agents" section
5. **Update the code**: Add the tool name to `COMPLETION_TOOLS` if needed
6. **Submit a pull request**: Include tests for the new tool

## References

- **Cline Source**: `dev/thrdparty/cline/`
- **Roo-Code Source**: `dev/thrdparty/Roo-Code/`
- **OpenAI API Docs**: https://platform.openai.com/docs/api-reference/chat/object
- **Anthropic API Docs**: https://docs.anthropic.com/claude/reference/messages_post
- **Phase 2 Improvements**: `.kiro/specs/test-execution-reminder/PHASE2_IMPROVEMENTS.md`
- **Design Document**: `.kiro/specs/test-execution-reminder/design.md`

## License

This documentation is part of the LLM Interactive Proxy project and follows the same license.
