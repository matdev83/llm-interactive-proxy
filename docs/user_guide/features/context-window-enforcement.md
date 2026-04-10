# Context Window Enforcement

Enforce per-model context window limits at the front-end to prevent requests that exceed model capabilities.

## Overview

The Context Window Enforcement feature enforces per-model context window limits at the front-end, preventing requests that exceed model capabilities and providing clear error messages before they reach backend providers. This protects against excessive token usage, prevents unnecessary API calls and costs, and provides structured error responses that help clients understand and fix the issue.

## Key Features

- **Customizable Limits**: Configure different context window sizes per model and backend
- **Input Token Enforcement**: Blocks requests that exceed input token limits with structured error responses
- **Front-end Protection**: Prevents unnecessary API calls and costs by validating limits before backend requests
- **Flexible Configuration**: Supports both `context_window` and `max_input_tokens` for fine-grained control
- **Clear Error Messages**: Provides detailed information about limits and measured token counts
- **Model-Specific Tokenizers**: Uses model-specific tokenizers when available for accurate counting
- **Registry-Backed Modality Checks**: Rejects requests with unsupported input modalities (image/audio) when registry metadata is available

## Configuration

Context windows are configured in backend-specific YAML files or model defaults.

When the model registry is enabled, the proxy can also enforce modality support based on registry metadata. If the registry file is missing/unparsable or the requested model is absent from the registry, both modality and context enforcement are skipped (fail-open). If the model exists but `modalities` are missing, only modality validation is skipped.

### Backend-Specific Configuration

```yaml
# config/backends/custom/backend.yaml
models:
  "your-model-name":
    limits:
      context_window: 262144        # Total context window size (tokens)
      max_input_tokens: 200000      # Input token limit (tokens)
      max_output_tokens: 62144      # Output token limit (tokens)
      requests_per_minute: 60       # Rate limits
      tokens_per_minute: 1000000
```

### Model Defaults Configuration

```yaml
# config.yaml
model_defaults:
  "your-model-name":
    limits:
      context_window: 128000        # 128K context window
      max_input_tokens: 100000      # 100K input limit
```

### CLI Override

Force a specific context window size for all models:

```bash
--force-context-window 8000   # Override all model context windows to 8000 tokens
```

## Usage Examples

### Configure Large Context Model

```yaml
models:
  "large-context-model":
    limits:
      context_window: 262144      # 256K total context window
      max_input_tokens: 200000    # 200K input limit (leaves room for response)
      requests_per_minute: 30     # Conservative rate limits
```

### Configure Small Fast Model

```yaml
models:
  "small-fast-model":
    limits:
      context_window: 8192        # 8K context window
      max_input_tokens: 6000      # 6K input limit
      requests_per_minute: 120    # Higher rate for smaller model
```

### Override Context Window via CLI

```bash
python -m src.core.cli \
  --default-backend openai \
  --force-context-window 8000
```

### Configure Multiple Models

```yaml
model_defaults:
  "gpt-4":
    limits:
      context_window: 128000
      max_input_tokens: 100000
  "gpt-3.5-turbo":
    limits:
      context_window: 16384
      max_input_tokens: 12000
  "claude-3-opus":
    limits:
      context_window: 200000
      max_input_tokens: 180000
```

## Error Handling

When limits are exceeded, the proxy returns a structured 400 error:

```json
{
  "detail": {
    "code": "input_limit_exceeded",
    "message": "Input token limit exceeded",
    "details": {
      "model": "your-model-name",
      "limit": 100000,
      "measured": 125432
    }
  }
}
```

### Error Response Fields

- **code**: Error code (`input_limit_exceeded`)
- **message**: Human-readable error message
- **details.model**: Model name that exceeded the limit
- **details.limit**: Configured token limit
- **details.measured**: Actual token count in the request

## Use Cases

### Cost Control

Prevent accidental large-context requests with expensive models:

```yaml
models:
  "expensive-model":
    limits:
      max_input_tokens: 50000  # Limit to 50K tokens to control costs
```

### Agent Compatibility

Ensure agents with long conversations don't exceed model limits:

```yaml
models:
  "agent-model":
    limits:
      context_window: 128000
      max_input_tokens: 100000  # Leave room for agent's response
```

### Performance Tuning

Optimize different models for different use cases:

```yaml
models:
  "fast-model":
    limits:
      context_window: 8192      # Small context for fast responses
  "quality-model":
    limits:
      context_window: 200000    # Large context for quality
```

### Multi-Tier Service

Configure different limits for different user tiers or applications:

```yaml
# Free tier
models:
  "free-tier-model":
    limits:
      max_input_tokens: 4000

# Premium tier
models:
  "premium-tier-model":
    limits:
      max_input_tokens: 100000
```

### Testing Compatibility

Test how agents behave with smaller context windows:

```bash
python -m src.core.cli \
  --default-backend openai \
  --force-context-window 4000  # Test with 4K context
```

### Debugging

Use fixed context windows to isolate issues:

```bash
python -m src.core.cli \
  --force-context-window 8000  # Fixed 8K context for debugging
```

## Implementation Notes

### Token Counting

- Uses model-specific tokenizers when available for accurate counting
- Falls back to generic tokenizers for unknown models
- Counts all message content, system prompts, and tool definitions

### Limit Types

- **context_window**: Total context window size (input + output)
- **max_input_tokens**: Maximum input tokens (recommended for enforcement)
- **max_output_tokens**: Maximum output tokens (handled by backend providers)

### Fallback Behavior

- If `max_input_tokens` is not specified, `context_window` is used as fallback
- If neither is specified, no limit is enforced
- Configuration supports both `backend:model` and plain `model` key formats

### Enforcement Points

- Input limits are enforced strictly at the front-end
- Output limits are handled by backend providers
- Enforcement happens before backend API calls to save costs

## Troubleshooting

**Limits not being enforced:**

- Verify limits are configured for the model
- Check that the model name matches the configuration key
- Review logs for limit enforcement messages
- Ensure the feature is not disabled

**Incorrect token counts:**

- Verify the correct tokenizer is being used for the model
- Check if special tokens are being counted
- Review logs for tokenization messages
- Consider if the model uses a non-standard tokenizer

**Requests being blocked incorrectly:**

- Verify the configured limits are appropriate for the model
- Check if the token count includes unexpected content
- Review the error response for measured vs limit tokens
- Consider increasing the limit if it's too restrictive

**Performance impact:**

- Token counting adds minimal overhead (<10ms per request)
- The benefit (preventing expensive API calls) far outweighs the cost
- Disable enforcement if not needed to eliminate overhead

**CLI override not working:**

- Verify the `--force-context-window` flag is being used
- Check that the value is a valid integer
- Review logs for override messages
- Ensure no configuration is overriding the CLI flag

## Related Features

- [Session Management](session-management.md) - Intelligent session continuity
- [Pytest Context Saving](pytest-context-saving.md) - Add context-saving flags
- [Edit Precision Tuning](edit-precision.md) - Automatic parameter adjustment
