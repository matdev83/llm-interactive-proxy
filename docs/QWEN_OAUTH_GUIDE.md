# Qwen OAuth Backend Guide

## Overview

The Qwen OAuth backend allows you to use Alibaba's Qwen models through OAuth authentication, leveraging the same tokens used by the `qwen-code` CLI tool.

## ✅ Status: FULLY FUNCTIONAL

- ✅ OAuth token loading and refresh
- ✅ Chat completions (streaming and non-streaming)
- ✅ Model routing and overrides
- ✅ Integration with proxy features
- ✅ Performance tracking and accounting

## Prerequisites

1. **Install and authenticate qwen-code CLI**:
   ```bash
   # Install qwen-code CLI (if not already installed)
   npm install -g qwen-code
   
   # Authenticate to get OAuth tokens
   qwen-code --auth
   ```

2. **Verify OAuth tokens exist**:
   ```bash
   # Check if credentials file exists
   ls ~/.qwen/oauth_creds.json  # Linux/Mac
   dir %USERPROFILE%\.qwen\oauth_creds.json  # Windows
   ```

## Configuration

### Option 1: Environment Variable
```bash
export LLM_BACKEND=qwen-oauth
```

### Option 2: .env File
```env
LLM_BACKEND=qwen-oauth
```

### Option 3: In-Chat Command
```
!/set(backend=qwen-oauth)
```

## Available Models

- `qwen3-coder-plus` (default, recommended)
- `qwen3-coder-flash` (faster variant)
- `qwen-turbo`, `qwen-plus`, `qwen-max` (legacy names)
- Various `qwen2.5-*` models

## Usage Examples

### 1. Start the Proxy
```bash
python src/core/cli.py
```

### 2. Use with OpenAI Client
```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-proxy-api-key"
)

response = client.chat.completions.create(
    model="qwen-oauth:qwen3-coder-plus",
    messages=[
        {"role": "user", "content": "Hello, Qwen!"}
    ]
)

print(response.choices[0].message.content)
```

### 3. Use with curl
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-proxy-api-key" \
  -d '{
    "model": "qwen-oauth:qwen3-coder-plus",
    "messages": [
      {"role": "user", "content": "Hello, Qwen!"}
    ],
    "max_tokens": 100
  }'
```

### 4. Model Override Commands
```
# Switch to flash model for faster responses
!/set(model=qwen-oauth:qwen3-coder-flash)

# One-time model override
!/oneoff(qwen-oauth:qwen3-coder-plus)
```

## Features

### ✅ Automatic Token Refresh
- Tokens are automatically refreshed when they expire
- Uses refresh tokens from qwen-code authentication
- Seamless operation without manual intervention

### ✅ Streaming Support
```python
response = client.chat.completions.create(
    model="qwen-oauth:qwen3-coder-plus",
    messages=[{"role": "user", "content": "Count to 10"}],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### ✅ Error Handling
- Proper HTTP status codes
- Detailed error messages
- Automatic fallback to refresh tokens

### ✅ Integration Features
- Works with all proxy features (commands, routing, accounting)
- Performance tracking
- Loop detection
- API key redaction

## Troubleshooting

### Token Issues
```bash
# Re-authenticate if tokens are invalid
qwen-code --auth

# Check token status
python test_qwen_oauth.py
```

### Connection Issues
- Verify internet connection to `portal.qwen.ai`
- Check firewall settings
- Ensure OAuth tokens are not expired

### Model Issues
- Use `qwen3-coder-plus` as the primary model
- Check available models in the connector configuration

## Testing

Run the comprehensive test suite:
```bash
# Test OAuth connection
python test_qwen_oauth.py

# Test full integration
python test_qwen_integration.py
```

## Architecture

```
Client Request
    ↓
Proxy (main.py)
    ↓
QwenOAuthConnector
    ↓
OAuth Token Management
    ↓
Qwen API (portal.qwen.ai)
    ↓
Response back to Client
```

## Files

- `src/connectors/qwen_oauth.py` - Main connector implementation
- `src/constants.py` - Backend type definitions
- `src/main.py` - Integration and routing
- `test_qwen_oauth.py` - Basic connectivity test
- `test_qwen_integration.py` - Full integration test

## Support

The Qwen OAuth backend is fully functional and tested. For issues:

1. Check OAuth token validity with `qwen-code --auth`
2. Run test scripts to verify connectivity
3. Check proxy logs for detailed error information
4. Ensure proper model names are used (`qwen3-coder-plus`)