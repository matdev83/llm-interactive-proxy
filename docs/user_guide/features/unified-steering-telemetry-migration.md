# Unified Steering Telemetry Migration Guide

This guide documents the telemetry changes introduced with the unified steering framework and provides migration guidance for users with existing log monitoring dashboards.

## Overview

The unified steering framework consolidates multiple legacy steering handlers into a single `UnifiedSteeringHandler`. This change includes a new structured log format while providing backward compatibility through an optional legacy log emission mode.

## Log Format Changes

### New Structured Log Format (Default)

The unified steering handler emits structured logs with the following schema:

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

### Legacy Log Format

When `emit_legacy_steering_log` is enabled, an additional log line is emitted in the legacy format:

```
Steering via rule '<policy_name>' for tool '<tool_name>' in session <session_id>
```

**Example:**
```
INFO - Steering via rule 'inline_python' for tool 'shell' in session abc123
```

## Migration Strategies

### Option 1: Enable Legacy Log Emission (Recommended for Gradual Migration)

Enable the legacy log format alongside the new structured logs:

```yaml
session:
  tool_call_reactor:
    emit_legacy_steering_log: true  # Default: true
```

This allows existing dashboards to continue working while you update them to use the new format.

### Option 2: Update Dashboards to New Format

Update your log parsing and dashboards to use the new structured format:

| Legacy Field | New Field Location |
|--------------|-------------------|
| Rule name | `matched_policy` |
| Tool name | `tool_name` |
| Session ID | `session_id` |
| (not available) | `outcome` |
| (not available) | `evaluated_policies` |
| (not available) | `elapsed_ms` |
| (not available) | `severity` |
| (not available) | `should_block` |

### Option 3: Disable Legacy Logging (After Migration)

Once dashboards are updated, disable legacy logging to reduce log volume:

```yaml
session:
  tool_call_reactor:
    emit_legacy_steering_log: false
```

## Field Mapping Reference

### Parsing the Structured Log

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

### Key Differences

| Aspect | Legacy | Unified |
|--------|--------|---------|
| Log prefix | `Steering via rule` | `Unified steering evaluation` |
| Format | Plain text | Structured dict |
| Timing info | No | Yes (`elapsed_ms`) |
| Policy chain visibility | No | Yes (`evaluated_policies`) |
| Outcome indicator | Implicit (log only on block) | Explicit (`outcome` field) |
| Pass-through logging | No | Yes (when `outcome: pass_through`) |

## Configuration Reference

### Full Configuration Example

```yaml
session:
  tool_call_reactor:
    # Enable/disable legacy log format for backward compatibility
    emit_legacy_steering_log: true  # Default: true

    # Policy priority overrides (optional)
    steering_policy_priorities:
      inline_python: 100      # Higher = evaluated first
      configured_rules: 90
      pytest_full_suite: 70
```

### Environment Variables

```bash
# No direct environment variable for emit_legacy_steering_log
# Use YAML configuration or programmatic setup
```

## Deprecation Timeline

| Phase | Timeline | Action |
|-------|----------|--------|
| Current | Now | Legacy log emission enabled by default |
| Phase 1 | +6 months | Legacy log emission disabled by default |
| Phase 2 | +12 months | Legacy log emission removed |

Plan your migration accordingly.

## Troubleshooting

### Missing Legacy Logs

If legacy logs are not appearing:

1. Verify `emit_legacy_steering_log: true` in configuration
2. Check that a policy actually matched (legacy log only emits on block)
3. Ensure log level is set to INFO or lower

### Duplicate Log Entries

When both formats are enabled, you'll see two log lines per steering event. This is expected behavior during migration. Disable legacy logging after updating dashboards.

## Related Documentation

- [Inline Python Steering](inline-python-steering.md)
- [Pytest Full Suite Steering](pytest-full-suite-steering.md)
- [Dangerous Command Protection](dangerous-command-protection.md)
- [Monitoring Overview](monitoring-overview.md)
