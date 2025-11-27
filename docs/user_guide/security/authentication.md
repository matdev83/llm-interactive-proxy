# Authentication

API key authentication for the LLM Interactive Proxy, controlling access to the proxy server.

## Overview

The proxy supports optional API key authentication to control which clients can access the service. When enabled, clients must provide a valid API key in the `Authorization` header to make requests. This prevents unauthorized access to your proxy instance and the backend LLM providers it connects to.

Authentication is enabled by default and can be configured via CLI flags, environment variables, or the configuration file.

## Key Features

- Bearer token authentication using standard HTTP Authorization header
- Optional authentication (can be disabled for development/testing)
- Per-IP brute-force protection against invalid key attempts
- Automatic key redaction in logs and wire captures
- Bypass list for public endpoints (docs, health checks)

## Configuration

### Setting the Proxy API Key

The proxy API key is set via the `LLM_INTERACTIVE_PROXY_API_KEY` environment variable:

```bash
export LLM_INTERACTIVE_PROXY_API_KEY="your-secret-proxy-key"
```

**Security Best Practice**: Never store the proxy API key in configuration files or commit it to version control. Always use environment variables.

### CLI Arguments

```bash
# Authentication is enabled by default
python -m src.core.cli

# Explicitly disable authentication (not recommended for production)
python -m src.core.cli --disable-auth
```

### Environment Variables

```bash
# Set the proxy API key (required when authentication is enabled)
export LLM_INTERACTIVE_PROXY_API_KEY="your-secret-proxy-key"

# Disable authentication (default: false)
export DISABLE_AUTH=true
```

### YAML Configuration

```yaml
auth:
  # Disable authentication (default: false)
  disable_auth: false
  
  # Brute-force protection settings (see brute-force-protection.md)
  brute_force_protection:
    enabled: true
    max_failed_attempts: 5
    ttl_seconds: 900
```

## Usage Examples

### Client Authentication

Clients must include the API key in the `Authorization` header using the Bearer scheme:

**cURL Example**:

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-secret-proxy-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**Python Example**:

```python
import openai

client = openai.OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-secret-proxy-key"  # Proxy API key, not provider key
)

response = client.chat.completions.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**JavaScript Example**:

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'your-secret-proxy-key'  // Proxy API key, not provider key
});

const response = await client.chat.completions.create({
  model: 'gpt-4',
  messages: [{ role: 'user', content: 'Hello!' }]
});
```

### Development Mode (No Authentication)

For local development and testing, you can disable authentication:

```bash
# Disable authentication via CLI
python -m src.core.cli --disable-auth

# Or via environment variable
export DISABLE_AUTH=true
python -m src.core.cli
```

**Warning**: Never disable authentication in production environments or when the proxy is exposed to the internet.

## Use Cases

### Production Deployment

Enable authentication to secure your proxy instance:

```bash
# Set a strong proxy API key
export LLM_INTERACTIVE_PROXY_API_KEY="$(openssl rand -base64 32)"

# Start the proxy with authentication enabled (default)
python -m src.core.cli --default-backend openai
```

### Multi-User Access

Use the same proxy API key for all authorized users:

```bash
# Share the proxy API key with authorized users
export LLM_INTERACTIVE_PROXY_API_KEY="shared-team-key"

# Users configure their clients with the proxy key
# Each user still needs their own provider API keys (OpenAI, Anthropic, etc.)
```

### Development and Testing

Disable authentication for local development:

```bash
# Development mode - no authentication required
export DISABLE_AUTH=true
python -m src.core.cli --default-backend openai

# Clients can connect without Authorization header
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [...]}'
```

## Troubleshooting

### 401 Unauthorized Error

**Problem**: Client receives `401 Unauthorized` response.

**Solutions**:

1. Verify the proxy API key is set:
   ```bash
   echo $LLM_INTERACTIVE_PROXY_API_KEY
   ```

2. Check that the client is sending the correct key in the Authorization header:
   ```bash
   # Test with cURL
   curl -v http://localhost:8000/v1/chat/completions \
     -H "Authorization: Bearer your-secret-proxy-key"
   ```

3. Ensure authentication is not disabled:
   ```bash
   # Check DISABLE_AUTH is not set to true
   echo $DISABLE_AUTH
   ```

### 429 Too Many Requests

**Problem**: Client receives `429 Too Many Requests` with `Retry-After` header.

**Cause**: Brute-force protection has blocked the client IP due to too many invalid authentication attempts.

**Solution**: Wait for the block duration (shown in `Retry-After` header) or see [brute-force-protection.md](brute-force-protection.md) for configuration options.

### Missing Authorization Header

**Problem**: Client forgets to include the Authorization header.

**Solution**: Ensure all requests include the header:

```bash
Authorization: Bearer your-secret-proxy-key
```

### Key Not Found in Environment

**Problem**: Proxy fails to start with "API key not configured" error.

**Solution**: Set the `LLM_INTERACTIVE_PROXY_API_KEY` environment variable before starting the proxy:

```bash
export LLM_INTERACTIVE_PROXY_API_KEY="your-secret-proxy-key"
python -m src.core.cli
```

## Security Best Practices

1. **Use Strong Keys**: Generate cryptographically secure random keys:
   ```bash
   openssl rand -base64 32
   ```

2. **Never Commit Keys**: Add `.env` files to `.gitignore` and never commit API keys to version control.

3. **Rotate Keys Regularly**: Change the proxy API key periodically, especially if it may have been compromised.

4. **Enable in Production**: Always enable authentication when the proxy is exposed to the internet or untrusted networks.

5. **Use HTTPS**: When deploying the proxy, use HTTPS to encrypt the Authorization header in transit.

6. **Monitor Failed Attempts**: Review logs for repeated authentication failures, which may indicate an attack.

7. **Separate Keys**: Use different proxy API keys for different environments (development, staging, production).

## Related Features

- [Brute-Force Protection](brute-force-protection.md) - Automatic blocking of repeated invalid authentication attempts
- [Key Hygiene](key-hygiene.md) - API key redaction in logs and wire captures
