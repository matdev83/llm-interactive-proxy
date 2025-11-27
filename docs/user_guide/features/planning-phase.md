# Planning-Phase Strong Model Overrides

Use a more capable "strong" model for the early planning phase of a session, then switch back to your default model once execution starts. This helps ensure high-quality initial analysis and planning without paying strong-model costs for the whole session.

## Overview

The Planning-Phase Strong Model Overrides feature allows you to automatically route the initial turns of a session to a more powerful model for better planning and analysis, then seamlessly switch back to your default model for execution. This provides the best of both worlds: high-quality planning from stronger models and cost-effective execution from your standard model.

## Key Features

- **Automatic Model Switching**: Routes early requests to a configured strong model, then switches back based on turn count or file writes
- **Parameter Overrides**: Configure specific parameters (temperature, top_p, reasoning effort, thinking budget) for the strong model
- **File-Write Detection**: Automatically switches back when the model performs file-writing operations
- **Turn-Based Switching**: Configurable maximum number of planning turns before switching back
- **Zero Overhead**: Uses existing Tool Call Reactor for file-write detection, no duplicate logic
- **Flexible Configuration**: Configure via CLI, environment variables, or YAML config files

## Why This Feature Is Useful

- **Better Initial Planning**: Early prompts often set the trajectory of an entire session. Stronger reasoning models can plan tasks more effectively, leading to better overall outcomes
- **Cost and Speed Control**: After planning, the system returns to your normal/default model to control costs and improve turnaround time
- **Minimal Configuration**: No arbiter or complex logic; switching is automatic based on simple counters (turns or file writes)
- **Optimized Resource Usage**: Pay for strong model capabilities only when they matter most - during the planning phase

## Configuration

Configuration follows standard precedence: CLI > Environment Variables > YAML

### YAML Configuration

Add to your `config.yaml`:

```yaml
session:
  planning_phase:
    enabled: true
    strong_model: "openai:gpt-4o"
    max_turns: 10
    max_file_writes: 1
    overrides:
      temperature: 0.2
      top_p: 0.9
      reasoning_effort: "high"
      thinking_budget: 8000
```

### Environment Variables

```bash
# Enable/disable the feature
PLANNING_PHASE_ENABLED=true

# Specify the strong model (format: backend:model)
PLANNING_PHASE_STRONG_MODEL=openai:gpt-4o

# Set switching thresholds
PLANNING_PHASE_MAX_TURNS=10
PLANNING_PHASE_MAX_FILE_WRITES=1

# Override model parameters for the strong model
PLANNING_PHASE_TEMPERATURE=0.2
PLANNING_PHASE_TOP_P=0.9
PLANNING_PHASE_REASONING_EFFORT=high
PLANNING_PHASE_THINKING_BUDGET=8000
```

### CLI Flags

```bash
--enable-planning-phase
--planning-phase-strong-model BACKEND:MODEL
--planning-phase-max-turns N
--planning-phase-max-file-writes N
--planning-phase-temperature FLOAT
--planning-phase-top-p FLOAT
--planning-phase-reasoning-effort EFFORT
--planning-phase-thinking-budget TOKENS
```

## Usage Examples

### Basic Usage

Enable planning phase with GPT-4o for the first 8 turns:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-planning-phase \
  --planning-phase-strong-model openai:gpt-4o \
  --planning-phase-max-turns 8
```

### With Parameter Overrides

Use a strong model with specific parameters optimized for planning:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-planning-phase \
  --planning-phase-strong-model openai:gpt-4o \
  --planning-phase-max-turns 8 \
  --planning-phase-max-file-writes 1 \
  --planning-phase-temperature 0.2 \
  --planning-phase-top-p 0.9 \
  --planning-phase-reasoning-effort high \
  --planning-phase-thinking-budget 8000
```

### Using Environment Variables

Set up planning phase via environment variables:

```bash
export PLANNING_PHASE_ENABLED=true
export PLANNING_PHASE_STRONG_MODEL=openai:gpt-4o
export PLANNING_PHASE_MAX_TURNS=10
export PLANNING_PHASE_TEMPERATURE=0.2

python -m src.core.cli --default-backend openai
```

### Switching on First File Write

Configure to switch back immediately after the first file-writing operation:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-planning-phase \
  --planning-phase-strong-model openai:gpt-4o \
  --planning-phase-max-turns 20 \
  --planning-phase-max-file-writes 1
```

## Use Cases

### Code Refactoring Projects

Use a strong model to analyze the codebase and plan the refactoring strategy, then switch to a faster model for implementing the changes:

```yaml
session:
  planning_phase:
    enabled: true
    strong_model: "openai:gpt-4o"
    max_turns: 5
    max_file_writes: 1
    overrides:
      temperature: 0.1  # Low temperature for careful analysis
      reasoning_effort: "high"
```

### Complex Feature Development

Let a strong model design the architecture and plan the implementation, then use a standard model for coding:

```bash
python -m src.core.cli \
  --enable-planning-phase \
  --planning-phase-strong-model anthropic:claude-3-opus \
  --planning-phase-max-turns 10 \
  --planning-phase-temperature 0.3
```

### Bug Investigation

Use a strong model to analyze logs and plan the debugging approach, then switch to a faster model for fixes:

```yaml
session:
  planning_phase:
    enabled: true
    strong_model: "openai:gpt-4o"
    max_turns: 8
    max_file_writes: 0  # Don't switch until turn limit
    overrides:
      temperature: 0.2
      thinking_budget: 10000
```

### Cost-Optimized Development

Balance quality and cost by using premium models only for planning:

```bash
# Use GPT-4o for planning, GPT-3.5-turbo for execution
python -m src.core.cli \
  --default-backend openai \
  --default-model gpt-3.5-turbo \
  --enable-planning-phase \
  --planning-phase-strong-model openai:gpt-4o \
  --planning-phase-max-turns 5
```

## Behavior Details

### When Planning Phase Is Active

- If enabled, the proxy routes early requests to the configured strong model
- The strong model is used **unless** the current model is already the strong model
- Configured parameter overrides (temperature, top_p, etc.) are applied to the strong model

### Switching Back Conditions

The proxy automatically switches back to the default model when **either** condition is met:

1. **Maximum turns reached**: The number of turns in the planning phase reaches `max_turns`
2. **File write detected**: The model performs a file-writing tool call (e.g., `write`, `edit`, `apply_diff`, `patch`)

### After Switching

- Requests use whatever the normal routing would select (typically your default model)
- No more parameter overrides are applied
- The session continues with standard behavior

### File-Write Detection

- File-write detection is handled by the existing Tool Call Reactor
- Supported file-writing tools: `write`, `edit`, `apply_diff`, `patch`, and similar operations
- No duplicate detection logic - reuses existing infrastructure

## Configuration Parameters

### Core Settings

- **enabled**: Enable or disable the planning phase feature (default: `false`)
- **strong_model**: The model to use during planning phase (format: `backend:model`)
- **max_turns**: Maximum number of turns to use the strong model (default: `10`)
- **max_file_writes**: Maximum file writes before switching back (default: `1`)

### Parameter Overrides

These parameters are applied only to the strong model during the planning phase:

- **temperature**: Controls randomness (0.0 to 2.0, lower is more deterministic)
- **top_p**: Nucleus sampling parameter (0.0 to 1.0)
- **reasoning_effort**: Reasoning effort level (e.g., "low", "medium", "high")
- **thinking_budget**: Token budget for thinking/reasoning (integer)

## Troubleshooting

### Planning Phase Not Activating

**Problem**: The strong model is not being used even though planning phase is enabled.

**Solutions**:

- Verify `enabled` is set to `true`
- Check that `strong_model` is configured correctly (format: `backend:model`)
- Ensure the strong model is different from your default model
- Check logs for planning phase activation messages

### Not Switching Back

**Problem**: The proxy continues using the strong model after planning should end.

**Solutions**:

- Verify `max_turns` is set to a reasonable value
- Check if file-write operations are being detected (review Tool Call Reactor logs)
- Ensure `max_file_writes` is not set to 0 (which disables file-write switching)
- Review session state to confirm turn counters are incrementing

### Parameter Overrides Not Applied

**Problem**: The strong model is not using the configured parameter overrides.

**Solutions**:

- Verify overrides are in the correct section of the config
- Check configuration precedence (CLI > Env > YAML)
- Review logs for parameter override messages
- Ensure the backend supports the parameters you're overriding

### Conflicts with Other Features

**Problem**: Planning phase conflicts with other model override features.

**Solutions**:

- Check if Edit Precision Tuning is also enabled and potentially conflicting
- Review the order of middleware in the request pipeline
- Consider disabling one feature if they interfere with each other
- Check logs for multiple override attempts

## Related Features

- [Edit Precision Tuning](edit-precision.md) - Fine-tune model parameters based on edit patterns
- [Hybrid Backend](hybrid-backend.md) - Use different backends for different phases
- [Model Name Rewrites](model-name-rewrites.md) - Dynamically rewrite model names using regex rules
- [URI Model Parameters](uri-model-parameters.md) - Override model parameters via URI
- [Session Management](session-management.md) - Intelligent session state management
