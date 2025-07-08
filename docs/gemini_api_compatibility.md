# Gemini API Compatibility

The LLM Interactive Proxy now provides a **Gemini API-compatible frontend interface**, allowing users to interact with the proxy using Google Gemini API format requests and responses. This enables seamless integration with existing Gemini API clients while leveraging the proxy's backend capabilities.

## Overview

This feature adds Gemini API-compatible endpoints that:
- Accept requests in Google Gemini API format
- Convert them internally to OpenAI format for processing by existing backends
- Convert responses back to Gemini format
- Support both streaming and non-streaming requests
- Handle Gemini-style authentication

## Available Endpoints

### 1. Models Listing
```
GET /v1beta/models
```
Returns available models in Gemini API format.

**Response Format:**
```json
{
  "models": [
    {
      "name": "models/gpt-4",
      "base_model_id": "gpt-4",
      "version": "001",
      "display_name": "Gpt 4",
      "description": "Model gpt-4 via LLM Interactive Proxy",
      "input_token_limit": 32768,
      "output_token_limit": 4096,
      "supported_generation_methods": ["generateContent", "streamGenerateContent"]
    }
  ]
}
```

### 2. Content Generation
```
POST /v1beta/models/{model}:generateContent
```
Generate content using a specific model (non-streaming).

**Request Format:**
```json
{
  "contents": [
    {
      "parts": [{"text": "What is the capital of France?"}],
      "role": "user"
    }
  ],
  "generation_config": {
    "temperature": 0.7,
    "max_output_tokens": 100,
    "top_p": 0.9
  },
  "system_instruction": {
    "parts": [{"text": "You are a helpful assistant."}],
    "role": "user"
  }
}
```

**Response Format:**
```json
{
  "candidates": [
    {
      "content": {
        "parts": [{"text": "The capital of France is Paris."}],
        "role": "model"
      },
      "finish_reason": "STOP",
      "index": 0
    }
  ],
  "usage_metadata": {
    "prompt_token_count": 10,
    "candidates_token_count": 8,
    "total_token_count": 18
  }
}
```

### 3. Streaming Content Generation
```
POST /v1beta/models/{model}:streamGenerateContent
```
Generate content with streaming response.

**Request Format:** Same as non-streaming endpoint.

**Response Format:** Server-sent events with Gemini-formatted chunks:
```
data: {"candidates":[{"content":{"parts":[{"text":"The"}],"role":"model"},"index":0}]}

data: {"candidates":[{"content":{"parts":[{"text":" capital"}],"role":"model"},"index":0}]}

data: [DONE]
```

## Authentication

The Gemini API compatibility layer supports two authentication methods:

### 1. Gemini-style API Key (Recommended)
Use the `x-goog-api-key` header:
```http
x-goog-api-key: your-proxy-api-key
```

### 2. Bearer Token (Fallback)
Use the standard Authorization header:
```http
Authorization: Bearer your-proxy-api-key
```

## Model Names

You can use any model available through the proxy's backends by specifying:
- Direct model names: `gemini-pro`, `gpt-4`, `claude-3-sonnet`
- Backend-prefixed names: `openrouter:gpt-4`, `gemini:gemini-pro`

## Supported Features

### ✅ Supported
- Basic text generation
- System instructions
- Generation configuration (temperature, max_tokens, top_p, etc.)
- Multi-turn conversations
- Streaming and non-streaming responses
- Multiple content parts (text + attachment indicators)
- Proper error handling and response conversion

### ⚠️ Partial Support
- Multimodal content (images/files converted to text indicators)
- Safety settings (passed through but not fully processed)
- Tool/function calling (not yet implemented)

### ❌ Not Supported
- File API integration
- Advanced safety filtering
- Gemini-specific features not available in OpenAI format

## Usage Examples

### Python Client Example
```python
import requests

# Initialize client
base_url = "http://localhost:8000"
api_key = "your-api-key"

headers = {
    "Content-Type": "application/json",
    "x-goog-api-key": api_key
}

# Simple generation
response = requests.post(
    f"{base_url}/v1beta/models/gemini-pro:generateContent",
    headers=headers,
    json={
        "contents": [
            {
                "parts": [{"text": "Explain quantum computing"}],
                "role": "user"
            }
        ],
        "generation_config": {
            "temperature": 0.7,
            "max_output_tokens": 200
        }
    }
)

result = response.json()
content = result["candidates"][0]["content"]["parts"][0]["text"]
print(content)
```

### cURL Example
```bash
curl -X POST "http://localhost:8000/v1beta/models/gemini-pro:generateContent" \
  -H "Content-Type: application/json" \
  -H "x-goog-api-key: your-api-key" \
  -d '{
    "contents": [
      {
        "parts": [{"text": "What is machine learning?"}],
        "role": "user"
      }
    ],
    "generation_config": {
      "temperature": 0.5,
      "max_output_tokens": 150
    }
  }'
```

## Configuration

No additional configuration is required. The Gemini API endpoints are automatically available when the proxy is running. The endpoints use the same authentication and backend configuration as the existing OpenAI-compatible endpoints.

## Error Handling

Errors are handled gracefully and passed through in the appropriate format:
- Authentication errors return 401 status
- Invalid requests return 400 status with details
- Backend errors are converted to appropriate Gemini error format

## Integration with Existing Backends

The Gemini API compatibility layer works with all existing proxy backends:
- **OpenRouter**: Access to various models via Gemini API format
- **Gemini**: Direct Gemini backend access with format consistency
- **Gemini CLI Direct**: Local Gemini CLI access via Gemini API format

This allows users to:
1. Use familiar Gemini API format
2. Access multiple backend providers
3. Leverage proxy features (session management, command processing, etc.)
4. Maintain compatibility with existing Gemini API clients

## Testing

Comprehensive tests are available in:
- `tests/integration/chat_completions_tests/test_gemini_api_compatibility.py`
- `tests/unit/test_gemini_converters.py`

Run tests with:
```bash
python -m pytest tests/ -k gemini
``` 