# Codebuff Quick Start Guide

Get started with the Codebuff backend in 5 minutes.

## What is Codebuff?

Codebuff is a coding agent platform that uses AI models to assist with software development. The LLM Interactive Proxy includes a WebSocket server that implements the Codebuff protocol, allowing Codebuff clients to route their requests through the proxy's backend infrastructure.

## Quick Setup

### 1. Configure the Proxy

Create a configuration file or use the example:

```bash
cp config/codebuff.example.yaml config/my-codebuff.yaml
```

Edit `config/my-codebuff.yaml`:

```yaml
codebuff:
  enabled: true  # Enable Codebuff WebSocket server
  websocket_path: "/ws"
  heartbeat_timeout_seconds: 60
  max_connections: 1000

backends:
  default_backend: "openai"
  openai:
    timeout: 120
```

### 2. Set API Keys

```bash
# Windows
set OPENAI_API_KEY=your-key-here

# Linux/Mac
export OPENAI_API_KEY=your-key-here
```

### 3. Start the Proxy

```bash
python -m src.core.cli --config config/my-codebuff.yaml
```

You should see:

```text
INFO: Codebuff WebSocket server enabled on /ws
INFO: Server started on http://0.0.0.0:8000
```

### 4. Connect Your Codebuff Client

Configure your Codebuff client to use the proxy:

```bash
codebuff --backend-url ws://localhost:8000/ws
```

That's it! Your Codebuff client is now routing through the proxy.

## Disclaimer

### IMPORTANT LEGAL NOTICE - READ CAREFULLY BEFORE USING THE CODEBUFF-COMPATIBLE BACKEND

1. **Non-Affiliation**: This project is an independent open-source initiative. It is **not affiliated with, endorsed by, authorized by, or in any way officially connected to** Codebuff or any of their subsidiaries or affiliates. All product and company names are trademarks™ or registered® trademarks of their respective holders. Use of them does not imply any affiliation with or endorsement by them.

2. **No Liability**: The authors, contributors, and maintainers of this project hold **no responsibility or liability** for any consequences arising from the use of this backend in violation of these rules, or for any violations of third-party Terms of Service resulting from such use.

3. **User Responsibility**: You accept full responsibility for ensuring your use of this tool complies with all applicable laws and third-party agreements.

4. **Compliance with Provider Terms**: Users of the Codebuff-compatible backend connector are strictly required to respect all related Terms of Service (ToS) and other agreements with Codebuff and any backend providers. You are solely responsible for verifying that your use of this software is compatible with those agreements.

5. **Indemnification**: You agree to indemnify, defend, and hold harmless the authors and contributors of this project from and against any and all claims, liabilities, damages, losses, or expenses, including legal fees and costs, arising out of or in any way connected with your access to or use of the Codebuff-compatible backend.

**If you do not agree to these terms, do not use the Codebuff-compatible backend interface.**

## What You Get

- **Multiple Backends**: Route to OpenAI, Anthropic, Gemini, or any supported backend
- **Model Override**: Force specific models regardless of client defaults
- **Streaming Responses**: Real-time LLM output
- **Session Management**: Automatic session tracking and cleanup
- **File Context**: Initialize sessions with project files
- **All Proxy Features**: Access to all proxy features (wire capture, middleware, etc.)

## Configuration

The Codebuff backend can be configured through the main proxy configuration file:

```yaml
codebuff:
  enabled: true                      # Enable/disable Codebuff WebSocket server
  websocket_path: "/ws"              # WebSocket endpoint path
  heartbeat_timeout_seconds: 60      # Client heartbeat timeout
  max_connections: 1000              # Maximum concurrent connections

backends:
  default_backend: "openai"          # Default backend to use
  openai:
    timeout: 120                     # Request timeout in seconds
    model: "gpt-4"                   # Default model
```

### Configuration Options

- **enabled**: Set to `true` to enable the Codebuff WebSocket server
- **websocket_path**: The URL path where the WebSocket server listens (default: `/ws`)
- **heartbeat_timeout_seconds**: How long to wait for client heartbeat before disconnecting (default: 60)
- **max_connections**: Maximum number of concurrent WebSocket connections (default: 1000)

### Backend Configuration

Configure any supported backend:

```yaml
backends:
  default_backend: "anthropic"
  anthropic:
    timeout: 120
    model: "claude-3-5-sonnet-20241022"
```

## Usage Examples

### Basic Connection

Connect a Codebuff client to the proxy:

```bash
# Start the proxy
python -m src.core.cli --config config/my-codebuff.yaml

# Connect Codebuff client
codebuff --backend-url ws://localhost:8000/ws
```

### Custom Port and Path

```yaml
# config.yaml
server:
  host: "0.0.0.0"
  port: 9000

codebuff:
  enabled: true
  websocket_path: "/codebuff"
```

```bash
# Connect to custom endpoint
codebuff --backend-url ws://localhost:9000/codebuff
```

### Using Different Backends

```yaml
# Use Gemini backend
backends:
  default_backend: "gemini-oauth"
  gemini-oauth:
    model: "gemini-2.0-flash-exp"
    timeout: 120
```

### Session with File Context

```python
# Client sends init action with file context
{
  "type": "action",
  "txid": 1,
  "data": {
    "type": "init",
    "fingerprintId": "project-123",
    "fileContext": {
      "src/main.py": "def main():\n    pass",
      "README.md": "# My Project"
    }
  }
}
```

## Use Cases

- **One proxy for every teammate**: Ship a pre-baked config so anyone can point Codebuff to your proxy without additional setup.
- **Backend steering**: Override the default Codebuff model and route requests to the provider you choose (OpenAI, Anthropic, Gemini, etc.).
- **Debugging tool calls**: Capture WebSocket traffic and inspect tool-call payloads when diagnosing client/backend mismatches.
- **Resilient sessions**: Keep long-running sessions alive with tuned heartbeats and automatic cleanup.

## Next Steps

- **[Full Feature Guide](codebuff-backend.md)** - Complete configuration and usage
- **[Protocol Reference](../codebuff-protocol-reference.md)** - Message format specification
- **[Configuration Guide](../configuration.md)** - Advanced configuration options
- **[Backend Setup](../backends/overview.md)** - Configure additional backends
- **[Session Management](session-management.md)** - Configure resilient sessions and heartbeats

## Troubleshooting

**Connection refused?**

- Verify proxy is running: `curl http://localhost:8000/health`
- Check `codebuff.enabled: true` in config
- Verify WebSocket path matches client configuration

**Authentication errors?**

- Set API keys via environment variables
- Check backend configuration in config file
- Verify backend is accessible

**Timeout errors?**

- Increase `heartbeat_timeout_seconds` in config
- Ensure client sends ping messages regularly
- Check network connectivity

For more help, see the [Troubleshooting Guide](../debugging/troubleshooting.md).
