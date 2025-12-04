# SSO Authentication Overview

## Introduction

The LLM Proxy supports Single Sign-On (SSO) authentication, allowing users to authenticate via corporate or public identity providers instead of using static API keys. This provides enterprise-grade security while maintaining compatibility with AI coding agents that only support Bearer token authentication.

## Key Concepts

### Agent Token vs SSO Session

The SSO authentication system uses a two-phase model:

1. **SSO Session**: Short-lived authentication session (typically 24-48 hours) established by logging in through an identity provider (Google, Microsoft, GitHub, etc.)

2. **Agent Token**: Long-lived device identifier (similar to a device ID) that persists across SSO sessions. This token is configured once in your AI agent and remains valid indefinitely.

**Think of it like this:**
- **Agent Token** = Your device's unique ID (like a phone's device ID)
- **SSO Session** = Your current login session (expires periodically)

When your SSO session expires, you simply re-authenticate through your identity provider. Your agent token remains the same, so you don't need to reconfigure your AI agent.

### Authentication Flow

```
1. User makes request without token
   -> Proxy returns login banner with authentication URL

2. User opens URL in browser
   -> Redirects to identity provider (Google, Microsoft, etc.)

3. User authenticates with IdP
   -> IdP redirects back to proxy with authentication proof

4. Proxy performs authorization check
   -> Single-user mode: Displays confirmation code in server logs
   -> Enterprise mode: Queries authorization API

5. User completes authorization
   -> Proxy generates and displays agent token

6. User copies token to AI agent configuration
   -> Agent can now make authenticated requests

7. When SSO session expires (days/weeks later)
   -> Proxy returns re-authentication URL
   -> User re-authenticates (same agent token, no reconfiguration needed)
```

### Sandbox Isolation

For security, the proxy enforces strict session isolation:

- **Unauthenticated requests** receive only a login banner (sandbox mode)
- **After authentication**, you must configure your agent with the token
- **Sandbox sessions cannot continue** after authentication completes
- This prevents authentication state from leaking into unauthenticated conversations

## Supported Identity Providers

The proxy supports the following identity providers out of the box:

| Provider | Protocol | Use Case |
|----------|----------|----------|
| **Google** | OAuth2/OIDC | Personal and G Suite accounts |
| **Microsoft Azure AD/Entra ID** | OAuth2/OIDC | Enterprise Microsoft accounts |
| **GitHub** | OAuth2 | Developer authentication |
| **LinkedIn** | OAuth2 | Professional network authentication |
| **AWS IAM Identity Center** | OAuth2/OIDC | AWS SSO, enterprise AWS accounts |

**All five providers are enabled by default** when you configure their credentials. Users will see all configured providers on the SSO login page and can choose their preferred authentication method. Administrators can selectively disable specific providers by setting `enabled: false` in the configuration.

See [Identity Provider Setup Guide](./sso-idp-setup.md) for detailed configuration instructions.

## Authorization Modes

After SSO authentication, the proxy performs an authorization check to determine if the user should be granted access:

### Single-User Mode

Best for personal use or small teams:

- After SSO authentication, a 6-digit confirmation code is logged to the server console
- User enters the code in the web interface
- Proxy generates and displays the agent token
- Includes rate limiting and exponential backoff for brute-force protection

**Use when:**
- Running the proxy locally for personal use
- Small team with trusted users
- No external authorization infrastructure

### Enterprise Mode

Best for organizations with existing authorization systems:

- After SSO authentication, proxy queries an external authorization API
- API receives user identity and IP address
- API returns true/false to grant/deny access
- Supports custom authorization logic (role checks, IP allowlists, etc.)

**Use when:**
- Need centralized access control
- Integration with existing authorization systems
- Complex authorization rules (roles, groups, IP restrictions)
- Audit and compliance requirements

See [Authorization Configuration](./sso_authorization.md) for detailed setup instructions.

## Getting Started

### Prerequisites

- Python 3.10 or higher
- LLM Proxy installed and configured
- Identity provider credentials (client ID and secret)

### Quick Start

1. **Choose an identity provider** (Google, Microsoft, GitHub, LinkedIn, or AWS)

2. **Create OAuth2 credentials** in the provider's developer console
   - See [Identity Provider Setup Guide](./sso_idp_setup.md) for provider-specific instructions

3. **Create SSO configuration file** (`config/sso_auth.yaml`):

```yaml
sso:
  enabled: true
  
  # Authorization mode
  authorization:
    mode: "single_user"  # or "enterprise"
    session_lifetime_hours: 24
  
  # Identity providers
  providers:
    google:
      type: "oauth2"
      client_id: "YOUR_CLIENT_ID.apps.googleusercontent.com"
      client_secret: "YOUR_CLIENT_SECRET"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

4. **Start the proxy with SSO enabled**:

```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

5. **Test authentication**:

```bash
# Make a request without authentication
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'

# Response will contain login banner with authentication URL
```

6. **Complete authentication flow**:
   - Open the authentication URL in a browser
   - Log in with your identity provider
   - Complete authorization (confirmation code or API approval)
   - Copy the generated agent token

7. **Configure your AI agent**:
   - See [Agent Configuration Guide](./sso_agent_setup.md) for agent-specific instructions

## Configuration Methods

### Method 1: YAML Configuration File (Recommended)

Create `config/sso_auth.yaml`:

```yaml
sso:
  enabled: true
  authorization:
    mode: "single_user"
    session_lifetime_hours: 24
  providers:
    google:
      type: "oauth2"
      client_id: "..."
      client_secret: "..."
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

Start with config file:
```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

### Method 2: Environment Variables

Set environment variables:
```bash
export SSO_ENABLED=true
export SSO_PROVIDER=google
export SSO_CLIENT_ID=your_client_id
export SSO_CLIENT_SECRET=your_client_secret
export SSO_AUTHORIZATION_MODE=single_user
```

Start the proxy:
```bash
python -m src.anthropic_server
```

### Method 3: CLI Flags

Pass configuration via command-line flags:
```bash
python -m src.anthropic_server \
  --sso-enabled \
  --sso-provider google \
  --sso-client-id "your_client_id" \
  --sso-client-secret "your_client_secret" \
  --sso-auth-mode single_user
```

**Priority order**: CLI flags > Environment variables > Config file

See [Configuration Options](./sso_configuration.md) for complete reference.

## Security Features

### Token Storage Security

- **Argon2id hashing**: Agent tokens are hashed using Argon2id with 2025-recommended parameters
- **No plaintext storage**: Only hashes are stored in the database
- **Constant-time comparison**: Token verification uses constant-time comparison to prevent timing attacks
- **Secure generation**: Tokens use 256-bit entropy from cryptographically secure random sources

### Sandbox Isolation

- **Session separation**: Unauthenticated sessions cannot continue after authentication
- **History detection**: Proxy detects and rejects requests containing sandbox login banners
- **No state leakage**: Authentication state never leaks into unauthenticated conversations

### Rate Limiting and Brute-Force Protection

- **Exponential backoff**: Failed authorization attempts trigger increasing wait times
- **Per-IP tracking**: Rate limits are enforced per IP address
- **Attempt limits**: Maximum 3 confirmation code attempts before re-authentication required

See [Security Considerations](./sso_security.md) for detailed security information.

## Re-Authentication

When your SSO session expires (typically after 24-48 hours):

1. **Proxy detects expired session** when you make a request
2. **Returns re-authentication URL** in the response
3. **You open the URL** and log in with your identity provider
4. **Session is restored** automatically
5. **No agent reconfiguration needed** - same token continues working

**Important**: Your agent token never changes. Only the SSO session expires and needs renewal.

## Disabling Legacy Authentication

When SSO mode is enabled, the proxy automatically disables legacy static Bearer key authentication:

- Static API keys configured in the proxy are ignored
- Requests with legacy keys receive the sandbox login banner
- This ensures all authentication goes through SSO

## Non-Loopback Binding

For security, the proxy enforces authentication when binding to non-loopback addresses:

- **Loopback (127.0.0.1, ::1)**: Authentication optional (for local development)
- **Non-loopback (0.0.0.0, public IPs)**: Authentication required (SSO or legacy)
- **Startup validation**: Proxy refuses to start on non-loopback without authentication

This prevents accidentally exposing an unauthenticated proxy to the network.

## Troubleshooting

### Common Issues

**"Provider not configured" error**
- Verify your SSO configuration file is valid YAML
- Check that the provider name matches exactly (case-sensitive)
- Ensure client ID and secret are set correctly

**"Invalid redirect URI" error**
- Verify the redirect URI in your IdP matches: `http://localhost:8080/auth/callback`
- Adjust port if you're running on a different port
- Use exact match (no trailing slashes)

**"Session expired" message**
- Your SSO session has expired (normal after 24-48 hours)
- Click the re-authentication URL to log in again
- Your agent token remains valid - no reconfiguration needed

**Agent token not working**
- Verify you copied the entire token (no spaces or line breaks)
- Check that your agent is configured with the token as a Bearer token
- Ensure your SSO session is still active (re-authenticate if needed)

See [Troubleshooting Guide](./sso_troubleshooting.md) for more solutions.

## Next Steps

- **[Identity Provider Setup](./sso_idp_setup.md)** - Configure Google, Microsoft, GitHub, LinkedIn, or AWS
- **[Authorization Configuration](./sso_authorization.md)** - Set up single-user or enterprise authorization
- **[Agent Configuration](./sso_agent_setup.md)** - Configure Cursor, Continue, Cline, and other AI agents
- **[Security Considerations](./sso_security.md)** - Understand security features and best practices
- **[Troubleshooting](./sso_troubleshooting.md)** - Common issues and solutions

## Examples

### Example 1: Personal Use with Google

```yaml
sso:
  enabled: true
  authorization:
    mode: "single_user"
    session_lifetime_hours: 24
  providers:
    google:
      type: "oauth2"
      client_id: "123.apps.googleusercontent.com"
      client_secret: "GOCSPX-secret"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Example 2: Enterprise with Microsoft and Authorization API

```yaml
sso:
  enabled: true
  authorization:
    mode: "enterprise"
    api_url: "https://company.com/api/authorize"
    api_timeout_seconds: 5
  providers:
    microsoft:
      type: "oauth2"
      client_id: "12345678-1234-1234-1234-123456789012"
      client_secret: "secret"
      discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Example 3: Multiple Providers

```yaml
sso:
  enabled: true
  authorization:
    mode: "single_user"
  providers:
    google:
      type: "oauth2"
      client_id: "google_id"
      client_secret: "google_secret"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
    
    github:
      type: "oauth2"
      client_id: "github_id"
      client_secret: "github_secret"
      authorize_url: "https://github.com/login/oauth/authorize"
      token_url: "https://github.com/login/oauth/access_token"
      userinfo_url: "https://api.github.com/user"
      scopes: ["user:email", "read:user"]
```

## FAQ

**Q: Do I need to reconfigure my agent when my SSO session expires?**

A: No. Your agent token remains valid indefinitely. When your SSO session expires, you simply re-authenticate through the web interface. Your agent continues using the same token.

**Q: Can I use multiple identity providers?**

A: Yes. You can configure multiple providers and users will see a provider selection page during authentication.

**Q: What happens if I lose my agent token?**

A: You'll need to re-authenticate and generate a new token. The old token can be revoked if needed.

**Q: Can I revoke an agent token?**

A: Yes. Token revocation is supported through the admin interface (future feature) or by directly modifying the database.

**Q: Is SSO required for all deployments?**

A: No. SSO is optional. For local development on loopback addresses (127.0.0.1), authentication is not required. For production deployments on non-loopback addresses, either SSO or legacy authentication must be enabled.

**Q: Can I use SSO with the existing static API key authentication?**

A: No. When SSO mode is enabled, legacy static API key authentication is automatically disabled. This ensures all authentication goes through SSO.

**Q: How long do agent tokens last?**

A: Agent tokens are long-lived and do not expire automatically. However, the SSO session linked to the token expires periodically (typically 24-48 hours) and requires re-authentication.

**Q: What information does the proxy store about users?**

A: The proxy stores: token hash (not plaintext), user email, user ID from IdP, provider name, authentication status, and timestamps. No passwords or sensitive IdP data are stored.

**Q: Can I run the proxy without authentication?**

A: Yes, but only when binding to loopback addresses (127.0.0.1 or ::1) for local development. For non-loopback addresses, authentication is required for security.
