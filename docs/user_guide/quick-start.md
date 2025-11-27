# Quick Start Guide

Get the LLM Interactive Proxy up and running in minutes.

## Prerequisites

- Python 3.10 or higher
- API keys for the LLM providers you want to use

## Installation

1. Clone the repository:

   ```bash
   git clone https://github.com/matdev83/llm-interactive-proxy.git
   cd llm-interactive-proxy
   ```

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # On Windows
   .venv\Scripts\activate
   # On Linux/Mac
   source .venv/bin/activate
   ```

1. Install dependencies:

   ```bash
   ./.venv/Scripts/python.exe -m pip install -e .[dev]
   ```

## Configuration

### Step 1: Set Up API Keys

Export the API keys for the providers you plan to use. You only need to set keys for the backends you'll actually use:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...

# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# Google Gemini
export GEMINI_API_KEY=...

# OpenRouter
export OPENROUTER_API_KEY=sk-or-...

# ZenMux
export ZENMUX_API_KEY=...

# Z.AI
export ZAI_API_KEY=...

# MiniMax
export MINIMAX_API_KEY=...

# GCP-based Gemini backend
export GOOGLE_CLOUD_PROJECT=your-project-id
```

### Step 2: Start the Proxy

Start the proxy with your preferred backend:

```bash
python -m src.core.cli --default-backend openai
```

The proxy will start on `http://localhost:8000` by default.

## Connecting Your Client

### OpenAI-Compatible Clients

Point your OpenAI-compatible tools to the proxy:

```bash
export OPENAI_API_BASE=http://localhost:8000/v1
export OPENAI_API_KEY=<your-proxy-key>  # Only if auth is enabled
```

### Anthropic Clients (Claude Code)

Configure Anthropic clients to use the proxy:

```bash
export ANTHROPIC_API_URL=http://localhost:8001
export ANTHROPIC_API_KEY=<your-proxy-key>  # Only if auth is enabled
```

Note: Anthropic compatibility is exposed both at `/anthropic/...` on the main port (8000) and on a dedicated Anthropic port (defaults to main port + 1, i.e., 8001). Override via `ANTHROPIC_PORT` environment variable.

### Gemini Clients

Gemini clients can call the `/v1beta/...` endpoints on `http://localhost:8000`.

## Useful CLI Flags

Customize the proxy behavior with these common flags:

- `--host 0.0.0.0` - Bind to all network interfaces (default: 127.0.0.1)
- `--port 8000` - Change the port (default: 8000)
- `--config config/config.example.yaml` - Load a saved configuration file
- `--disable-auth` - Disable authentication for local-only use (forces host=127.0.0.1)
- `--force-model MODEL_NAME` - Override all client-requested models (e.g., `--force-model gemini-2.5-pro`)
- `--force-context-window TOKENS` - Override context window size for all models (e.g., `--force-context-window 8000`)
- `--capture-file wire.log` - Record requests/responses for debugging (see [Wire Capture](debugging/wire-capture.md))
- `--disable-dangerous-git-commands-protection` - Disable protection against dangerous git commands
- `--strict-command-detection` - Only process commands on the last non-blank line
- `--enable-pytest-compression` - Enable pytest output compression
- `--enable-pytest-context-saving` - Automatically add `-r fE` and `-q` flags to pytest commands
- `--fix-think-tags` - Correct improperly formatted `<think>` tags in model responses
- `--enable-edit-precision` / `--disable-edit-precision` - Control automated edit-precision tuning
- `--hybrid-backend-repeat-messages` - Enable message repetition in hybrid backend execution phase
- `--reasoning-injection-probability VALUE` - Set probability (0.0-1.0) of using reasoning model in hybrid backend

## Using the Proxy

### Switching Backends and Models

You can switch backends and models on the fly using slash commands in your chat:

```text
!/backend(openai)
!/model(gpt-4o-mini)
!/oneoff(openrouter:qwen/qwen3-coder)
```

### Adjusting Reasoning Behavior

Control reasoning behavior with reasoning alias commands:

```text
!/max          # High reasoning mode (more thoughtful responses)
!/medium       # Medium reasoning mode (balanced approach)
!/low          # Low reasoning mode (faster, less intensive)
!/no-think     # Disable reasoning for direct, quick responses
```

Aliases: `!/no-thinking`, `!/no-reasoning`, `!/disable-thinking` also work for disabling reasoning.

## Next Steps

- **Configure Advanced Features**: See [Configuration Guide](configuration.md) for detailed configuration options
- **Explore Features**: Browse the [Features](features/) directory to learn about specific capabilities
- **Set Up Backends**: Review [Backend Documentation](backends/overview.md) for provider-specific setup
- **Enable Debugging**: Learn about [Wire Capture](debugging/wire-capture.md) and [CBOR Capture](debugging/cbor-capture.md)
- **Secure Your Proxy**: Read about [Authentication](security/authentication.md) and [Security Best Practices](security/key-hygiene.md)

## Troubleshooting

If you encounter issues:

1. Check that your API keys are correctly set
2. Verify the proxy is running on the expected port
3. Ensure your client is pointing to the correct URL
4. Review the [Troubleshooting Guide](debugging/troubleshooting.md) for common issues
5. Check the proxy logs for error messages

## Getting Help

- **Issues**: Report bugs or request features on [GitHub Issues](https://github.com/matdev83/llm-interactive-proxy/issues)
- **Documentation**: Browse the full [User Guide](index.md) for detailed information
- **Development**: See the [Development Guide](../development_guide/index.md) if you want to contribute
