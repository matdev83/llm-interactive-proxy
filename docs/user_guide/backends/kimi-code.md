# Kimi Code Backend

The `kimi-code` backend provides an OpenAI-compatible connector for Kimi's coding gateway.

It is implemented as a subclass of the OpenAI-compatible backend connector and targets:

- Base URL: `https://api.kimi.com/coding/v1`

This backend is intended to be used via the [OpenAI Chat Completions frontend](../frontends/openai-chat-completions.md).

## Configuration

### Environment Variables

Set the API key:

```bash
export KIMI_API_KEY="..."
```

## Model Naming

The proxy exposes a single model through this backend:

- `kimi-for-coding`

When calling the OpenAI Chat Completions frontend, use the fully-qualified model string:

- `kimi-code:kimi/kimi-for-coding`

Example:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-code:kimi/kimi-for-coding",
    "messages": [{"role": "user", "content": "Write a Python function that prints Hello World."}],
    "stream": true
  }'
```

## Multimodal (Text + Image)

This backend advertises the model as accepting:

- Input modalities: `text`, `image`
- Output modalities: `text`

Example (OpenAI-compatible `image_url` message parts):

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "kimi-code:kimi/kimi-for-coding",
    "messages": [{
      "role": "user",
      "content": [
        {"type": "text", "text": "Describe what you see and suggest refactors."},
        {"type": "image_url", "image_url": {"url": "https://example.com/screenshot.png"}}
      ]
    }],
    "stream": true
  }'
```

## Reasoning Output Compatibility

Some OpenAI-compatible providers stream text using `reasoning_content` while leaving `content` empty.
Many clients only render `content`.

The `kimi-code` connector mirrors reasoning text into `content` when needed, while keeping the original
reasoning fields intact. This makes the backend usable with clients that do not understand
`reasoning_content`.

## Related Documentation

- [Backend Overview](overview.md)
- [OpenAI Chat Completions Frontend](../frontends/openai-chat-completions.md)
