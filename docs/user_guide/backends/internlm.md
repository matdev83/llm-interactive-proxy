# InternLM Backend

The InternLM backend provides access to InternLM AI models through an OpenAI-compatible API. InternLM models are known for their strong reasoning capabilities and coding performance.

## Overview

[InternLM](https://internlm.intern-ai.org.cn) is a series of large language models developed by the Shanghai AI Laboratory. The proxy supports the `internlm` backend, which connects to InternLM's API using API key authentication.

## Key Features

- OpenAI-compatible API
- Multiple API key rotation for load distribution
- Vendor prefix support (`internlm/`)
- Automatic non-streaming backend requests with SSE stream synthesis
- Deep thinking mode support

## Configuration

### Prerequisites

You need an InternLM API key to use this backend:

1. Visit [https://internlm.intern-ai.org.cn](https://internlm.intern-ai.org.cn)
2. Navigate to API → API Tokens
3. Create a new API token

### Environment Variables

Set your API key using environment variables:

```bash
# Single API key
export INTERNAI_API_KEY="your-api-key-here"

# Multiple API keys for rotation (optional)
export INTERNAI_API_KEY="your-primary-key"
export INTERNAI_API_KEY_1="your-second-key"
export INTERNAI_API_KEY_2="your-third-key"
```

### CLI Arguments

```bash
# Start proxy with InternLM as default backend
python -m src.core.cli --default-backend internlm

# With specific model
python -m src.core.cli --default-backend internlm --force-model internlm2.5-latest
```

### Config File Example

```yaml
backends:
  internlm:
    type: internlm
    enabled: true

default_backend: internlm
```

## Available Models

The InternLM backend supports the following models:

| Model | Description |
|-------|-------------|
| `internlm2.5-latest` | Latest InternLM 2.5 model (recommended) |
| `internlm2.5-20b` | InternLM 2.5 20B parameter model |
| `internlm2.5-7b` | InternLM 2.5 7B parameter model |
| `internlm2-latest` | Latest InternLM 2 model |
| `internlm2-20b` | InternLM 2 20B parameter model |
| `internlm2-7b` | InternLM 2 7B parameter model |

Use with vendor prefix: `internlm/internlm2.5-latest`

## API Key Rotation

The InternLM backend supports multiple API keys for automatic rotation:

1. Set multiple keys using numbered environment variables:
   ```bash
   export INTERNAI_API_KEY="key1"
   export INTERNAI_API_KEY_1="key2"
   export INTERNAI_API_KEY_2="key3"
   ```

2. The backend automatically rotates through keys in round-robin fashion
3. This helps distribute load and provides fallback if one key hits rate limits

## Streaming Support

**Note:** The InternLM API does not reliably support Server-Sent Events (SSE) streaming. The connector handles this transparently by:

1. Sending non-streaming requests to the InternLM API
2. Converting the complete response into an OpenAI-compatible SSE stream
3. Providing the stream to clients as if it were native streaming

This ensures compatibility with all OpenAI-compatible clients while working within InternLM's API limitations.

## Usage Examples

### Basic Chat Completion

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="dummy-key"
)

response = client.chat.completions.create(
    model="internlm/internlm2.5-latest",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
```

### With Model Override

```bash
# Force all requests to use InternLM
python -m src.core.cli --default-backend internlm --force-model internlm2.5-latest
```

## Troubleshooting

### API Key Issues

If you see authentication errors:
- Verify your `INTERNAI_API_KEY` is set correctly
- Check that the key is active in your InternLM account
- For multiple keys, ensure all keys are valid

### Streaming Issues

The InternLM backend automatically handles streaming via non-streaming API calls. If you experience issues:
- Check proxy logs for InternLM-specific error messages
- Verify the backend is healthy: `curl http://localhost:8000/health`
- Ensure the InternLM API endpoint is reachable

### Model Not Found

InternLM models should be prefixed with `internlm/` when using unified routing:
- ✅ `internlm/internlm2.5-latest`
- ❌ `internlm2.5-latest` (may not route correctly in multi-backend setups)

## Links

- [InternLM Website](https://internlm.intern-ai.org.cn)
- [API Documentation](https://internlm.intern-ai.org.cn/api/document)
- [InternLM GitHub](https://github.com/InternLM)
