# Replacement Metrics

The model replacement service includes comprehensive metrics tracking to monitor and analyze replacement behavior.

## Overview

The metrics system tracks three main categories:

1. **Activation Rate** - How often replacement is triggered
2. **Turn Count Distribution** - How long replacement sessions last
3. **Opt-Out Rate** - How often users opt out of replacement

## Accessing Metrics
### Configuration

- Enable replacement metrics by turning on the model replacement feature in your config (metrics are tracked automatically when replacement is active).
- Keep metrics in memory only; no external storage is required.
- Reset metrics between runs with `ModelReplacementService.reset_metrics()` to avoid mixing prod and test data.

### Programmatic Access

```python
from src.core.services.model_replacement_service import ModelReplacementService

# Get the service instance
service = ModelReplacementService(config, backend_registry)

# Access metrics
metrics = service.get_metrics()

# Get activation rate (per second)
activation_rate = metrics.get_activation_rate()

# Get activation rate for last 60 seconds
recent_rate = metrics.get_activation_rate(60.0)

# Get activation rate for a specific session
session_rate = metrics.get_activation_rate_by_session("session-id")

# Get turn count distribution
distribution = metrics.get_turn_count_distribution()
# Returns: {3: 10, 5: 5, 2: 3}  # 10 activations with 3 turns, etc.

# Get average turn count
avg_turns = metrics.get_average_turn_count()

# Get opt-out rate (per second)
opt_out_rate = metrics.get_opt_out_rate()

# Get opt-out rate for a specific session
session_opt_out_rate = metrics.get_opt_out_rate_by_session("session-id")

# Get comprehensive summary
summary = metrics.get_summary()
```

### Logging Metrics

The service can log a comprehensive metrics summary:

```python
# Log metrics summary to INFO level
service.log_metrics_summary()
```

This will output a log message like:

```
REPLACEMENT_METRICS_SUMMARY: elapsed=120.5s | activations=15 (rate=0.1245/s, last_60s=8.0) | turns=45 (avg=3.00) | opt_outs=3 (header=2, session=1, rate=0.0249/s)
REPLACEMENT_TURN_DISTRIBUTION: 3turns=10x, 5turns=5x
```

## Metrics Details
### Usage Examples

- **Ad-hoc debugging**: Call `service.log_metrics_summary()` after a test run to confirm activation counts and opt-out rates.
- **Dashboards**: Periodically read `service.get_metrics().get_summary()` and push the dict to your monitoring system.
- **Guardrails**: Alert when `opt_out_rate` spikes or when `activation_rate` falls below a threshold (indicating replacement is rarely used).

### Activation Metrics

- `total_activations`: Total number of times replacement was activated
- `activations_by_session`: Dictionary mapping session IDs to activation counts
- `activation_timestamps`: List of timestamps when activations occurred
- `turn_counts`: List of turn counts for each activation

### Turn Completion Metrics

- `total_turns_completed`: Total number of turns completed across all sessions
- `turns_by_session`: Dictionary mapping session IDs to turn counts

### Opt-Out Metrics

- `total_opt_outs`: Total number of opt-out events
- `header_opt_outs`: Number of header-based opt-outs
- `session_opt_outs`: Number of session-level opt-outs
- `opt_outs_by_session`: Dictionary mapping session IDs to opt-out counts
- `opt_out_timestamps`: List of timestamps when opt-outs occurred

### Probability Check Metrics

- `total_probability_checks`: Total number of probability checks performed
- `probability_checks_by_session`: Dictionary mapping session IDs to check counts

## Resetting Metrics

Metrics can be reset to initial state:

```python
service.reset_metrics()
```

This is useful for:
- Starting fresh after a deployment
- Clearing metrics after a test run
- Resetting counters for a new time period

## Use Cases

### Monitoring Replacement Effectiveness

Track activation rate to understand how often replacement is being used:

```python
metrics = service.get_metrics()
summary = metrics.get_summary()

activation_rate = summary["activation_metrics"]["activation_rate_per_second"]
if activation_rate < 0.01:
    print("Replacement is rarely being used")
elif activation_rate > 0.1:
    print("Replacement is frequently being used")
```

### Analyzing Turn Count Patterns

Understand how long replacement sessions typically last:

```python
distribution = metrics.get_turn_count_distribution()
avg_turns = metrics.get_average_turn_count()

print(f"Average turns per activation: {avg_turns:.2f}")
print(f"Turn count distribution: {distribution}")
```

### Tracking Opt-Out Behavior

Monitor how often users opt out of replacement:

```python
summary = metrics.get_summary()
opt_out_metrics = summary["opt_out_metrics"]

total_opt_outs = opt_out_metrics["total_opt_outs"]
header_opt_outs = opt_out_metrics["header_opt_outs"]
session_opt_outs = opt_out_metrics["session_opt_outs"]

print(f"Total opt-outs: {total_opt_outs}")
print(f"  Header-based: {header_opt_outs}")
print(f"  Session-level: {session_opt_outs}")
```

## Performance Considerations

The metrics system is designed to have minimal performance impact:

- Metrics are tracked in-memory using efficient data structures
- No external dependencies or I/O operations
- Timestamp recording uses `time.time()` which is very fast
- Dictionary lookups are O(1) for session-specific metrics

The overhead of metrics tracking is typically less than 0.1ms per request.
