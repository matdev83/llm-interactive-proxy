# URI Model Parameters

Specify model parameters directly in model strings using URL query parameter syntax for explicit per-request control.

## Overview

The URI Model Parameters feature allows you to specify model parameters directly in the model string using URL query parameter syntax. This provides explicit per-request control over model behavior without modifying configuration files or headers.

This feature is particularly useful when you need to:

- Override default model parameters for specific requests
- Apply different parameters to reasoning and execution models in hybrid backends
- Test different parameter combinations without changing configuration
- Provide per-request parameter control in automated workflows

## Key Features

- **Inline Parameter Specification**: Append parameters to model strings using URI syntax (e.g., `backend:model?temperature=0.5`)
- **Multiple Parameters**: Support for multiple parameters in a single model string (e.g., `?temperature=0.5&reasoning_effort=high`)
- **Hybrid Backend Support**: Apply different parameters to reasoning and execution models independently
- **Clear Precedence**: URI parameters override config and headers but respect interactive session commands
- **Graceful Error Handling**: Invalid parameters are logged but don't break requests

## Configuration

### Supported Parameters

The following parameters can be specified via URI syntax:

- **temperature**: Controls randomness in model outputs (0.0-2.0)
- **reasoning_effort**: Controls computational effort for reasoning models (low/medium/high)
- **top_p**: Controls diversity via nucleus sampling (e.g., 0.9)
- **top_k**: Controls diversity by filtering to the K most likely next tokens (e.g., 40)

### Parameter Precedence

Parameters are resolved from multiple sources with the following precedence (highest to lowest):

1. **Interactive Session Commands** (highest priority) - `!/temperature(0.5)`
2. **URI Parameters** - `model?temperature=0.5`
3. **Request Headers** - `X-Temperature: 0.5`
4. **Configuration File** (lowest priority) - `config.yaml`

When the same parameter is specified in multiple sources, the higher priority source wins. This allows you to:

- Set defaults in config files
- Override per-request with URI parameters
- Override dynamically with session commands

### Debug Logging

When debug logging is enabled, the proxy provides detailed information about parameter resolution:

```
DEBUG: Parsed URI parameters from model string 'openai:gpt-4?temperature=0.5': {'temperature': 0.5}
DEBUG: Parameter resolution for openai:
  temperature: 0.5 (source: uri, overrode: config=0.8)
  reasoning_effort: high (source: session)
```

This helps you understand:

- Which parameters were parsed from the URI
- The effective value of each parameter
- Which source provided each parameter
- Which sources were overridden

## Usage Examples

### Basic Usage

**Simple Model with Temperature:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai:gpt-4?temperature=0.5",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Multiple Parameters:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic:claude-3?temperature=0.7&reasoning_effort=high",
    "messages": [{"role": "user", "content": "Solve this problem"}]
  }'
```

**Complex Model Path:**

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter:anthropic/claude-3-haiku:beta?temperature=0.3&reasoning_effort=medium",
    "messages": [{"role": "user", "content": "Quick task"}]
  }'
```

### Hybrid Backend with Independent Parameters

Apply different parameters to reasoning and execution models:

```bash
# Use high temperature for creative reasoning, low for precise execution
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "hybrid:[openai:gpt-4?temperature=0.9,anthropic:claude-3?temperature=0.1]",
    "messages": [{"role": "user", "content": "Write a creative story"}]
  }'
```

### Override Config Temperature

```yaml
# config.yaml
model_defaults:
  openai:gpt-4:
    temperature: 0.8
```

```bash
# Request with URI parameter overrides config
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai:gpt-4?temperature=0.3",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
# Effective temperature: 0.3 (URI overrides config)
```

### Session Command Override

```bash
# Start with URI parameter
model: openai:gpt-4?temperature=0.5

# Override with session command (takes precedence)
!/temperature(0.8)

# Effective temperature: 0.8 (session command wins)
```

### Validation and Error Handling

The proxy validates URI parameters and handles errors gracefully:

**Valid Parameter:**

```
openai:gpt-4?temperature=0.5
# Parsed and applied
```

**Invalid Value:**

```
openai:gpt-4?temperature=3.5
# Logged as error: "temperature: 3.5 above maximum value (2.0)"
# Request continues with default/config temperature
```

**Unknown Parameter:**

```
openai:gpt-4?unknown_param=value
# Logged as warning: "Unknown URI parameter 'unknown_param'"
# Request continues, parameter ignored
```

**Malformed Query String:**

```
openai:gpt-4?invalid
# Logged as warning: "Malformed URI query string"
# Request continues without URI parameters
```

## Use Cases

### Testing Different Parameter Combinations

Quickly test different parameter values without modifying configuration files:

```bash
# Test low temperature
curl ... -d '{"model": "openai:gpt-4?temperature=0.1", ...}'

# Test high temperature
curl ... -d '{"model": "openai:gpt-4?temperature=0.9", ...}'

# Test with reasoning effort
curl ... -d '{"model": "openai:gpt-4?temperature=0.5&reasoning_effort=high", ...}'
```

### Per-Request Parameter Control

Apply specific parameters for different types of requests:

```bash
# Creative writing - high temperature
curl ... -d '{"model": "openai:gpt-4?temperature=0.9", "messages": [{"role": "user", "content": "Write a story"}]}'

# Code generation - low temperature
curl ... -d '{"model": "openai:gpt-4?temperature=0.1", "messages": [{"role": "user", "content": "Write a function"}]}'

# Analysis - medium temperature
curl ... -d '{"model": "openai:gpt-4?temperature=0.5", "messages": [{"role": "user", "content": "Analyze this"}]}'
```

### Hybrid Backend Optimization

Optimize reasoning and execution phases independently:

```bash
# Creative reasoning + precise execution
curl ... -d '{
  "model": "hybrid:[openai:gpt-4?temperature=0.9&reasoning_effort=high,anthropic:claude-3?temperature=0.1]",
  "messages": [...]
}'

# Fast reasoning + detailed execution
curl ... -d '{
  "model": "hybrid:[openai:gpt-4?reasoning_effort=low,anthropic:claude-3?temperature=0.5]",
  "messages": [...]
}'
```

### Automated Workflows

Programmatically control model parameters in scripts:

```python
import requests

def call_llm(prompt, temperature=0.5, reasoning_effort="medium"):
    model = f"openai:gpt-4?temperature={temperature}&reasoning_effort={reasoning_effort}"
    response = requests.post(
        "http://localhost:8000/v1/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}]
        }
    )
    return response.json()

# Use different parameters for different tasks
creative_response = call_llm("Write a story", temperature=0.9, reasoning_effort="high")
code_response = call_llm("Write a function", temperature=0.1, reasoning_effort="low")
```

### A/B Testing

Compare model behavior with different parameters:

```bash
# Version A - conservative
curl ... -d '{"model": "openai:gpt-4?temperature=0.3", ...}'

# Version B - creative
curl ... -d '{"model": "openai:gpt-4?temperature=0.8", ...}'

# Compare outputs to determine optimal parameters
```

## Troubleshooting

### Parameters Not Applied

**Problem**: URI parameters don't seem to affect model behavior

**Solutions**:

1. Check parameter precedence - session commands override URI parameters
2. Verify parameter name spelling (case-sensitive)
3. Enable debug logging to see parameter resolution
4. Check that the backend supports the parameter

### Invalid Parameter Values

**Problem**: Getting warnings about invalid parameter values

**Solutions**:

1. Check parameter ranges (e.g., temperature: 0.0-2.0)
2. Verify parameter format (e.g., reasoning_effort: low/medium/high)
3. Review logs for specific validation errors
4. Consult backend documentation for supported values

### Malformed Query Strings

**Problem**: URI parameters not being parsed

**Solutions**:

1. Ensure proper URL encoding for special characters
2. Use `&` to separate multiple parameters
3. Use `=` to assign values to parameters
4. Check for typos in the query string syntax

### Hybrid Backend Parameter Conflicts

**Problem**: Parameters not applying correctly to hybrid backend models

**Solutions**:

1. Specify parameters for each model independently
2. Use square brackets to group hybrid models: `hybrid:[model1?param=value,model2?param=value]`
3. Check logs to verify which parameters are applied to which model
4. Ensure both models support the specified parameters

## Related Features

- [Hybrid Backend](hybrid-backend.md) - Use URI parameters with hybrid reasoning/execution models
- [Model Name Rewrites](model-name-rewrites.md) - Transform model names before URI parameter parsing
- [Planning Phase Overrides](planning-phase.md) - Combine with planning phase model selection
- [Identity Override](identity-override.md) - Control client identity alongside model parameters
