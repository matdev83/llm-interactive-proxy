# OpenCode Go Backend

The `opencode-go` backend provides a single public backend name for OpenCode Go while routing requests internally across two upstream protocol flavors:

- OpenAI-compatible chat completions for most supported models
- Anthropic-compatible messages for the Minimax models that require it

This keeps client-side routing simple. You select `opencode-go`, and the proxy chooses the correct upstream protocol based on the model id.

## Upstream Service Details

OpenCode Go service details and upstream usage documentation:

- [OpenCode Go documentation](https://opencode.ai/docs/go)

## Configuration

### Environment Variables

Configure the backend with your OpenCode API key:

```bash
export OPENCODE_GO_API_KEY="..."
```

### YAML Example

```yaml
backends:
  opencode-go:
    api_key: "${OPENCODE_GO_API_KEY}"
    api_url: "https://opencode.ai/zen/go/v1"
    extra:
      model_protocol_overrides:
        # Optional escape hatch for future upstream protocol changes.
        # custom-model: anthropic
```

## Model Naming

Use the backend with canonical model identifiers in the form:

- `opencode-go/opencode-model-id` for advertised model names
- `opencode-go:<model-id>` when selecting the backend explicitly in request model strings

Examples:

- `opencode-go/glm-5`
- `opencode-go/glm-5.1`
- `opencode-go/kimi-k2.5`
- `opencode-go/mimo-v2-pro`
- `opencode-go/mimo-v2-omni`
- `opencode-go/minimax-m2.5`
- `opencode-go/minimax-m2.7`

## Protocol Routing

The proxy currently routes these models through the OpenAI-compatible upstream path:

- `glm-5`
- `glm-5.1`
- `kimi-k2.5`
- `mimo-v2-pro`
- `mimo-v2-omni`

The proxy currently routes these models through the Anthropic-compatible upstream path:

- `minimax-m2.5`
- `minimax-m2.7`

If OpenCode changes protocol assignments later, you can override the built-in mapping with `backends.opencode-go.extra.model_protocol_overrides`.

## Usage Example

Example request through the OpenAI Chat Completions frontend:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode-go:glm-5.1",
    "messages": [{"role": "user", "content": "Explain this code."}],
    "stream": true
  }'
```

Example request targeting a model that the proxy routes through the Anthropic-compatible upstream path:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "opencode-go:minimax-m2.7",
    "messages": [{"role": "user", "content": "Summarize the design tradeoffs."}]
  }'
```

## Related Documentation

- [Backend Overview](overview.md)
- [User Guide Index](../index.md)
- [OpenAI Chat Completions Frontend](../frontends/openai-chat-completions.md)
