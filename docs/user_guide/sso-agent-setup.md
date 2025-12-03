# AI Agent Configuration Guide

After completing SSO authentication and authorization, you'll receive an agent token. This guide explains how to configure popular AI coding agents to use your token with the LLM Proxy.

## Understanding Agent Tokens

### What is an Agent Token?

An agent token is a long-lived credential that identifies your AI agent to the proxy. Think of it like a device ID:

- **Long-lived**: Doesn't expire automatically (unlike SSO sessions)
- **Device-specific**: Each agent/device should have its own token
- **Bearer token format**: Used in the `Authorization` header
- **Secure**: Hashed with Argon2id, never stored in plaintext

### Agent Token vs SSO Session

| Aspect | Agent Token | SSO Session |
|--------|-------------|-------------|
| **Lifetime** | Indefinite (until revoked) | 24-48 hours (configurable) |
| **Purpose** | Device identification | User authentication |
| **Storage** | Agent configuration file | Proxy database |
| **Reconfiguration** | Once per agent | Never (auto-renewed) |

**Key Point**: When your SSO session expires, you re-authenticate through the web interface. Your agent token stays the same, so no reconfiguration is needed.

## Getting Your Agent Token

1. **Make an unauthenticated request** to the proxy (or open the proxy URL in a browser)
2. **Follow the authentication URL** provided in the response
3. **Log in** with your identity provider (Google, Microsoft, GitHub, etc.)
4. **Complete authorization**:
   - Single-user mode: Enter confirmation code from server console
   - Enterprise mode: Wait for authorization API approval
5. **Copy the agent token** from the success page

**Important**: The token is only displayed once. Copy it immediately and store it securely.

## Configuration by Agent

### Cursor

Cursor is a popular AI-powered code editor.

**Configuration Steps**:

1. Open Cursor settings (Cmd/Ctrl + ,)
2. Search for "API Key" or navigate to "Extensions" > "Cursor"
3. Find the "OpenAI API Key" or "API Key" field
4. Paste your agent token
5. Set the API base URL to your proxy: `http://localhost:8080/v1`

**Alternative (Settings JSON)**:

1. Open settings JSON (Cmd/Ctrl + Shift + P > "Preferences: Open Settings (JSON)")
2. Add:
```json
{
  "cursor.apiKey": "your-agent-token-here",
  "cursor.apiBaseUrl": "http://localhost:8080/v1"
}
```

**Verification**:
- Try using Cursor's AI features
- Check proxy logs for incoming requests
- Verify requests are authenticated (no sandbox responses)

---

### Continue

Continue is an open-source AI code assistant for VS Code and JetBrains IDEs.

**Configuration Steps**:

1. Open Continue settings (click Continue icon in sidebar > gear icon)
2. Click "Add Model" or edit existing model configuration
3. Select "OpenAI" as the provider
4. Set API key to your agent token
5. Set base URL to `http://localhost:8080/v1`

**Configuration File** (`~/.continue/config.json`):

```json
{
  "models": [
    {
      "title": "GPT-4 via Proxy",
      "provider": "openai",
      "model": "gpt-4",
      "apiKey": "your-agent-token-here",
      "apiBase": "http://localhost:8080/v1"
    }
  ]
}
```

**Verification**:
- Use Continue's chat or autocomplete features
- Check proxy logs for requests
- Verify model responses are coming through

---

### Cline (formerly Claude Dev)

Cline is an AI assistant for VS Code that supports multiple providers.

**Configuration Steps**:

1. Open Cline settings (click Cline icon > settings)
2. Select "OpenAI" as the API provider
3. Enter your agent token in the API key field
4. Set custom base URL to `http://localhost:8080/v1`
5. Select your preferred model

**Settings JSON** (`.vscode/settings.json`):

```json
{
  "cline.apiProvider": "openai",
  "cline.apiKey": "your-agent-token-here",
  "cline.apiBaseUrl": "http://localhost:8080/v1",
  "cline.model": "gpt-4"
}
```

**Verification**:
- Ask Cline to perform a task
- Check proxy logs for API calls
- Verify responses are correct

---

### Aider

Aider is a command-line AI pair programming tool.

**Configuration Steps**:

1. Set environment variable:
```bash
export OPENAI_API_KEY=your-agent-token-here
export OPENAI_API_BASE=http://localhost:8080/v1
```

2. Or use command-line flags:
```bash
aider --openai-api-key your-agent-token-here \
      --openai-api-base http://localhost:8080/v1 \
      --model gpt-4
```

3. Or create `.aider.conf.yml`:
```yaml
openai-api-key: your-agent-token-here
openai-api-base: http://localhost:8080/v1
model: gpt-4
```

**Verification**:
```bash
aider --test-cmd "echo test"
```

---

### GitHub Copilot (via Proxy)

**Note**: GitHub Copilot uses its own authentication. To route through the proxy, you need to configure the proxy as a system-wide HTTP proxy.

**Configuration Steps**:

1. Configure system HTTP proxy to point to LLM Proxy
2. Set environment variables:
```bash
export HTTP_PROXY=http://localhost:8080
export HTTPS_PROXY=http://localhost:8080
```

3. Configure Copilot to use custom endpoint (if supported)

**Alternative**: Use a tool like `mitmproxy` to intercept and route Copilot traffic.

---

### Cody (Sourcegraph)

Cody supports custom OpenAI-compatible endpoints.

**Configuration Steps**:

1. Open Cody settings in VS Code
2. Navigate to "Cody: Custom Configuration"
3. Add custom LLM configuration:
```json
{
  "customModels": [
    {
      "name": "GPT-4 via Proxy",
      "provider": "openai",
      "apiKey": "your-agent-token-here",
      "endpoint": "http://localhost:8080/v1"
    }
  ]
}
```

**Verification**:
- Use Cody's chat or autocomplete
- Check proxy logs for requests

---

### Tabnine

Tabnine primarily uses its own infrastructure, but supports custom endpoints for enterprise.

**Configuration Steps**:

1. Open Tabnine settings
2. Navigate to "Custom Model" or "Enterprise" settings
3. Set API endpoint to `http://localhost:8080/v1`
4. Set API key to your agent token

**Note**: Custom endpoint support may require Tabnine Enterprise.

---

### Custom/Generic OpenAI Client

For any tool that supports OpenAI-compatible APIs:

**Python (openai library)**:

```python
import openai

openai.api_key = "your-agent-token-here"
openai.api_base = "http://localhost:8080/v1"

response = openai.ChatCompletion.create(
    model="gpt-4",
    messages=[{"role": "user", "content": "Hello!"}]
)
```

**Node.js (openai library)**:

```javascript
import OpenAI from 'openai';

const openai = new OpenAI({
  apiKey: 'your-agent-token-here',
  baseURL: 'http://localhost:8080/v1'
});

const response = await openai.chat.completions.create({
  model: 'gpt-4',
  messages: [{ role: 'user', content: 'Hello!' }]
});
```

**cURL**:

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-agent-token-here" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

## Token Management Best Practices

### Secure Storage

**Do**:
- Store tokens in secure configuration files with restricted permissions
- Use environment variables for tokens
- Use secret managers (1Password, LastPass, etc.) for backup
- Keep tokens out of version control

**Don't**:
- Commit tokens to Git repositories
- Share tokens via email or chat
- Store tokens in plaintext in public locations
- Reuse tokens across multiple users

### File Permissions

Restrict access to configuration files containing tokens:

```bash
# Set restrictive permissions
chmod 600 ~/.continue/config.json
chmod 600 ~/.aider.conf.yml

# Verify permissions
ls -la ~/.continue/config.json
# Should show: -rw------- (owner read/write only)
```

### Environment Variables

Store tokens in environment variables:

```bash
# Add to ~/.bashrc or ~/.zshrc
export LLM_PROXY_TOKEN=your-agent-token-here

# Use in agent configuration
export OPENAI_API_KEY=$LLM_PROXY_TOKEN
```

### Token Rotation

Periodically rotate tokens for security:

1. Re-authenticate via SSO to generate a new token
2. Update agent configurations with new token
3. Revoke old token (if supported)
4. Test agents with new token

### Multiple Agents

Each agent/device should have its own token:

1. Authenticate separately for each agent
2. Use descriptive names when generating tokens (if supported)
3. Track which token is used by which agent
4. Revoke tokens individually when needed

## Troubleshooting

### Token Not Working

**Symptom**: Agent receives "Unauthorized" or sandbox response

**Solutions**:
- Verify token is copied correctly (no spaces, line breaks)
- Check token is configured as Bearer token
- Ensure SSO session is still active (re-authenticate if expired)
- Verify proxy is running and accessible
- Check proxy logs for authentication errors

### Token Expired

**Symptom**: "Session expired" or "Re-authentication required" message

**Solutions**:
- Your SSO session has expired (normal after 24-48 hours)
- Re-authenticate via the web interface
- Your agent token remains valid - no reconfiguration needed
- After re-authentication, agent should work immediately

### Wrong Base URL

**Symptom**: Connection errors or "404 Not Found"

**Solutions**:
- Verify base URL is correct: `http://localhost:8080/v1`
- Check proxy is running on the expected port
- Ensure `/v1` suffix is included in base URL
- Test URL with curl to verify it's accessible

### Token in Wrong Format

**Symptom**: "Invalid token format" error

**Solutions**:
- Ensure token is used as Bearer token: `Authorization: Bearer <token>`
- Don't add extra prefixes or suffixes
- Check agent documentation for correct token format
- Some agents may require `sk-` prefix (add if needed)

### Proxy Not Accessible

**Symptom**: Connection refused or timeout errors

**Solutions**:
- Verify proxy is running: `curl http://localhost:8080/health`
- Check firewall settings
- Ensure correct hostname/IP (use `localhost` for local proxy)
- Verify port number matches proxy configuration

## Re-Authentication

When your SSO session expires:

1. **Agent receives sandbox response** with re-authentication URL
2. **Open the URL** in a browser
3. **Log in** with your identity provider
4. **Session is restored** automatically
5. **Agent continues working** with the same token

**Important**: You do NOT need to reconfigure your agent. The same token continues working after re-authentication.

## Security Considerations

### Token Security

- **Treat tokens like passwords**: Never share or expose them
- **Use HTTPS in production**: Encrypt token transmission
- **Rotate regularly**: Generate new tokens periodically
- **Revoke compromised tokens**: Immediately revoke if exposed

### Network Security

- **Use VPN**: When accessing remote proxies
- **Firewall rules**: Restrict proxy access to authorized IPs
- **TLS/SSL**: Always use HTTPS for production deployments
- **Monitor access**: Review proxy logs for suspicious activity

### Agent Security

- **Keep agents updated**: Install security updates promptly
- **Review permissions**: Understand what agents can access
- **Limit scope**: Only grant necessary permissions
- **Audit usage**: Review what agents are doing with your token

## Advanced Configuration

### Multiple Proxies

Configure different agents to use different proxies:

**Cursor** (Production):
```json
{
  "cursor.apiKey": "prod-token",
  "cursor.apiBaseUrl": "https://proxy.company.com/v1"
}
```

**Continue** (Development):
```json
{
  "models": [{
    "apiKey": "dev-token",
    "apiBase": "http://localhost:8080/v1"
  }]
}
```

### Proxy Chaining

Route through multiple proxies:

```bash
# Set upstream proxy
export HTTP_PROXY=http://corporate-proxy:8080

# Configure agent to use LLM proxy
export OPENAI_API_BASE=http://localhost:8080/v1
```

### Custom Headers

Some agents support custom headers:

```json
{
  "customHeaders": {
    "X-User-ID": "alice",
    "X-Department": "engineering"
  }
}
```

## Next Steps

- **[Security Considerations](./sso_security.md)** - Understand security features
- **[Troubleshooting](./sso_troubleshooting.md)** - Common issues and solutions
- **[Configuration Options](./sso_configuration.md)** - Complete configuration reference

## FAQ

**Q: Do I need a separate token for each agent?**

A: It's recommended but not required. Each agent/device should have its own token for better security and tracking.

**Q: What happens if I lose my token?**

A: Re-authenticate via SSO to generate a new token. The old token can be revoked if needed.

**Q: Can I use the same token on multiple devices?**

A: Yes, but it's not recommended. Each device should have its own token for security and audit purposes.

**Q: How do I revoke a token?**

A: Token revocation is supported through the admin interface (future feature) or by directly modifying the database.

**Q: Does the token expire?**

A: The token itself doesn't expire, but the SSO session linked to it does (typically 24-48 hours). When the session expires, re-authenticate to restore access.

**Q: Can I see which agents are using my token?**

A: The proxy logs include client information (IP, user agent) for each request, allowing you to track token usage.

**Q: What if my agent doesn't support custom base URLs?**

A: You may need to use a system-wide HTTP proxy or a tool like `mitmproxy` to intercept and route traffic.

**Q: Can I use the token with the OpenAI Python library?**

A: Yes! Set `openai.api_key` to your token and `openai.api_base` to your proxy URL.
