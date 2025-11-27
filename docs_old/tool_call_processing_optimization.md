# Tool Call Processing Optimization

## Overview

The tool call processing optimization prevents re-processing of historical tool calls in conversation histories, significantly improving performance when dealing with long conversations (70+ messages).

## Problem Statement

Prior to this optimization, the system would re-process ALL historical tool calls on every request, causing:

1. **Performance Issues**: Processing 70+ messages with tool calls on every request
2. **Excessive Logging**: Multiple repeated log messages (25+ per request) about "Extracted MCP tool calls"
3. **Potential Side Effects**: Tool call repairs, loop detection, and event-driven reactors triggering on historical data
4. **Wasted Resources**: Re-parsing and re-validating tool calls that were already processed in previous turns

## Solution

The system now tracks which messages have been processed using a lightweight marker mechanism. Historical messages are efficiently skipped, and only new tool calls from the current LLM response are processed.

## Configuration Options

### `force_reprocess_tool_calls`

Controls whether to bypass the processing marker checks and force reprocessing of all tool calls.

**Default**: `false` (recommended for production)

**When to set to `true`**:
- Debugging tool call processing issues
- Testing changes to tool call repair logic
- Investigating unexpected behavior in tool call handling
- Reproducing issues that may be related to the optimization

**Impact**: Enabling this will reduce performance with long conversation histories, as all historical messages will be reprocessed on every request.

**Configuration Examples**:

CLI:
```bash
python -m src.core.cli --force-reprocess-tool-calls
```

Environment Variable:
```bash
export FORCE_REPROCESS_TOOL_CALLS=true
```

YAML (`config/config.yaml`):
```yaml
session:
  force_reprocess_tool_calls: true
```

### `log_skipped_tool_calls`

Controls visibility of skipped message logging.

**Default**: `false` (recommended for production to reduce log noise)

**When to set to `true`**:
- Understanding which messages are being optimized
- Verifying the optimization is working correctly
- Development and debugging of the processing system
- Investigating performance improvements

**Impact**: Logs are emitted at TRACE level (level 5) to minimize noise. You'll need to set your logging level to TRACE to see these messages.

**Configuration Examples**:

CLI:
```bash
python -m src.core.cli --log-skipped-tool-calls
```

Environment Variable:
```bash
export LOG_SKIPPED_TOOL_CALLS=true
```

YAML (`config/config.yaml`):
```yaml
session:
  log_skipped_tool_calls: true
```

## How It Works

### Message Processing Markers

The system uses a lightweight marker (`_tool_calls_processed`) added to message metadata after processing. This marker:

- Does not modify the core message structure
- Is request-scoped (not persisted across sessions)
- Works with both dict and object message formats
- Is checked before any tool call processing occurs

### Hybrid Approach

The system uses a hybrid approach for maximum robustness:

1. **Primary**: Check for `_tool_calls_processed` marker
2. **Fallback**: If no marker exists, only process the last assistant message
3. **Safety**: Configuration flag to force reprocessing if needed

### Processing Flow

```
Request with conversation history
    ↓
For each message:
    ↓
    Check if message has _tool_calls_processed marker
    ↓
    ├─ Yes → Skip processing, pass through unchanged
    │
    └─ No → Is this the last assistant message?
            ↓
            ├─ Yes → Process tool calls, add marker
            │
            └─ No → Skip processing (historical message)
```

## Performance Impact

With a conversation history of 70+ messages:

- **Before optimization**: All 70+ messages processed on every request
- **After optimization**: Only 1 message (the latest) processed on every request
- **Performance improvement**: >90% reduction in tool call processing time

## Affected Components

The optimization is applied consistently across all tool call processing components:

1. **ZAI Coding Plan Connector** (`src/connectors/zai_coding_plan.py`)
   - `_extract_mcp_tool_calls_from_messages()` method

2. **Tool Call Repair Service** (`src/core/services/tool_call_repair_service.py`)
   - `repair_tool_calls()` and `repair_tool_calls_in_messages()` methods

3. **Tool Call Reactor Middleware** (`src/core/services/tool_call_reactor_middleware.py`)
   - Filters tool calls before reactor execution

4. **Tool Call Loop Detection Middleware** (`src/core/services/tool_call_loop_middleware.py`)
   - Only tracks new tool calls for loop detection

5. **Streaming Tool Call Repair Processor** (`src/core/services/streaming_tool_call_repair_processor.py`)
   - Skips repair for already-processed streaming chunks

## Troubleshooting

### Issue: Tool calls not being processed

**Symptoms**: New tool calls from the LLM are not being repaired or processed.

**Possible Causes**:
1. The message is incorrectly marked as processed
2. The last-message detection is failing

**Solutions**:
1. Enable `force_reprocess_tool_calls` temporarily to bypass the optimization
2. Enable `log_skipped_tool_calls` to see which messages are being skipped
3. Check logs for any errors in message processing utilities

### Issue: Performance hasn't improved

**Symptoms**: Request processing time is still high with long conversation histories.

**Possible Causes**:
1. `force_reprocess_tool_calls` is enabled
2. Other bottlenecks in the request processing pipeline
3. The optimization is not being applied to all components

**Solutions**:
1. Verify `force_reprocess_tool_calls` is set to `false`
2. Enable `log_skipped_tool_calls` to confirm messages are being skipped
3. Profile the request to identify other bottlenecks

### Issue: Excessive log messages

**Symptoms**: Still seeing repeated "Extracted tool calls" messages in logs.

**Possible Causes**:
1. `log_skipped_tool_calls` is enabled
2. Logging level is set to TRACE
3. The optimization is not working correctly

**Solutions**:
1. Set `log_skipped_tool_calls` to `false`
2. Increase logging level to INFO or higher
3. Verify the optimization is working by checking for processing markers

## Best Practices

1. **Production**: Keep both options at their default values (`false`) for optimal performance and minimal log noise

2. **Development**: Enable `log_skipped_tool_calls` during development to verify the optimization is working

3. **Debugging**: Enable `force_reprocess_tool_calls` only when specifically debugging tool call processing issues

4. **Testing**: When testing changes to tool call processing logic, enable `force_reprocess_tool_calls` to ensure all code paths are exercised

5. **Monitoring**: Monitor request processing times to verify the optimization is providing the expected performance improvements

## Related Documentation

- [Tool Call Repair Service](../src/core/services/tool_call_repair_service.py)
- [Tool Call Reactor Middleware](../src/core/services/tool_call_reactor_middleware.py)
- [Tool Call Loop Detection](../src/core/services/tool_call_loop_middleware.py)
- [Message Processing Utilities](../src/core/utils/message_processing_utils.py)

## Changelog

### Version 1.0 (Initial Release)
- Added message processing markers
- Implemented hybrid approach (marker + last-message fallback)
- Added configuration options for debugging
- Applied optimization across all tool call processing components
- Achieved >90% reduction in processing time for long conversations
