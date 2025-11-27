# OpenRouter Backend

The OpenRouter backend provides access to a wide variety of models from multiple providers through a single API. OpenRouter acts as a unified gateway to models from OpenAI, Anthropic, Google, Meta, and many other providers.

## Overview

OpenRouter is a model aggregation service that provides access to dozens of models through a single API key. This makes it easy to experiment with different models without managing multiple API keys and accounts.

## Key Features

- Access to 50+ models from multiple providers
- Single API key for all models
- Unified pricing and billing
- Automatic failover between providers
- Model routing and load balancing
- Cost tracking and analytics

## Configuration

### Environment Variables

```bash
export OPENROUTER_API_KEY="sk-or-..."
```

### CLI Arguments

```bash
# Start proxy with OpenRouter as default backend
python -m src.core.cli --default-backend openrouter

# With specific model
python -m src.core.cli --default-backend openrouter --force-model anthropic/claude-3-5-sonnet
```

### YAML Configuration

```yaml
# config.yaml
backends:
  openrouter:
    type: openrouter

default_backend: openrouter
```

## Available Models

OpenRouter provides access to models from many providers. Model names follow the format `provider/model-name`:

### Popular Models

- **OpenAI**: `openai/gpt-4o`, `openai/gpt-4-turbo`, `openai/gpt-3.5-turbo`
- **Anthropic**: `anthropic/claude-3-5-sonnet`, `anthropic/claude-3-opus`, `anthropic/claude-3-haiku`
- **Google**: `google/gemini-pro`, `google/gemini-pro-vision`
- **Meta**: `meta-llama/llama-3-70b-instruct`, `meta-llama/llama-3-8b-instruct`
- **Mistral**: `mistralai/mistral-large`, `mistralai/mistral-medium`
- **Qwen**: `qwen/qwen-2-72b-instruct`, `qwen/qwen3-coder`

For a complete list of available models, visit [OpenRouter's model list](https://openrouter.ai/models).

## Usage Examples

### Basic Chat Completion

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_PROXY_KEY" \
  -d '{
    "model": "anthropic/claude-3-5-sonnet",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ]
  }'
```

### Using Different Providers

```bash
# OpenAI via OpenRouter
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openai/gpt-4o",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Anthropic via OpenRouter
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "anthropic/claude-3-opus",
    "messages": [{"role": "user", "content": "Hello"}]
  }'

# Meta Llama via OpenRouter
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "meta-llama/llama-3-70b-instruct",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

### With Model Parameters

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter:anthropic/claude-3-5-sonnet?temperature=0.7",
    "messages": [{"role": "user", "content": "Write a story"}]
  }'
```

## Use Cases

### Model Experimentation

OpenRouter is ideal for:

- Testing different models without multiple API keys
- Comparing model performance across providers
- Prototyping with various model capabilities
- Finding the best model for your use case

### Cost Optimization

Use OpenRouter to:

- Access cheaper alternatives to premium models
- Compare pricing across providers
- Track costs across multiple models
- Optimize spending with model routing

### Simplified Integration

Benefits include:

- Single API key for all providers
- Unified API format (OpenAI-compatible)
- No need to manage multiple accounts
- Automatic provider failover

### Model Name Rewrites

Route all GPT requests through OpenRouter:

```yaml
# config.yaml
model_aliases:
  - pattern: "^gpt-(.*)"
    replacement: "openrouter:openai/gpt-\\1"
```

Now any request for `gpt-4o` will be routed to `openrouter:openai/gpt-4o`.

## Pricing and Billing

OpenRouter uses a unified billing system:

- Pay-as-you-go pricing
- Different rates for different models
- Transparent cost tracking
- Usage analytics dashboard

Check current pricing at [OpenRouter's pricing page](https://openrouter.ai/docs#models).

## Model Parameters

You can specify model parameters using URI syntax:

```bash
# With temperature and top_p
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "openrouter:anthropic/claude-3-5-sonnet?temperature=0.7&top_p=0.9",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

See [URI Model Parameters](../features/uri-model-parameters.md) for more details.

## Troubleshooting

### 401 Unauthorized

- Verify your `OPENROUTER_API_KEY` is set correctly
- Check that the API key is valid and has credits
- Ensure you're using the correct authentication header

### 429 Rate Limit Exceeded

- OpenRouter has rate limits based on your account tier
- Consider upgrading your account for higher limits
- Use failover to switch to alternative models

### Model Not Found

- Verify the model name format is correct (`provider/model-name`)
- Check that the model is available on OpenRouter
- Some models may require special access or higher account tiers

### High Costs

- Monitor your usage on the OpenRouter dashboard
- Use cheaper models for simple tasks
- Enable cost tracking in the proxy
- Set up budget alerts on OpenRouter

## Identity Override

OpenRouter checks client identity headers. You may need to configure identity override:

```yaml
# config.yaml
identity:
  user_agent:
    mode: override
    override_value: "MyApp/1.0.0"
```

See [Client Identity Override](../features/identity-override.md) for more details.

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Route models through OpenRouter
- [Hybrid Backend](../features/hybrid-backend.md) - Combine OpenRouter with other backends
- [Client Identity Override](../features/identity-override.md) - Configure client identification

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Backend](openai.md)
- [Anthropic Backend](anthropic.md)
- [Gemini Backends](gemini.md)
