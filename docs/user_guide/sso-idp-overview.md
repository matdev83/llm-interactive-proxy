# Identity Provider Configuration Overview

## What Are Identity Providers?

Identity Providers (IdPs) are external services that authenticate users and provide identity information. Instead of managing passwords locally, the LLM Proxy delegates authentication to trusted IdPs like Google, Microsoft, GitHub, LinkedIn, or AWS.

## Why Use IdPs?

- **Security**: Leverage enterprise-grade authentication infrastructure
- **Convenience**: Users authenticate with existing accounts (no new passwords)
- **Compliance**: Meet organizational security and audit requirements
- **Flexibility**: Support multiple authentication methods (OAuth2, OIDC, SAML)

## Supported Providers

The LLM Proxy includes pre-configured support for:

| Provider | Protocol | Discovery | Use Case |
|----------|----------|-----------|----------|
| **Google** | OAuth2/OIDC | Automatic | Personal and G Suite accounts |
| **Microsoft** | OAuth2/OIDC | Automatic | Azure AD, Office 365, personal accounts |
| **GitHub** | OAuth2 | Manual | Developer authentication |
| **LinkedIn** | OAuth2 | Manual | Professional network authentication |
| **AWS IAM Identity Center** | OAuth2/OIDC | Automatic | AWS SSO, enterprise AWS accounts |

## Configuration Methods

### 1. YAML Configuration File (Recommended)

The simplest method for most users:

```yaml
sso:
  enabled: true
  providers:
    google:
      type: "oauth2"
      client_id: "YOUR_CLIENT_ID"
      client_secret: "YOUR_CLIENT_SECRET"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

See `config/sso_auth.example.yaml` for a complete example.

### 2. Python API (Programmatic)

For dynamic configuration or custom integrations:

```python
from src.core.auth.sso import create_google_config, SSOConfig

google = create_google_config(
    client_id="123.apps.googleusercontent.com",
    client_secret="secret"
)

sso_config = SSOConfig(
    enabled=True,
    providers={"google": google}
)
```

See `examples/sso_idp_configuration.py` for more examples.

### 3. Convenience Functions

Quick configuration with minimal code:

```python
from src.core.auth.sso import create_provider_config

# Automatically selects the right configuration
config = create_provider_config(
    "google",  # or "microsoft", "github", "linkedin", "aws"
    client_id="...",
    client_secret="..."
)
```

## OAuth2 vs OIDC vs SAML

### OAuth2
- **Purpose**: Authorization (what you can access)
- **Providers**: GitHub, LinkedIn
- **Configuration**: Manual endpoint URLs required

### OIDC (OpenID Connect)
- **Purpose**: Authentication (who you are) + Authorization
- **Providers**: Google, Microsoft, AWS
- **Configuration**: Automatic discovery via `.well-known/openid-configuration`
- **Benefits**: Standardized, includes ID tokens with user info

### SAML
- **Purpose**: Enterprise authentication
- **Status**: Planned for future release
- **Use Case**: Large enterprises with existing SAML infrastructure

## Discovery vs Manual Configuration

### Automatic Discovery (OIDC)

Providers like Google, Microsoft, and AWS support OIDC discovery:

```yaml
google:
  discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
  # Endpoints are automatically discovered
```

**Advantages:**
- Simpler configuration (just one URL)
- Automatic updates if provider changes endpoints
- Standardized across providers

### Manual Configuration (OAuth2)

Providers like GitHub and LinkedIn require manual endpoint specification:

```yaml
github:
  authorize_url: "https://github.com/login/oauth/authorize"
  token_url: "https://github.com/login/oauth/access_token"
  userinfo_url: "https://api.github.com/user"
```

**When to use:**
- Provider doesn't support OIDC discovery
- Custom or self-hosted OAuth2 servers
- Need fine-grained control over endpoints

## Scopes Explained

Scopes define what information the proxy can access from the IdP:

| Scope | Purpose | Required? |
|-------|---------|-----------|
| `openid` | OIDC authentication | Yes (OIDC only) |
| `email` | User's email address | Recommended |
| `profile` | Basic profile info (name, picture) | Recommended |
| `user:email` | GitHub email access | Yes (GitHub) |
| `read:user` | GitHub profile access | Yes (GitHub) |

**Best Practice**: Request only the scopes you need. Users are more likely to approve minimal scope requests.

## Multi-Provider Setup

You can configure multiple providers simultaneously:

```yaml
sso:
  enabled: true
  providers:
    google:
      # Google config
    microsoft:
      # Microsoft config
    github:
      # GitHub config
```

Users will see a provider selection page during authentication.

## Security Considerations

### Client Secrets
- **Never commit to version control**: Use environment variables or secret managers
- **Rotate regularly**: Change secrets periodically
- **Restrict access**: Limit who can view/modify secrets

### Redirect URIs
- **Exact match required**: IdPs validate redirect URIs exactly
- **Use HTTPS in production**: Never use HTTP for production deployments
- **Minimize URIs**: Only add necessary redirect URIs

### Scopes
- **Principle of least privilege**: Request minimum necessary scopes
- **Review regularly**: Remove unused scopes
- **Document usage**: Explain why each scope is needed

## Quick Start Checklist

1. **Choose a provider** (Google, Microsoft, GitHub, LinkedIn, or AWS)
2. **Create OAuth2 credentials** in the provider's developer console
3. **Configure redirect URI**: `http://localhost:8080/auth/callback`
4. **Copy client ID and secret** from the provider
5. **Add to configuration file**: `config/sso_auth.yaml`
6. **Start the proxy**: `python -m src.anthropic_server --sso-config config/sso_auth.yaml`
7. **Test authentication**: Make a request and follow the login flow

## Next Steps

- **Detailed Setup**: See [Identity Provider Setup Guide](./sso_idp_setup.md) for provider-specific instructions
- **Authorization**: Configure [single-user or enterprise authorization](./sso_authorization.md)
- **Agent Setup**: Learn how to [configure AI agents with tokens](./sso_agent_setup.md)
- **Troubleshooting**: Review [common issues and solutions](./sso_troubleshooting.md)

## Examples

### Example 1: Google for Personal Use

```yaml
sso:
  enabled: true
  authorization:
    mode: "single_user"
  providers:
    google:
      type: "oauth2"
      client_id: "123.apps.googleusercontent.com"
      client_secret: "GOCSPX-secret"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Example 2: Microsoft for Enterprise

```yaml
sso:
  enabled: true
  authorization:
    mode: "enterprise"
    api_url: "https://company.com/api/authorize"
  providers:
    microsoft:
      type: "oauth2"
      client_id: "12345678-1234-1234-1234-123456789012"
      client_secret: "secret"
      discovery_url: "https://login.microsoftonline.com/organizations/v2.0/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Example 3: Multiple Providers

```yaml
sso:
  enabled: true
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

## Resources

- [OAuth 2.0 Specification](https://oauth.net/2/)
- [OpenID Connect Specification](https://openid.net/connect/)
- [Google OAuth2 Documentation](https://developers.google.com/identity/protocols/oauth2)
- [Microsoft Identity Platform](https://docs.microsoft.com/en-us/azure/active-directory/develop/)
- [GitHub OAuth Apps](https://docs.github.com/en/developers/apps/building-oauth-apps)
- [LinkedIn OAuth 2.0](https://docs.microsoft.com/en-us/linkedin/shared/authentication/authentication)
- [AWS IAM Identity Center](https://docs.aws.amazon.com/singlesignon/latest/userguide/what-is.html)
