# Tool Call Loop Detection

This document provides detailed information about the tool call loop detection system in the LLM Interactive Proxy. It covers the problem of tool call loops, the detection algorithm, configuration options, and best practices for tuning the system.

## Table of Contents

1. [Introduction](#introduction)
2. [The Problem of Tool Call Loops](#the-problem-of-tool-call-loops)
3. [Detection Mechanism](#detection-mechanism)
4. [Configuration Options](#configuration-options)
5. [Detection Modes](#detection-modes)
6. [Session-Level Configuration](#session-level-configuration)
7. [Interactive Mitigation](#interactive-mitigation)
8. [Advanced Configuration](#advanced-configuration)
9. [Logging and Monitoring](#logging-and-monitoring)
10. [Recommendations and Best Practices](#recommendations-and-best-practices)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)
13. [Performance Considerations](#performance-considerations)
14. [Related Features](#related-features)

## Introduction

Tool call loop detection is a safety feature that identifies and mitigates repetitive tool calls in LLM responses. It prevents infinite loops where an LLM repeatedly calls the same tool with similar parameters, resulting in resource waste and poor user experience.

The system tracks tool calls, detects patterns, and can take various actions when loops are detected, from simple warnings to blocking the tool calls and providing guidance for the LLM to recover.

## The Problem of Tool Call Loops

Tool call loops occur when an LLM gets stuck in a pattern of calling the same tool repeatedly, often with identical or very similar parameters. This can happen for several reasons:

1. **Incorrect Tool Understanding**: The LLM misunderstands the tool's purpose or parameters
2. **Hallucinated Errors**: The LLM believes a tool call failed when it didn't
3. **Lack of Progress**: The tool call works but doesn't advance toward solving the problem
4. **Instruction Confusion**: The LLM misinterprets instructions after a tool call
5. **Context Window Limitations**: The LLM forgets previous tool calls due to context limitations

Without intervention, these loops can continue indefinitely, consuming resources, generating large bills, and creating a poor user experience.

### Common Loop Patterns

Some typical patterns include:

1. **Identical Tool Calls**: Same tool with identical parameters
   ```json
   {"name": "get_weather", "arguments": {"location": "New York"}}
   {"name": "get_weather", "arguments": {"location": "New York"}}
   ```

2. **Slight Parameter Variations**: Same tool with minor parameter changes
   ```json
   {"name": "search", "arguments": {"query": "population of France 2023"}}
   {"name": "search", "arguments": {"query": "France population 2023"}}
   ```

3. **Error Recovery Loops**: Attempting to recover from errors
   ```json
   {"name": "read_file", "arguments": {"path": "/tmp/data.csv"}}
   {"name": "read_file", "arguments": {"path": "data.csv"}}
   {"name": "read_file", "arguments": {"path": "./data.csv"}}
   ```

## Detection Mechanism

The tool call loop detection system works as follows:

1. **Tool Call Tracking**: Each tool call is recorded with its name, arguments, and timestamp
2. **Similarity Comparison**: When a new tool call occurs, it's compared with previous calls
3. **Hashing**: Tool calls are hashed for efficient comparison
4. **Time Window**: Only tool calls within a configurable time window are considered
5. **Action Determination**: Based on the detection mode, an action is taken

### Tool Call Comparison

Tool calls are considered similar if:

1. The tool name is identical
2. The arguments are identical or very similar (based on string similarity)

For argument similarity, the system:
1. Normalizes the JSON representation
2. Computes a similarity score using Levenshtein distance
3. Compares against a configurable threshold

## Configuration Options

Tool call loop detection is highly configurable, with options at both the global and session levels.

### Global Configuration

Global configuration is set in the configuration file:

```yaml
# config.yaml
tool_call_loop:
  enabled: true
  max_repeats: 3
  ttl_seconds: 300
  mode: "block"  # Options: block, warn, chance_then_block
  similarity_threshold: 0.9  # 0.0-1.0, higher means more similar
```

### Key Configuration Parameters

| Parameter | Description | Default | Recommended Range |
|-----------|-------------|---------|------------------|
| `enabled` | Enable/disable tool call loop detection | `true` | `true` or `false` |
| `max_repeats` | Maximum number of similar tool calls before action | `3` | `2` to `5` |
| `ttl_seconds` | Time window for considering tool calls (seconds) | `300` | `60` to `600` |
| `mode` | Action mode when loop detected | `"block"` | `"block"`, `"warn"`, `"chance_then_block"` |
| `similarity_threshold` | Threshold for argument similarity (0.0-1.0) | `0.9` | `0.7` to `0.95` |

## Detection Modes

The system supports several detection modes that determine the action taken when a tool call loop is detected:

### Block Mode

In `block` mode, when a loop is detected:

1. The tool call is blocked immediately
2. An error message is returned in place of the tool call
3. The LLM must respond with a different approach

Example configuration:
```yaml
# config.yaml
tool_call_loop:
  mode: "block"
```

### Warn Mode

In `warn` mode, when a loop is detected:

1. The tool call is allowed to proceed
2. A warning message is logged
3. No intervention in the response

Example configuration:
```yaml
# config.yaml
tool_call_loop:
  mode: "warn"
```

### Chance Then Block Mode

In `chance_then_block` mode:

1. First detection: Warning is issued with guidance to the LLM
2. Second detection: Tool call is blocked
3. Interactive mitigation is attempted before blocking

Example configuration:
```yaml
# config.yaml
tool_call_loop:
  mode: "chance_then_block"
```

This mode is recommended for most use cases as it balances intervention with giving the LLM a chance to recover.

## Session-Level Configuration

Tool call loop detection can be configured at the session level using the `set` command. This allows different settings for different sessions.

```
!/set(tool_loop_detection_enabled=true)
!/set(tool_loop_max_repeats=4)
!/set(tool_loop_ttl_seconds=600)
!/set(tool_loop_mode="chance_then_block")
```

Session-level configuration overrides global configuration for that specific session.

## Interactive Mitigation

In `chance_then_block` mode, the system attempts interactive mitigation before blocking a tool call:

1. When a potential loop is detected, a warning and guidance message is injected
2. The message is appended to the conversation as an assistant message
3. The LLM is given one more chance to respond without the problematic tool call
4. If the same pattern continues, the tool call is then blocked

The guidance message contains:
- Information about the repeating pattern
- Suggestions for alternative approaches
- Encouragement to reflect on the current strategy

Example guidance message:
```
Tool call loop warning: The last tool invocation repeated the same function with identical parameters 3 times within the last 300 seconds.
Before invoking any tool again, pause and reflect on your plan.
- Verify that the tool name and parameters are correct and necessary.
- If the tool previously failed or produced no progress, adjust inputs or choose a different approach.
- Only call a tool if it is strictly required for the next step, otherwise continue with reasoning or a textual reply.
Tool you attempted: search_web with arguments: {"query": "population of France 2023"}.
Respond with either: (a) revised reasoning and a corrected single tool call with improved parameters; or (b) a textual explanation of the next steps without calling any tool.
```

## Advanced Configuration

### Custom Error Messages

You can customize the error messages returned when a tool call is blocked:

```yaml
# config.yaml
tool_call_loop:
  error_messages:
    block: "Tool call blocked due to repetitive pattern. Please try a different approach."
    warning: "Warning: This tool call pattern has been repeated multiple times."
```

### Per-Tool Configuration

You can configure different settings for specific tools:

```yaml
# config.yaml
tool_call_loop:
  per_tool:
    search_web:
      max_repeats: 2
    get_weather:
      max_repeats: 5
```

### Fine-tuning Similarity Detection

For advanced users, similarity detection can be fine-tuned:

```yaml
# config.yaml
tool_call_loop:
  similarity:
    algorithm: "levenshtein"  # Options: levenshtein, jaccard
    threshold: 0.9
    normalize_whitespace: true
    ignore_case: true
```

## Logging and Monitoring

Tool call loop detection events are logged for monitoring and debugging:

```
INFO - Tool call loop detection: Warning issued for tool 'search_web' - 3 similar calls in 120 seconds
WARNING - Tool call loop detection: Blocked tool 'search_web' - 4 similar calls in 150 seconds
```

### Log Levels

- `DEBUG`: Detailed information about all tool calls
- `INFO`: Information about warnings and interactive mitigation
- `WARNING`: Information about blocked tool calls
- `ERROR`: Errors in the detection system itself

### Metrics

The system tracks the following metrics:

- Number of tool calls processed
- Number of warnings issued
- Number of blocks applied
- Number of successful interactive mitigations

## Recommendations and Best Practices

### Recommended Configuration by Use Case

| Use Case | Mode | Max Repeats | TTL Seconds |
|----------|------|------------|-------------|
| General purpose | `chance_then_block` | 3 | 300 |
| Coding tools | `chance_then_block` | 4 | 600 |
| Search tools | `block` | 2 | 180 |
| API-calling tools | `block` | 3 | 300 |
| File operations | `chance_then_block` | 3 | 300 |

### Tuning Tips

1. **Start Conservative**: Begin with stricter settings (lower `max_repeats`)
2. **Monitor and Adjust**: Watch for false positives and adjust as needed
3. **Consider Tool Purpose**: Tools that are naturally repetitive may need higher thresholds
4. **Use Session-Level Settings**: Apply different configurations for different users or tasks

### User Experience Considerations

- Balance protection against disruption of legitimate tool usage
- Consider using `chance_then_block` mode for better user experience
- Provide clear error messages that guide the user and LLM to recovery

## Examples

### Configuration Examples

#### Strict Configuration (Security-Focused)

```yaml
# config.yaml
tool_call_loop:
  enabled: true
  max_repeats: 2
  ttl_seconds: 180
  mode: "block"
  similarity_threshold: 0.8
```

#### Lenient Configuration (User Experience-Focused)

```yaml
# config.yaml
tool_call_loop:
  enabled: true
  max_repeats: 4
  ttl_seconds: 600
  mode: "chance_then_block"
  similarity_threshold: 0.95
```

#### Development Configuration

```yaml
# config.yaml
tool_call_loop:
  enabled: true
  max_repeats: 5
  ttl_seconds: 300
  mode: "warn"
  similarity_threshold: 0.9
```

### Code Examples

#### Using Session-Level Configuration

```python
from src.core.domain.configuration.loop_detection_config import ToolCallLoopConfig, ToolLoopMode
from src.core.services.session_service import SessionService

# Get session
session = await session_service.get_session(session_id)

# Update configuration
session.state = session.state.with_tool_loop_config(
    ToolCallLoopConfig(
        enabled=True,
        max_repeats=4,
        ttl_seconds=300,
        mode=ToolLoopMode.CHANCE_THEN_BLOCK
    )
)

# Save session
await session_service.update_session(session)
```

#### Custom Tool Call Tracker

```python
from src.core.tool_call_loop.tracker import ToolCallTracker
from src.core.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode

# Create custom configuration
config = ToolCallLoopConfig(
    enabled=True,
    max_repeats=3,
    ttl_seconds=300,
    mode=ToolLoopMode.CHANCE_THEN_BLOCK
)

# Create tracker
tracker = ToolCallTracker(config)

# Track tool calls
should_block, reason, count = tracker.track_tool_call(
    "search_web",
    '{"query": "population of France 2023"}'
)

# Handle result
if should_block:
    print(f"Tool call blocked: {reason}")
else:
    print("Tool call allowed")
```

## Troubleshooting

### Common Issues

#### False Positives

**Symptoms**:
- Legitimate tool calls being blocked
- Tool calls with different purposes identified as loops

**Solutions**:
- Increase `similarity_threshold` (e.g., from 0.9 to 0.95)
- Increase `max_repeats` (e.g., from 3 to 4)
- Switch to `chance_then_block` mode to give the LLM a chance to recover

#### False Negatives

**Symptoms**:
- Clear loops not being detected
- Same tool called repeatedly without intervention

**Solutions**:
- Decrease `similarity_threshold` (e.g., from 0.9 to 0.8)
- Decrease `max_repeats` (e.g., from 3 to 2)
- Increase `ttl_seconds` to consider a longer history

#### Disrupted User Experience

**Symptoms**:
- Frequent interruptions in legitimate tool usage
- Users complaining about blocked tool calls

**Solutions**:
- Use `chance_then_block` mode instead of `block`
- Customize error messages to be more helpful
- Increase `max_repeats` for specific tools that are naturally repetitive

## Performance Considerations

The tool call loop detection system is designed to be lightweight and efficient:

- Tool calls are hashed for quick comparison
- Only calls within the TTL window are considered
- Memory usage is proportional to the number of tool calls within the TTL window

For most use cases, the performance impact is negligible. However, for very high-volume applications:

- Consider increasing `ttl_seconds` to reduce the history size
- Monitor memory usage if tracking many sessions
- Use more selective tool call tracking (e.g., only for specific tools)

## Related Features

### Loop Detection for Content

In addition to tool call loop detection, the system also includes loop detection for content:

- Detects repetitive patterns in LLM output text
- Works in tandem with tool call loop detection
- Can be configured separately

See `docs/LOOP_DETECTION.md` for more information on content loop detection.

### Command-based Configuration

Tool call loop detection can be configured using interactive commands:

```
!/set(tool_loop_detection_enabled=true)
!/set(tool_loop_max_repeats=4)
!/set(tool_loop_ttl_seconds=600)
!/set(tool_loop_mode="chance_then_block")
```

See `docs/API_REFERENCE.md` for more information on interactive commands.
