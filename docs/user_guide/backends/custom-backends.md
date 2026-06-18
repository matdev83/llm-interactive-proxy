# Custom Backends

The LLM Interactive Proxy supports creating custom backend configurations for providers not included in the default set. This allows you to integrate with any OpenAI-compatible API or create specialized configurations for existing providers.

## Overview

Custom backends enable you to:

- Connect to proprietary or internal LLM services
- Configure specialized endpoints for existing providers
- Create custom model configurations with specific limits
- Integrate with new LLM providers as they emerge

## Creating a Custom Backend

### Directory Structure

Custom backends are configured in YAML files under `config/backends/`:

```
config/
└── backends/
    └── my-custom-backend/
        └── backend.yaml
```

### Basic Backend Configuration

Create a `backend.yaml` file with the following structure:

```yaml
# config/backends/my-custom-backend/backend.yaml
backend_type: "custom"
api_base_url: "https://api.example.com/v1"
api_key_env_var: "MY_CUSTOM_API_KEY"

models:
  "my-model-name":
    limits:
      context_window: 128000
      max_input_tokens: 100000
      max_output_tokens: 28000
      requests_per_minute: 60
      tokens_per_minute: 1000000
```

### Configuration Fields

#### Required Fields

- **backend_type**: Type of backend (use `"custom"` for custom backends)
- **api_base_url**: Base URL for the API endpoint
- **api_key_env_var**: Environment variable name containing the API key

#### Optional Fields

- **models**: Dictionary of model configurations
- **default_model**: Default model to use if none specified
- **timeout**: Request timeout in seconds
- **max_retries**: Maximum number of retry attempts

### Model Configuration

Each model can have the following configuration:

```yaml
models:
  "model-name":
    limits:
      context_window: 128000        # Total context window (tokens)
      max_input_tokens: 100000      # Maximum input tokens
      max_output_tokens: 28000      # Maximum output tokens
      requests_per_minute: 60       # Rate limit (requests)
      tokens_per_minute: 1000000    # Rate limit (tokens)
    parameters:
      temperature: 0.7              # Default temperature
      top_p: 0.9                    # Default top_p
```

## Usage Examples

### Example 1: Internal LLM Service

```yaml
# config/backends/internal-llm/backend.yaml
backend_type: "custom"
api_base_url: "https://internal-llm.company.com/v1"
api_key_env_var: "INTERNAL_LLM_API_KEY"

models:
  "company-gpt-large":
    limits:
      context_window: 32000
      max_input_tokens: 24000
      max_output_tokens: 8000
      requests_per_minute: 100
```

Usage:

```bash
export INTERNAL_LLM_API_KEY="your-key"
python -m src.core.cli --default-backend internal-llm
```

### Example 2: Specialized OpenAI Configuration

```yaml
# config/backends/openai-specialized/backend.yaml
backend_type: "custom"
api_base_url: "https://api.openai.com/v1"
api_key_env_var: "OPENAI_API_KEY"

models:
  "gpt-4-specialized":
    limits:
      context_window: 8000          # Restricted context
      max_input_tokens: 6000
      max_output_tokens: 2000
      requests_per_minute: 30       # Conservative rate limits
    parameters:
      temperature: 0.3              # Lower temperature for precision
```

### Example 3: Multiple Model Variants

```yaml
# config/backends/multi-model/backend.yaml
backend_type: "custom"
api_base_url: "https://api.provider.com/v1"
api_key_env_var: "PROVIDER_API_KEY"

models:
  "fast-model":
    limits:
      context_window: 4096
      max_input_tokens: 3000
      requests_per_minute: 120
    parameters:
      temperature: 0.8
  
  "accurate-model":
    limits:
      context_window: 32000
      max_input_tokens: 24000
      requests_per_minute: 30
    parameters:
      temperature: 0.2
  
  "balanced-model":
    limits:
      context_window: 16000
      max_input_tokens: 12000
      requests_per_minute: 60
    parameters:
      temperature: 0.5
```

## Advanced Configuration

### Custom Headers

Add custom headers to all requests:

```yaml
backend_type: "custom"
api_base_url: "https://api.example.com/v1"
api_key_env_var: "EXAMPLE_API_KEY"

headers:
  X-Custom-Header: "value"
  X-Organization-ID: "org-123"
```

### Authentication Methods

#### Bearer Token (Default)

```yaml
api_key_env_var: "MY_API_KEY"
auth_type: "bearer"  # Default
```

#### Custom Header

```yaml
api_key_env_var: "MY_API_KEY"
auth_type: "custom"
auth_header: "X-API-Key"
```

### Timeout and Retry Configuration

```yaml
backend_type: "custom"
api_base_url: "https://api.example.com/v1"
api_key_env_var: "EXAMPLE_API_KEY"

timeout: 60              # Request timeout in seconds
max_retries: 3           # Maximum retry attempts
retry_delay: 1.0         # Delay between retries (seconds)
```

## Context Window Enforcement

Custom backends support context window enforcement to prevent excessive token usage:

```yaml
models:
  "large-context-model":
    limits:
      context_window: 262144      # 256K total context
      max_input_tokens: 200000    # 200K input limit
      max_output_tokens: 62144    # 62K output limit
```

When a request exceeds `max_input_tokens`, the proxy returns a 400 error:

```json
{
  "detail": {
    "type": "invalid_request_error",
    "code": "context_length_exceeded",
    "param": "input",
    "message": "Your input exceeds the context window of this model. Please adjust your input and try again.",
    "details": {
      "model": "large-context-model",
      "limit": 200000,
      "measured": 225000
    }
  }
}
```

## Use Cases

### Development and Testing

Create custom backends for:

- Testing against local LLM instances
- Mocking LLM responses for integration tests
- Prototyping with experimental models

### Enterprise Integration

Use custom backends to:

- Connect to internal LLM services
- Enforce company-specific rate limits
- Add custom authentication and headers
- Integrate with proprietary models

### Cost Control

Configure custom backends to:

- Set strict context window limits
- Enforce conservative rate limits
- Route to cost-effective alternatives
- Track usage per model variant

### Multi-Tier Service

Create different backend configurations for:

- Free tier users (strict limits)
- Premium users (higher limits)
- Enterprise users (custom configurations)

## Troubleshooting

### Backend Not Found

- Verify the backend directory exists under `config/backends/`
- Check that `backend.yaml` is in the correct location
- Ensure the backend name matches the directory name

### Authentication Errors

- Verify the environment variable is set correctly
- Check that the API key is valid
- Ensure the `auth_type` matches the provider's requirements

### Rate Limiting Issues

- Adjust `requests_per_minute` and `tokens_per_minute` in model limits
- Check provider's actual rate limits
- Consider using API Key Rotation (via multiple backend instances) with load balancing

### Context Window Errors

- Verify `max_input_tokens` is set correctly
- Ensure `context_window` is larger than `max_input_tokens`
- Check that token counting is accurate for your provider

## Best Practices

1. **Start with Defaults**: Base your configuration on existing backends
2. **Test Thoroughly**: Validate your configuration with test requests
3. **Document Limits**: Clearly document rate limits and context windows
4. **Use Environment Variables**: Never hardcode API keys in config files
5. **Monitor Usage**: Track token usage and costs
6. **Version Control**: Keep backend configurations in version control (without secrets)

## Related Features

- [Context Window Enforcement](../features/context-window-enforcement.md) - Enforce token limits
- [Model Name Rewrites](../features/model-name-rewrites.md) - Route to custom backends
- [URI Model Parameters](../features/uri-model-parameters.md) - Override model parameters

## Related Documentation

- [Backend Overview](overview.md)
- [Configuration Guide](../configuration.md)
