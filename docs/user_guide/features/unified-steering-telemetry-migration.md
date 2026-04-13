# Unified Steering Telemetry

This guide describes how steering events appear in application logs after the unified steering framework (`UnifiedSteeringHandler`) replaced multiple per-tool steering handlers.

## Overview

The unified handler evaluates policies in priority order and emits **one structured INFO line per evaluation** (steered or pass-through).

Individual policies may also emit their own INFO lines when they match (for example, `ConfiguredRulesPolicy` logs when a YAML steering rule hits). Those lines are separate from the unified telemetry line.

## Structured log format

The unified handler logs:

```
Unified steering evaluation: {
    "session_id": "<session_id>",
    "tool_name": "<tool_name>",
    "command_preview": "<first 100 chars of command>",
    "evaluated_policies": ["policy1", "policy2", ...],
    "matched_policy": "<policy_name>" | null,
    "outcome": "steered" | "pass_through",
    "elapsed_ms": <float>,
    "severity": "<severity>" (only if steered),
    "should_block": <bool> (only if steered)
}
```

**Example:**

```
INFO - Unified steering evaluation: {'session_id': 'abc123', 'tool_name': 'shell', 'command_preview': 'python -c "print(1)"', 'evaluated_policies': ['inline_python', 'configured_rules', 'pytest_full_suite'], 'matched_policy': 'inline_python', 'outcome': 'steered', 'elapsed_ms': 0.45, 'severity': 'warning', 'should_block': True}
```

## Parsing for dashboards

The structured log is a Python dict representation. For JSON parsing in log aggregators:

1. Extract the text after `Unified steering evaluation: `
2. Replace single quotes with double quotes
3. Replace `True`/`False` with `true`/`false`
4. Replace `None` with `null`
5. Parse as JSON

**Example log aggregator query (Splunk-style):**

```spl
index=proxy sourcetype=application "Unified steering evaluation"
| rex "Unified steering evaluation: (?<steering_data>.*)"
| eval steering_json = replace(replace(replace(steering_data, "'", "\""), "True", "true"), "False", "false")
| spath input=steering_json
| stats count by matched_policy, outcome
```

## Configuration

Policy order can be tuned with `session.tool_call_reactor.steering_policy_priorities` (see main configuration reference). There is no separate toggle for unified steering telemetry format.

## Usage Examples

1. **Verify unified lines in local logs:** run a tool call that triggers steering (for example, a disallowed shell pattern) and confirm a single `Unified steering evaluation` line appears at INFO with `outcome: steered`.
2. **Compare with policy-specific logs:** some policies still emit their own INFO lines; the unified line is the cross-policy summary and should always be present when the reactor evaluated that tool call.

## Use Cases

- **Operators:** aggregate `matched_policy` and `outcome` from unified lines to see which policy fired most often.
- **Developers:** when debugging a false steer, inspect `evaluated_policies` and `command_preview` in the same line without correlating multiple legacy log formats.

**Example (priorities only):**

```yaml
session:
  tool_call_reactor:
    steering_policy_priorities:
      inline_python: 100
      configured_rules: 90
      pytest_full_suite: 70
```

## Troubleshooting

- **No unified line:** Ensure log level is INFO or lower. Pass-through evaluations still emit `Unified steering evaluation` with `outcome: pass_through`.
- **Older docs mentioned `emit_legacy_steering_log`:** That option has been removed. Use the structured line above (and any policy-specific logs) as the source of truth.

## Related Documentation

- [Inline Python Steering](inline-python-steering.md)
- [Pytest Full Suite Steering](pytest-full-suite-steering.md)
- [Dangerous Command Protection](dangerous-command-protection.md)
- [Monitoring Overview](monitoring-overview.md)
