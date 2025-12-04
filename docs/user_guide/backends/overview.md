# Backend Overview

The LLM Interactive Proxy supports multiple backend providers, allowing you to route requests to different LLM services while maintaining a consistent front-end API. This flexibility enables you to choose the best provider for your use case, switch providers without changing client code, and implement failover strategies.

## Supported Backends

The proxy supports the following backend providers out of the box:

| Backend ID | Provider | Authentication | Best For |
|------------|----------|----------------|----------|
| `openai` | OpenAI | API Key | Production applications, standard OpenAI models |
| `openai-codex` | OpenAI (ChatGPT/Codex OAuth) | Local OAuth token | Using ChatGPT login instead of API key |
| `anthropic` | Anthropic | API Key | Claude models via standard API |
| `anthropic-oauth` | Anthropic (OAuth) | Local OAuth token | Claude via OAuth credential flow |
| `cline` | Cline | Local OAuth token | Internal development & debugging |
| `gemini` | Google Gemini | API Key | Metered API usage, production apps |
| `gemini-oauth-plan` | Google Gemini (CLI) | OAuth | Users with Google One subscription |
| `gemini-oauth-free` | Google Gemini (CLI) | OAuth | Free tier users |
| `gemini-cli-cloud-project` | Google Gemini (GCP) | OAuth + GCP Project | Enterprise, team workflows, central billing |
| `gemini-cli-acp` | Google Gemini (CLI Agent) | OAuth | AI agent workflows, project-aware coding |
| `openrouter` | OpenRouter | API Key | Access to many hosted models |
| `zenmux` | ZenMux | API Key | OpenAI-compatible ZenMux router |
| `zai` | ZAI | API Key | Zhipu/Z.ai access |
| `zai-coding-plan` | ZAI Coding Plan | API Key | Coding-specific workflows |
| `minimax` | Minimax | API Key | Minimax AI models |
| `qwen-oauth` | Alibaba Qwen | Local OAuth token | Qwen CLI OAuth |
| `qwen-oauth` | Alibaba Qwen | Local OAuth token | Qwen CLI OAuth |
| `hybrid` | Virtual (orchestrates two models) | Inherits from sub-backends | Two-phase reasoning + execution |
| `gemini-oauth-antigravity` | Google Gemini (Antigravity) | Antigravity Token | Internal debugging (Gemini models) |

## Frontend APIs

The proxy exposes multiple frontend APIs where clients connect. Each frontend implements a different LLM provider's API specification.

For detailed frontend API documentation, see the [Frontend Overview](../frontends/overview.md):

- [OpenAI Chat Completions](../frontends/openai-chat-completions.md) - `/v1/chat/completions`
- [OpenAI Responses API](../frontends/openai-responses.md) - `/v1/responses`
- [Anthropic Messages](../frontends/anthropic.md) - `/anthropic/v1/messages`
- [Google Gemini v1beta](../frontends/gemini.md) - `/v1beta/models`

## Choosing a Backend

When selecting a backend, consider:

- **Cost**: API key-based backends typically charge per token, while OAuth-based backends may have subscription or free tier limits
- **Performance**: Different providers have different latency and throughput characteristics
- **Model Availability**: Each provider offers different models with varying capabilities
- **Authentication**: Choose between API keys (simpler) or OAuth (may offer free tiers)
- **Use Case**: Some backends are optimized for specific tasks (e.g., `zai-coding-plan` for coding)

## Configuration

Backends are configured through environment variables and the proxy configuration file:

### Basic Setup

```bash
# Set API keys for the backends you want to use
export OPENAI_API_KEY="sk-..."
export ANTHROPIC_API_KEY="sk-ant-..."
export GEMINI_API_KEY="AIza..."
export OPENROUTER_API_KEY="sk-or-..."
export ZENMUX_API_KEY="..."
export ZAI_API_KEY="..."
export MINIMAX_API_KEY="..."

# For GCP-based Gemini
export GOOGLE_CLOUD_PROJECT="your-project-id"
```

### Starting the Proxy

```bash
# Start with a specific default backend
python -m src.core.cli --default-backend openai

# Or specify in config file
python -m src.core.cli --config config/config.yaml
```

### Config File Example

```yaml
# config.yaml
backends:
  openai:
    type: openai
  anthropic:
    type: anthropic
  gemini:
    type: gemini

default_backend: openai
```

## Switching Backends

You can switch backends dynamically during a session using in-chat commands:

```
!/backend(anthropic)
!/model(claude-3-5-sonnet-20241022)
```

Or use one-off commands for a single request:

```
!/oneoff(openrouter:qwen/qwen3-coder)
```

## Backend-Specific Documentation

For detailed configuration and usage information for each backend, see:

- [OpenAI Backend](openai.md)
- [Anthropic Backend](anthropic.md)
- [Gemini Backends](gemini.md)
- [Cline Backend](cline.md)
- [OpenRouter Backend](openrouter.md)
- [ZAI Backend](zai.md)
- [Qwen Backend](qwen.md)
- [MiniMax Backend](minimax.md)
- [ZenMux Backend](zenmux.md)
- [Custom Backends](custom-backends.md)

## Related Features

- [Model Name Rewrites](../features/model-name-rewrites.md) - Transform model names dynamically
- [Hybrid Backend](../features/hybrid-backend.md) - Use two models in sequence
- [URI Model Parameters](../features/uri-model-parameters.md) - Specify parameters in model strings
