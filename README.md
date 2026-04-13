# LLM Interactive Proxy

[![CI (dev)](https://img.shields.io/github/actions/workflow/status/matdev83/llm-interactive-proxy/ci.yml?branch=dev&event=push&label=CI%20(dev)&cacheSeconds=300)](https://github.com/matdev83/llm-interactive-proxy/actions/workflows/ci.yml?query=branch%3Adev)
[![Coverage](https://img.shields.io/codecov/c/github/matdev83/llm-interactive-proxy?branch=main)](https://codecov.io/gh/matdev83/llm-interactive-proxy)
![Tests passing](https://img.shields.io/badge/Tests%20passing-100%25%20out%20of%2013195-brightgreen)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
[![License](https://img.shields.io/github/license/matdev83/llm-interactive-proxy?color=blue)](LICENSE)

Turn any compatible AI client into a safer, smarter, multi-provider agent platform.

`LLM Interactive Proxy` is a universal translation, routing, and control layer for modern AI clients. Point OpenAI-compatible apps, Anthropic tools, Gemini integrations, and agentic coding workflows at one local or shared endpoint, then gain routing, failover, built-in security, automated steering, session intelligence, observability, and cross-provider flexibility without rewriting your client.

If your current setup feels fragile, expensive, opaque, or locked to one vendor, this project is designed to change that.

It is a compatibility layer, a security layer, a traffic control plane, a debugging surface, and a workflow improver for serious agentic use.

> **Active Development**: This project is continuously evolving with new backends, routing features, and reliability improvements. See the [CHANGELOG](CHANGELOG.md) for the latest additions.

- **Keep your existing clients** - Change the endpoint, not the app.
- **Mix providers freely** - Route across APIs, plans, OAuth accounts, model families, and protocol styles.
- **Control agents in production** - Add guardrails, rewrites, diagnostics, and policy at the proxy layer.
- **Debug with evidence** - Inspect exact wire traffic instead of guessing from symptoms.

| Without the proxy | With LLM Interactive Proxy |
| --- | --- |
| Each client is tied to one provider stack | One endpoint can serve many clients and many backend families |
| Provider switching often means code or config churn | Change routing instead of rewriting integrations |
| Agent safety is scattered across tools | Centralize redaction, tool controls, sandboxing, and command protection |
| Debugging depends on incomplete logs | Inspect exact wire traffic with captures and diagnostics |
| Token costs grow with long sessions | Use intelligent context compression and smarter routing to reduce spend |
| Protocol mismatch blocks experimentation | Use cross-protocol conversion to bridge Anthropic, OpenAI, Gemini, and more |

## At a glance

Beyond basic forwarding, the proxy adds cross-protocol translation, tool safety, routing and failover, session-oriented features (including B2BUA-style handling), boundary-level CBOR captures, usage tracking, and built-in token-saving controls. Longer narratives, use-case lists, and feature tours live in the [User Guide](docs/user_guide/index.md).

- **One endpoint, many clients** - Keep existing OpenAI-, Anthropic-, and Gemini-style clients while changing routing behind the proxy. `/v1/responses` streaming emits official OpenAI Responses events (no legacy `response.chunk` fallback shape).
- **Token-saving that actually matters** - Shrink bloated sessions with stale-history compaction and content-aware tool-output compression.
- **Production-minded resilience** - Use retries, failover, health tracking, and safeguards that respect streaming semantics.
- **Operational visibility** - Inspect wire captures, diagnostics, and usage data instead of debugging blind.

## Token Savings

Long coding sessions tend to waste tokens in two different ways: old tool results remain in history, and fresh tool outputs are often much more verbose than the model needs. The proxy addresses both problems separately.

- **Context Compaction** - Replaces stale historical tool results with explicit stubs once newer results for the same resource exist later in the conversation.
- **Dynamic Tool Output Compression** - Reduces the size of the remaining tool outputs during request preparation using content-aware strategies.
- **Designed to work together** - Compaction removes outdated history first; dynamic compression then reduces the cost of the tool outputs that still matter.
- **Useful for real agent workloads** - Especially helpful for repeated file reads, large grep/search results, verbose test output, logs, diffs, and long debugging sessions.

Start with the [Token Saving Guide](docs/user_guide/features/token-saving.md) for the overall picture, then go deeper into [Context Compaction](docs/user_guide/features/context-compaction.md) and [Dynamic Tool Output Compression](docs/user_guide/features/dynamic-tool-output-compression.md).

## Resilience & Reliability

The proxy includes built-in resilience features for production use:

- **Smart retry and failover** - Automatic recovery from transient backend failures
- **Circuit breaker** - Temporarily excludes unhealthy backends to prevent repeated failures
- **Streaming protection** - Avoids retry after output has started, preventing corruption
- **Health monitoring** - Tracks backend availability and performance

Configure via the `resilience` section in `config.yaml` or see the [Failure Handling Guide](docs/user_guide/features/failure-handling.md). Request processing now runs through a single canonical manager path with no legacy split-handler fallback. `canonical_request_processing` provides the remaining runtime controls such as empty-stream recovery tuning.

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/matdev83/llm-interactive-proxy.git
cd llm-interactive-proxy
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux/macOS
source .venv/bin/activate

python -m pip install -e .[dev]
```

If you want OAuth-oriented optional connectors, install the `oauth` extra:

```bash
python -m pip install -e .[dev,oauth]
```

### 2. Export at least one provider credential

```bash
# Example: OpenAI
export OPENAI_API_KEY="your-key-here"
```

### 3. Start the proxy

```bash
python -m src.core.cli --default-backend openai:gpt-4o
```

The proxy listens on `http://localhost:8000` by default.

### 4. Point your client at the proxy instead of the vendor

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy-key",
)

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}],
)

print(response.choices[0].message.content)
```

See the full [Quick Start Guide](docs/user_guide/quick-start.md) for additional setup, auth, and backend examples.

### Auto-Append First Prompt

Automatically append text from a file to the first user message in each session. Useful for injecting context, instructions, or system prompts without modifying client code.

**Usage:**
```yaml
# config.yaml
auto_append_first_prompt_filename: "./prompts/context.txt"
```

Or via CLI: `--auto-append-first-prompt-file ./prompts/context.txt`

The file is loaded once at startup and appended to the first user message of every new session. See [Configuration Guide](docs/user_guide/configuration.md) for details.

## Supported Frontend Interfaces

The proxy exposes standard API surfaces so existing clients can often work with little or no code changes.

- **OpenAI Chat Completions** - `/v1/chat/completions`
- **OpenAI Responses** - `/v1/responses`
- **OpenAI Models** - `/v1/models`
- **Anthropic Messages** - `/anthropic/v1/messages`
- **Dedicated Anthropic server** - `http://host:<anthropic_port>/v1/messages` (only when `anthropic_port` / `--anthropic-port` / `ANTHROPIC_PORT` is set; often `8001`)
- **Google Gemini v1beta** - `/v1beta/models` and `:generateContent`
- **Diagnostics endpoint** - `/v1/diagnostics`
- **Backend reactivation endpoint** - `/v1/diagnostics/backends/{backend_instance}/reactivate`

See [Frontend API documentation](docs/user_guide/frontends/overview.md) for protocol details and compatibility notes.

## Supported Backends

The backend catalog keeps growing. Current documented backends include:

- [OpenAI](docs/user_guide/backends/openai.md)
- [OpenAI Codex](docs/user_guide/backends/openai-codex.md)
- [Anthropic](docs/user_guide/backends/anthropic.md)
- [Google Gemini](docs/user_guide/backends/gemini.md)
- [OpenRouter](docs/user_guide/backends/openrouter.md)
- [Nvidia](docs/user_guide/backends/nvidia.md)
- [ZAI (Zhipu AI)](docs/user_guide/backends/zai.md)
- [Alibaba Qwen](docs/user_guide/backends/qwen.md)
- [MiniMax](docs/user_guide/backends/minimax.md)
- [InternLM](docs/user_guide/backends/internlm.md)
- [ZenMux](docs/user_guide/backends/zenmux.md)
- [Moonshot AI / Kimi Code](docs/user_guide/backends/kimi-code.md)
- [Hybrid backend](docs/user_guide/features/hybrid-backend.md)
- [Cline](docs/user_guide/backends/cline.md)
- [Antigravity OAuth](docs/user_guide/backends/antigravity-oauth.md)
See the full [Backends Overview](docs/user_guide/backends/overview.md) for configuration and provider-specific notes.

## Routing & Model Selection

The proxy uses a flexible selector syntax for routing requests to backends:

**Basic format:** `backend:model`
```bash
--default-backend openai:gpt-4o
--default-backend anthropic:claude-3-5-sonnet
```

**Failover chains:** Use `|` to specify fallback backends
```bash
--default-backend "openai:gpt-4o|anthropic:claude-3-5-sonnet|openrouter:openai/gpt-4o"
```

**Weighted routing:** Use `^` to distribute traffic
```bash
--default-backend "[weight=3]openai:gpt-4^[weight=1]anthropic:claude-3-5-sonnet"
```
When a weighted branch fails before meaningful output starts, runtime recovery can
re-roll within the same request by excluding the failed branch and choosing from the remaining weighted leaves.

**With parameters:** Pass model parameters in the selector
```bash
--default-backend "openai:gpt-4o?temperature=0.5&max_tokens=2000"
```

See the [Technical Reference: Routing Selectors](docs/development_guide/routing-selectors.md) for detailed syntax rules and advanced usage.

## Access Modes

The proxy supports two operational modes with different security assumptions:

- **Single User Mode** - Default local-development mode with localhost-first behavior and support for OAuth connectors.
- **Multi User Mode** - Shared or production mode with stronger authentication expectations and tighter connector rules.

Quick examples:

```bash
# Single User Mode
python -m src.core.cli

# Multi User Mode
python -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1,key2
```

See [Access Modes](docs/user_guide/access-modes.md) for the security model and deployment guidance.

## Documentation Map
- **[Quick Start](docs/user_guide/quick-start.md)** - Get running fast
- **[User Guide](docs/user_guide/index.md)** - End-user documentation and feature catalog
- **[Configuration Guide](docs/user_guide/configuration.md)** - Flags, config, and operational settings
- **[Token Saving Guide](docs/user_guide/features/token-saving.md)** - Understand context compaction and dynamic tool-output compression
- **[Frontend Overview](docs/user_guide/frontends/overview.md)** - Choose the right API surface
- **[Backends Overview](docs/user_guide/backends/overview.md)** - Provider setup and switching
- **[Security Docs](docs/user_guide/security/authentication.md)** - Authentication and key-handling guidance
- **[Development Guide](docs/development_guide/index.md)** - Architecture, local development, testing, and contributing
- **[CHANGELOG](CHANGELOG.md)** - Release history
- **[CONTRIBUTING](CONTRIBUTING.md)** - Contribution guidelines

## Development
```bash
# Run the test suite
python -m pytest

# Lint and auto-fix
python -m ruff check --fix .

# Format
python -m black .
```
See the [Development Guide](docs/development_guide/index.md) for architecture, contribution workflow, and extra dev scripts.

## Support
[GitHub Issues](https://github.com/matdev83/llm-interactive-proxy/issues) and [Discussions](https://github.com/matdev83/llm-interactive-proxy/discussions).
## License
This project is licensed under the [GNU AGPL v3.0 or later](LICENSE).
