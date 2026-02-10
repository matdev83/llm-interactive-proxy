# LLM Interactive Proxy

![CI](https://img.shields.io/github/actions/workflow/status/matdev83/llm-interactive-proxy/ci.yml?branch=main&event=push&label=CI&cacheSeconds=300)
![Architecture Check](https://img.shields.io/github/actions/workflow/status/matdev83/llm-interactive-proxy/architecture-check.yml?branch=main&event=push&label=Architecture&cacheSeconds=300)
[![Coverage](https://img.shields.io/codecov/c/github/matdev83/llm-interactive-proxy?branch=main&token=)](https://codecov.io/gh/matdev83/llm-interactive-proxy)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License](https://img.shields.io/github/license/matdev83/llm-interactive-proxy?color=blue)](LICENSE)

A swiss-army knife proxy that sits between your LLM client and provider—giving you a universal adapter, cost optimization, and full visibility with zero code changes.

## Quick Start

### 1. Installation

```bash
git clone https://github.com/matdev83/llm-interactive-proxy.git
cd llm-interactive-proxy
python -m venv .venv
source .venv/Scripts/activate  # Windows: .venv\Scripts\activate
pip install -e .[dev]
```

### 2. Start the Proxy

```bash
export OPENAI_API_KEY="your-key-here"
python -m src.core.cli --default-backend openai:gpt-4o
```

### 3. Point Your Client at the Proxy

```python
# Instead of direct API calls:
from openai import OpenAI
client = OpenAI(api_key="your-key")

# Use the proxy (base_url only):
from openai import OpenAI
client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy-key"  # Proxy handles real authentication
)

# Now use normally - requests go through the proxy
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

That's it. All your existing code works unchanged—the proxy handles routing, translation, and monitoring transparently.

See [Quick Start Guide](docs/user_guide/quick-start.md) for detailed configuration.

## Why Use LLM Interactive Proxy?

**One configuration. Any client. Any provider.**

Stop rewriting your code every time you want to try a different LLM. Stop managing API keys in a dozen different tools. Stop wondering why your agent is stuck in an infinite loop or why your API bill suddenly spiked.

### Solve Real Problems

**Tired of juggling multiple LLM subscriptions?**  
Connect all your premium accounts—GPT Plus/Pro, Gemini Advanced, Qwen, GLM Code, and more—through one endpoint. Use them all without switching tools.

**Worried about agent misbehavior?**  
Fix stuck agents with automatic loop detection. Reduce token costs with intelligent context compression. Get a second opinion mid-conversation by switching models seamlessly.

**Need more control over what LLMs actually do?**  
Rewrite prompts and responses on-the-fly without touching client code. Block dangerous git commands before they execute. Add a "guardian angel" model that monitors and helps when your primary model drifts off track.

**Want visibility into what's happening?**  
Capture every request and response in CBOR format. Debug issues, audit usage, and understand exactly what your LLM apps are doing.

Zero changes to your client code. Just point it at the proxy and gain control.

## Key Capabilities

### Universal Connectivity
- **Protocol Translation** — Use OpenAI SDK with Anthropic, Claude client with Gemini, any combination
- **Subscription Consolidation** — Leverage all your premium LLM accounts through one endpoint
- **Flexible Deployment** — Single-user mode for development, multi-user mode for production

### Cost & Performance Optimization
- **Smart Routing** — Rotate API keys to maximize free tiers, automatically fallback to cheaper models
- **Context Window Compression** — Reduce token usage and improve inference speed without losing quality
- **Full Observability** — Wire capture, usage tracking, token counting, performance metrics

### Intelligent Session Control
- **Loop Detection** — Automatically detect and resolve infinite loops and repetitive patterns
- **Dynamic Model Switching** — Change models mid-conversation for diverse perspectives without losing context
- **Guardian Angel** — Deploy a secondary model to monitor sessions and assist when the primary model struggles

### Behavioral Customization
- **Prompt & Response Rewriting** — Modify content on-the-fly to fine-tune agent behavior
- **Tool Call Reactors** — Override and intercept tool calls to suppress unwanted behaviors
- **Usage Limits** — Enforce quotas and control resource consumption

### Security & Safety
- **Key Isolation** — Configure API keys once, never expose them to clients
- **Directory Sandboxing** — Restrict LLM tool access to designated safe directories
- **Command Protection** — Block harmful operations like aggressive git commands
- **Tool Access Control** — Fine-grained control over which tools LLMs can invoke

### Enterprise Features
- **B2BUA Session Isolation** — Internal session identity generation and strict trust boundaries (enabled by default; use `--disable-b2bua-session-handling` to opt out)

See [User Guide](docs/user_guide/index.md) for the complete feature list.

## Architecture

```mermaid
graph TD
    subgraph "Clients"
        A[OpenAI Client]
        B[OpenAI Responses API Client]
        C[Anthropic Client]
        D[Gemini Client]
        E[Any LLM App]
    end

    subgraph "LLM Interactive Proxy"
        FE["Front-end APIs<br/>(OpenAI, Anthropic, Gemini)"]
        Core["Core Proxy Logic<br/>(Routing, Translation, Safety)"]
        BE["Back-end Connectors<br/>(OpenAI, Anthropic, Gemini, etc.)"]
        FE --> Core --> BE
    end

    subgraph "Providers"
        P1[OpenAI API]
        P2[Anthropic API]
        P3[Google Gemini API]
        P4[OpenRouter API]
    end

    A --> FE
    B --> FE
    C --> FE
    D --> FE
    BE --> P1
    BE --> P2
    BE --> P3
    BE --> P4
```

## Documentation

- **[User Guide](docs/user_guide/index.md)** - Feature documentation, configuration, backends, debugging
- **[Development Guide](docs/development_guide/index.md)** - Architecture, building, testing, contributing
- **[Configuration Guide](docs/user_guide/configuration.md)** - Complete parameter reference
- **[CHANGELOG](CHANGELOG.md)** - Version history and updates
- **[CONTRIBUTING](CONTRIBUTING.md)** - Contribution guidelines

## Supported Front-end Interfaces

The proxy exposes multiple standard API surfaces, allowing you to use your favorite clients with any backend:

- **OpenAI Chat Completions** (`/v1/chat/completions`) - Compatible with OpenAI SDKs and most tools.
- **OpenAI Responses** (`/v1/responses`) - Optimized for structured output generation.
- **OpenAI Models** (`/v1/models`) - Unified model discovery across all backends.
- **[Anthropic Messages](docs/user_guide/backends/anthropic.md#using-anthropic-messages-api-directly)** (`/anthropic/v1/messages`) - Native support for Claude clients/SDKs.
- **Dedicated Anthropic Server** (`http://host:8001/v1/messages`) - Drop-in replacement for Anthropic API on a separate port (default: 8001).
- **Google Gemini v1beta** (`/v1beta/models`, `:generateContent`) - Native support for Gemini tools.

See [Front-End APIs Overview](docs/user_guide/backends/overview.md#front-end-apis) for more details.

## Supported Backends

- **[OpenAI (Legacy)](docs/user_guide/backends/openai.md)** (GPT-4, GPT-4o, o1, standard Chat Completions)
- **[OpenAI Responses API](docs/user_guide/backends/openai.md)** (Optimized for structured output generation)
- **[Anthropic](docs/user_guide/backends/anthropic.md)** (Claude 3.5 Sonnet, Opus, Haiku)
- **[Google Gemini](docs/user_guide/backends/gemini.md)** (API Key, OAuth, GCP, Vertex AI, Auto-OAuth)
- **[OpenRouter](docs/user_guide/backends/openrouter.md)** (Access to 100+ models)

- **[ZAI (Zhipu AI)](docs/user_guide/backends/zai.md)** (GLM models, including support for the GLM Coding Plan)
- **[Alibaba Qwen](docs/user_guide/backends/qwen.md)** (Coding-optimized LLM models)
- **[MiniMax](docs/user_guide/backends/minimax.md)** (Hailuo AI reasoning models)
- **[InternLM](docs/user_guide/backends/internlm.md)** (InternLM AI models with API key rotation)
- **[ZenMux](docs/user_guide/backends/zenmux.md)** (Unified model aggregator)
- **[Moonshot AI](docs/user_guide/backends/kimi-code.md)** (Kimi models, including Kimi Code for coding)
- **[Cline](docs/user_guide/backends/cline.md)** (Specialized debugging backend)
- **[Hybrid](docs/user_guide/features/hybrid-backend.md)** (Virtual backend for two-phase reasoning)
- **[Antigravity](docs/user_guide/backends/antigravity-oauth.md)** (Internal debugging backends for Gemini/Claude)

See [Backends Overview](docs/user_guide/backends/overview.md) for full details and configuration.

## Access Modes

The proxy supports two operational modes to enforce appropriate security boundaries:

- **Single User Mode** (default): For local development. Allows OAuth connectors, optional authentication, localhost-only binding.
- **Multi User Mode**: For production/shared deployments. Blocks OAuth connectors, requires authentication for remote access, allows any IP binding.

### Quick Examples

```bash
# Single User Mode (default) - local development
./.venv/Scripts/python.exe -m src.core.cli

# Multi User Mode - production deployment
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1,key2
```

See [Access Modes User Guide](docs/user_guide/access-modes.md) for detailed documentation.

## Support

- [GitHub Issues](https://github.com/matdev83/llm-interactive-proxy/issues) - Report bugs or request features
- [Discussions](https://github.com/matdev83/llm-interactive-proxy/discussions) - Ask questions and share ideas

## License

This project is licensed under the [GNU AGPL v3.0 or later](LICENSE).

## Development

```bash
# Run tests
python -m pytest

# Run linter
python -m ruff --fix check .

# Format code
python -m black .
```

See [Development Guide](docs/development_guide/index.md) for more details.
