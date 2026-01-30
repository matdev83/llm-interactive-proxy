# Random Model/Backend Replacement

Probabilistically replace user-specified backend:model pairs with alternative models to improve session diversity and provide resilience when specific models encounter difficulties with certain problems.

## Overview

The Random Model/Backend Replacement feature enables probabilistic swapping of backend:model pairs during a session. When activated, the system routes requests to an alternative model for a configurable number of turns before returning to the original model. This provides session diversity and can help when a specific model struggles with particular types of problems that alternative models might solve more effectively.

## Related Documentation

- [Replacement Metrics](replacement-metrics.md) for monitoring activation rates and opt-outs
- [Monitoring Overview](monitoring-overview.md) for dashboard and endpoint context

## Key Features

- **Probabilistic Activation**: Configure the likelihood (0.0-1.0) of triggering replacement for each session
- **Multi-Turn Persistence**: Replacement remains active for a configurable number of consecutive turns
- **OAUTH-AUTO Support**: Optional support for multi-account `oauth-auto` rotating backends via explicit override
- **Per-Session State**: Each session maintains independent replacement state

- **Opt-Out Support**: Disable replacement via request headers or session-level configuration
- **Transparent Operation**: Works seamlessly with existing features like tool filtering, wire capture, and usage accounting
- **Streaming Compatible**: Full support for streaming responses with replacement models

## Why This Feature Is Useful

- **Improved Resilience**: When a model encounters difficulties with a specific problem, an alternative model might provide a fresh perspective or different approach
- **Session Diversity**: Probabilistic replacement introduces variety in model responses, which can be valuable for testing and development
- **Automatic Fallback**: No manual intervention required - the system automatically tries alternative models based on configured probability
- **Cost Optimization**: Configure replacement to use more cost-effective models for certain types of tasks
- **Testing and Validation**: Useful for comparing model behaviors and validating that your application works with multiple backends

## Configuration

Configuration follows standard precedence: CLI > Environment Variables > YAML

### YAML Configuration

Add to your `config.yaml`:

```yaml
replacement:
  enabled: true
  probability: 0.3  # 30% chance of replacement
  replacement_rules:
    - from_pattern: "*"  # Wildcard: matches all models
      to_backend: "qwen-oauth"
      to_model: "qwen3-coder-plus"
    - from_pattern: "gpt-4"  # Partial match: matches any model containing "gpt-4"
      to_backend: "openai"
      to_model: "gpt-3.5-turbo"
    - from_pattern: "openai:gpt-4"  # Exact match: matches specific backend:model
      to_backend: "anthropic"
      to_model: "claude-3-5-sonnet"
  turn_count: 3  # Stay with replacement for 3 turns
  allow_oauth_auto_replacement: true  # Allow replacement for oauth-auto backends
```


**Legacy format** (automatically converted to wildcard rule):
```yaml
replacement:
  enabled: true
  probability: 0.3
  backend_model: "qwen-oauth:qwen3-coder-plus"  # Deprecated
  turn_count: 3
```

### Environment Variables

```bash
# Enable/disable the feature
REPLACEMENT_ENABLED=true

# Set replacement probability (0.0-1.0)
REPLACEMENT_PROBABILITY=0.3

# Specify replacement rules as JSON array
REPLACEMENT_RULES='[{"from_pattern":"*","to_backend":"qwen-oauth","to_model":"qwen3-coder-plus"},{"from_pattern":"gpt-4","to_backend":"openai","to_model":"gpt-3.5-turbo"}]'

# Legacy format (deprecated)
REPLACEMENT_BACKEND_MODEL=qwen-oauth:qwen3-coder-plus

# Set number of turns to use replacement
REPLACEMENT_TURN_COUNT=3

# Allow replacement for oauth-auto backends
ALLOW_OAUTH_AUTO_REPLACEMENT=true
```


### CLI Flags

```bash
--enable-replacement
--replacement-probability FLOAT
--random-model-replacement-from-to "<from>=<to>"  # Can be specified multiple times
--replacement-backend-model BACKEND:MODEL  # Deprecated: use --random-model-replacement-from-to instead
--replacement-turn-count N
--allow-oauth-auto-replacement  # Allow replacement for oauth-auto backends
```


## Conditional Replacement Rules

The replacement feature supports conditional rules that specify **when** to replace (which models) and **what** to replace them with. Rules are evaluated in order, and the first matching rule is used.

### Pattern Matching

Each rule has a `from_pattern` that matches against the original model:

- **Wildcard (`*`)**: Matches all models from any backend
  ```yaml
  from_pattern: "*"
  ```

- **Partial Match (`model-name`)**: Matches any model whose name contains the substring (case-sensitive)
  ```yaml
  from_pattern: "gpt-4"  # Matches "gpt-4", "gpt-4-turbo", "gpt-4o", etc.
  ```

- **Exact Match (`backend:model`)**: Matches a specific fully qualified model identifier
  ```yaml
  from_pattern: "openai:gpt-4"  # Only matches exactly "openai:gpt-4"
  ```

### Rule Evaluation Order

Rules are evaluated in the order they are specified. Place more specific rules before wildcard rules:

```yaml
replacement_rules:
  - from_pattern: "openai:gpt-4"  # Specific rule first
    to_backend: "anthropic"
    to_model: "claude-3-5-sonnet"
  - from_pattern: "gpt-4"  # Partial match (catches other gpt-4 variants)
    to_backend: "openai"
    to_model: "gpt-3.5-turbo"
  - from_pattern: "*"  # Wildcard last (catches everything else)
    to_backend: "qwen-oauth"
    to_model: "qwen3-coder-plus"
```

## Usage Examples

### Basic Usage

Enable replacement with 30% probability using a wildcard rule:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-replacement \
  --replacement-probability 0.3 \
  --random-model-replacement-from-to "*=qwen-oauth:qwen3-coder-plus" \
  --replacement-turn-count 3
```

### Conditional Replacement

Replace specific models with different targets:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-replacement \
  --replacement-probability 0.3 \
  --random-model-replacement-from-to "gpt-4=openai:gpt-3.5-turbo" \
  --random-model-replacement-from-to "claude=anthropic:claude-3-haiku" \
  --random-model-replacement-from-to "*=qwen-oauth:qwen3-coder-plus" \
  --replacement-turn-count 3
```

### High Probability Replacement

Use replacement frequently for testing:

```bash
python -m src.core.cli \
  --default-backend anthropic \
  --enable-replacement \
  --replacement-probability 0.8 \
  --random-model-replacement-from-to "*=openai:gpt-4" \
  --replacement-turn-count 5
```

### Single-Turn Replacement

Replace for just one turn to get a quick alternative perspective:

```bash
python -m src.core.cli \
  --default-backend openai \
  --enable-replacement \
  --replacement-probability 0.5 \
  --random-model-replacement-from-to "*=anthropic:claude-3-5-sonnet" \
  --replacement-turn-count 1
```

### Using Environment Variables

Set up replacement via environment variables:

```bash
export REPLACEMENT_ENABLED=true
export REPLACEMENT_PROBABILITY=0.3
export REPLACEMENT_RULES='[{"from_pattern":"*","to_backend":"qwen-oauth","to_model":"qwen3-coder-plus"}]'
export REPLACEMENT_TURN_COUNT=3

python -m src.core.cli --default-backend openai
```

## Use Cases

### Development and Testing

Test your application with multiple models to ensure compatibility:

```yaml
replacement:
  enabled: true
  probability: 0.5  # 50% of sessions use alternative model
  replacement_rules:
    - from_pattern: "*"
      to_backend: "anthropic"
      to_model: "claude-3-5-sonnet"
  turn_count: 10  # Use alternative for extended testing
```

### Cost Optimization

Probabilistically route expensive models to more cost-effective alternatives:

```bash
python -m src.core.cli \
  --default-backend openai \
  --default-model gpt-4 \
  --enable-replacement \
  --replacement-probability 0.4 \
  --random-model-replacement-from-to "gpt-4=openai:gpt-3.5-turbo" \
  --random-model-replacement-from-to "claude-3-5-sonnet=anthropic:claude-3-haiku" \
  --replacement-turn-count 5
```

### Problem-Solving Resilience

When a model struggles, automatically try an alternative:

```yaml
replacement:
  enabled: true
  probability: 0.3
  replacement_rules:
    - from_pattern: "*"
      to_backend: "qwen-oauth"
      to_model: "qwen3-coder-plus"
  turn_count: 3  # Give alternative model a few turns to help
```

### Model Comparison

Compare behaviors across different models:

```bash
# Run multiple sessions to see how different models handle the same tasks
python -m src.core.cli \
  --default-backend anthropic \
  --enable-replacement \
  --replacement-probability 0.5 \
  --random-model-replacement-from-to "*=openai:gpt-4" \
  --replacement-turn-count 5
```

### Selective Model Replacement

Replace only specific models while leaving others unchanged:

```yaml
replacement:
  enabled: true
  probability: 0.3
  replacement_rules:
    # Only replace GPT-4 models with GPT-3.5
    - from_pattern: "gpt-4"
      to_backend: "openai"
      to_model: "gpt-3.5-turbo"
    # Other models are not replaced (no wildcard rule)
  turn_count: 3
```

## Behavior Details

### When Replacement Activates

```
Session Start
    |
    v
Check Probability --> Random < Threshold? --> Yes --> Activate Replacement
    |                                              |
    No                                             v
    |                                         Use Replacement Model
    v                                              |
Use Original Model                                 v
                                              Decrement Turn Counter
                                                   |
                                                   v
                                            Counter = 0? --> Yes --> Deactivate
                                                   |
                                                   No
                                                   |
                                                   v
                                            Continue Replacement
```

- At the start of each session (when replacement is not already active), the system generates a random number between 0.0 and 1.0
- If the random number is less than the configured probability, replacement activates
- Once activated, all requests for that session use the replacement backend:model
- The turn counter decrements after each completed turn
- When the counter reaches 0, the system deactivates replacement and returns to the original model

### Replacement State Management

- **Per-Session State**: Each session maintains independent replacement state
- **Turn Counting**: The system tracks remaining turns for each active replacement
- **Automatic Deactivation**: Replacement automatically deactivates when the turn counter expires
- **State Persistence**: Replacement state is maintained across the session lifetime

### Opt-Out Mechanisms

#### Header-Based Opt-Out

Disable replacement for a specific request:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "X-Disable-Replacement: true" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [...]}'
```

#### Session-Level Opt-Out

Disable replacement for an entire session programmatically via the replacement service API.

## Configuration Parameters

### Core Settings

- **enabled**: Enable or disable the replacement feature (default: `false`)
- **probability**: Probability (0.0-1.0) of triggering replacement (default: `0.0`)
  - `0.0` = Never replace
  - `0.3` = 30% chance of replacement
  - `1.0` = Always replace
- **replacement_rules**: List of conditional replacement rules (required when enabled)
  - Each rule specifies `from_pattern`, `to_backend`, and `to_model`
  - Rules are evaluated in order; first matching rule is used
  - At least one rule is required when enabled
- **backend_model**: **Deprecated** - Legacy format for backward compatibility. Automatically converted to a wildcard replacement rule if `replacement_rules` is empty.
- **turn_count**: Number of consecutive turns to use replacement model (default: `1`, minimum: `1`)
- **allow_oauth_auto_replacement**: Allow replacement for multi-account `oauth-auto` backends (default: `false`). Enabling this is recommended for "diversity of views" research but may bypass capacity protections.


### Replacement Rule Format

Each replacement rule has three fields:

- **from_pattern**: Pattern to match against original models
  - `"*"` - Wildcard (matches all models)
  - `"model-name"` - Partial match (substring in model name)
  - `"backend:model"` - Exact match (fully qualified identifier)
- **to_backend**: Target backend identifier (e.g., `"qwen-oauth"`, `"openai"`)
- **to_model**: Target model identifier (e.g., `"qwen3-coder-plus"`, `"gpt-3.5-turbo"`)

### Validation Rules

The system validates configuration at startup:

- **probability** must be between 0.0 and 1.0 inclusive
- **replacement_rules** must be a non-empty list when enabled
- Each rule's `to_backend` and `to_model` must be non-empty strings
- Each rule's `to_backend:to_model` must be in format "backend:model"
- **to_backend** specified in each rule must be registered in the backend registry
- **turn_count** must be a positive integer (>= 1)
- **backend_model** (legacy) must be in format "backend:model" with exactly one colon if provided

## Feature Compatibility

### Works With

- **Tool Filtering**: Tool filtering is applied to replacement models
- **Wire Capture**: Both original and replacement requests/responses are captured
- **Usage Accounting**: Usage is correctly attributed to the actual model used
- **Agent Configuration**: Agent settings are preserved when using replacement models
- **Streaming**: Full support for streaming responses
- **Command Processing**: Replacement logic executes after command processing

### Execution Order

Replacement logic executes in the request processing pipeline:

1. Session resolution
2. Command prefix processing
3. **Model replacement evaluation** (this feature)
4. Backend request routing
5. Response processing

## Troubleshooting

### Replacement Not Activating

**Problem**: Replacement never activates even though it's enabled.

**Solutions**:

- Verify `enabled` is set to `true`
- Check that `probability` is greater than 0.0
- Ensure `backend_model` is configured correctly (format: `backend:model`)
- Check logs for probability evaluation messages (DEBUG level)
- Verify the replacement backend is registered and available

### Replacement Backend Not Found

**Problem**: Configuration validation fails with "backend not registered" error.

**Solutions**:

- Verify the backend name in `backend_model` matches a registered backend
- Check your backend configuration in the `backends` section
- Ensure required API keys are set for the replacement backend
- Review available backends in your configuration

### Replacement Not Deactivating

**Problem**: Replacement continues beyond the configured turn count.

**Solutions**:

- Verify `turn_count` is set correctly
- Check logs for turn completion messages
- Ensure requests are completing successfully (errors may prevent turn counting)
- Review session state to confirm turn counter is decrementing

### Opt-Out Not Working

**Problem**: Replacement still activates despite opt-out header.

**Solutions**:

- Verify header name is exactly `X-Disable-Replacement` (case-insensitive)
- Ensure header value is `true` (string)
- Check that the header is being passed through any proxies or load balancers
- Review logs for opt-out detection messages (DEBUG level)

### Conflicts with Other Features

**Problem**: Replacement conflicts with other model override features.

**Solutions**:

- Check if Planning Phase is also enabled and potentially conflicting
- Review the order of middleware in the request pipeline
- Consider the precedence of different model override mechanisms
- Check logs for multiple override attempts

## Logging

The replacement service logs key events at different levels:

### INFO Level

- Service initialization with configuration summary
- Replacement activation (session_id, original model, replacement model, turn count)
- Replacement deactivation (session_id, return to original model)
- Session-level opt-out actions

### DEBUG Level

- Probability evaluation (session_id, random value, threshold, result)
- Routing decisions (session_id, effective backend:model)
- Header-based opt-out detection

## Related Features

- [Planning Phase](planning-phase.md) - Use strong models for initial planning
- [Model Name Rewrites](model-name-rewrites.md) - Dynamically rewrite model names using regex rules
- [Hybrid Backend](hybrid-backend.md) - Use different backends for different phases
- [Session Management](session-management.md) - Intelligent session state management
- [URI Model Parameters](uri-model-parameters.md) - Override model parameters via URI

## Implementation Details

### Architecture

The replacement feature is implemented as a service (`ModelReplacementService`) that integrates into the request processing pipeline. It maintains per-session state and uses probability-based decision making to determine when to activate replacement.

### State Management

- Replacement state is stored per session in memory
- State includes: active flag, turns remaining, original model, replacement model
- State is automatically cleaned up when sessions end

### Thread Safety

The replacement service uses asyncio locks to ensure thread-safe state updates in concurrent environments.

### Performance

- Minimal overhead: O(1) state lookup per request
- Efficient random number generation
- No blocking operations in the critical path
