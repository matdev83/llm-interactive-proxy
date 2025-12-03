# Identity Provider Setup Guide

This guide explains how to configure popular identity providers (IdPs) for SSO authentication with the LLM Proxy.

## Supported Identity Providers

The LLM Proxy supports the following identity providers:

- **Google** - OAuth2/OIDC
- **Microsoft Azure AD / Entra ID** - OAuth2/OIDC
- **GitHub** - OAuth2
- **LinkedIn** - OAuth2
- **AWS IAM Identity Center** (formerly AWS SSO) - OAuth2/OIDC

## Quick Start

### Using Configuration File

The easiest way to configure IdPs is using a YAML configuration file:

```yaml
sso:
  enabled: true
  providers:
    google:
      type: "oauth2"
      client_id: "YOUR_CLIENT_ID.apps.googleusercontent.com"
      client_secret: "YOUR_CLIENT_SECRET"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

See `config/sso_auth.example.yaml` for a complete example with all providers.

### Using Python API

You can also configure IdPs programmatically:

```python
from src.core.auth.sso import create_google_config, SSOConfig

# Create provider configuration
google = create_google_config(
    client_id="123.apps.googleusercontent.com",
    client_secret="GOCSPX-secret"
)

# Add to SSO config
sso_config = SSOConfig(
    enabled=True,
    providers={"google": google}
)
```

## Provider-Specific Setup

### Google OAuth2/OIDC

**1. Create OAuth2 Credentials**

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a new project or select an existing one
3. Click "Create Credentials" > "OAuth 2.0 Client ID"
4. Choose "Web application" as the application type
5. Add authorized redirect URI: `http://localhost:8080/auth/callback` (adjust port if needed)
6. Note the Client ID and Client Secret

**2. Configure in LLM Proxy**

```yaml
google:
  type: "oauth2"
  client_id: "123456789.apps.googleusercontent.com"
  client_secret: "GOCSPX-abc123def456"
  discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

Or using Python:

```python
from src.core.auth.sso import create_google_config

config = create_google_config(
    client_id="123456789.apps.googleusercontent.com",
    client_secret="GOCSPX-abc123def456"
)
```

**Scopes:**
- `openid` - Required for OIDC authentication
- `email` - Access user's email address
- `profile` - Access user's basic profile information

---

### Microsoft Azure AD / Entra ID

**1. Register Application**

1. Go to [Azure Portal](https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps)
2. Click "New registration"
3. Enter application name
4. Choose supported account types:
   - "Accounts in any organizational directory and personal Microsoft accounts" (multi-tenant)
   - "Accounts in this organizational directory only" (single-tenant)
5. Add redirect URI: `http://localhost:8080/auth/callback`
6. Click "Register"
7. Note the Application (client) ID and Directory (tenant) ID
8. Go to "Certificates & secrets" > "New client secret"
9. Note the client secret value

**2. Configure in LLM Proxy**

Multi-tenant configuration:

```yaml
microsoft:
  type: "oauth2"
  client_id: "12345678-1234-1234-1234-123456789012"
  client_secret: "abc~123def~456"
  discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

Single-tenant configuration:

```yaml
microsoft:
  type: "oauth2"
  client_id: "12345678-1234-1234-1234-123456789012"
  client_secret: "abc~123def~456"
  discovery_url: "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

Or using Python:

```python
from src.core.auth.sso import create_microsoft_config

# Multi-tenant
config = create_microsoft_config(
    client_id="12345678-1234-1234-1234-123456789012",
    client_secret="abc~123def~456",
    tenant_id="common"  # or "organizations", "consumers"
)

# Single-tenant
config = create_microsoft_config(
    client_id="12345678-1234-1234-1234-123456789012",
    client_secret="abc~123def~456",
    tenant_id="87654321-4321-4321-4321-210987654321"
)
```

**Tenant Options:**
- `common` - Multi-tenant (personal + work/school accounts)
- `organizations` - Work/school accounts only
- `consumers` - Personal Microsoft accounts only
- Specific tenant ID - Single tenant

---

### GitHub OAuth2

**1. Create OAuth App**

1. Go to [GitHub Developer Settings](https://github.com/settings/developers)
2. Click "New OAuth App"
3. Fill in application details:
   - Application name: Your app name
   - Homepage URL: Your application URL
   - Authorization callback URL: `http://localhost:8080/auth/callback`
4. Click "Register application"
5. Note the Client ID
6. Click "Generate a new client secret"
7. Note the Client Secret

**2. Configure in LLM Proxy**

```yaml
github:
  type: "oauth2"
  client_id: "Iv1.abc123def456"
  client_secret: "abc123def456ghi789jkl012mno345pqr678stu"
  authorize_url: "https://github.com/login/oauth/authorize"
  token_url: "https://github.com/login/oauth/access_token"
  userinfo_url: "https://api.github.com/user"
  scopes: ["user:email", "read:user"]
```

Or using Python:

```python
from src.core.auth.sso import create_github_config

config = create_github_config(
    client_id="Iv1.abc123def456",
    client_secret="abc123def456ghi789jkl012mno345pqr678stu"
)
```

**Scopes:**
- `user:email` - Access user's email addresses (required)
- `read:user` - Access user's profile information

**Note:** GitHub may not expose user email if privacy settings restrict it. The proxy will attempt to fetch email from the `/user/emails` endpoint.

---

### LinkedIn OAuth2

**1. Create LinkedIn App**

1. Go to [LinkedIn Developers](https://www.linkedin.com/developers/apps)
2. Click "Create app"
3. Fill in application details
4. Click "Create app"
5. Go to "Auth" tab
6. Add redirect URL: `http://localhost:8080/auth/callback`
7. Under "Products", add "Sign In with LinkedIn using OpenID Connect"
8. Note the Client ID and Client Secret

**2. Configure in LLM Proxy**

```yaml
linkedin:
  type: "oauth2"
  client_id: "abc123def456"
  client_secret: "AbC123DeF456"
  authorize_url: "https://www.linkedin.com/oauth/v2/authorization"
  token_url: "https://www.linkedin.com/oauth/v2/accessToken"
  scopes: ["openid", "profile", "email"]
```

Or using Python:

```python
from src.core.auth.sso import create_linkedin_config

config = create_linkedin_config(
    client_id="abc123def456",
    client_secret="AbC123DeF456"
)
```

**Scopes:**
- `openid` - Required for authentication
- `profile` - Access user's basic profile
- `email` - Access user's email address

---

### AWS IAM Identity Center

**1. Set Up IAM Identity Center**

1. Go to [AWS IAM Identity Center](https://console.aws.amazon.com/singlesignon)
2. Enable IAM Identity Center if not already enabled
3. Go to "Applications" > "Add application"
4. Choose "I have an application I want to set up"
5. Select "OAuth 2.0" as application type
6. Fill in application details:
   - Display name: Your app name
   - Redirect URIs: `http://localhost:8080/auth/callback`
   - Grant types: Authorization code
   - Scopes: openid, email, profile
7. Click "Submit"
8. Note the Client ID and Client Secret

**2. Configure in LLM Proxy**

```yaml
aws:
  type: "oauth2"
  client_id: "abc123def456ghi789"
  client_secret: "AbC123DeF456GhI789JkL012"
  discovery_url: "https://oidc.us-east-1.amazonaws.com/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

Or using Python:

```python
from src.core.auth.sso import create_aws_iam_identity_center_config

config = create_aws_iam_identity_center_config(
    client_id="abc123def456ghi789",
    client_secret="AbC123DeF456GhI789JkL012",
    region="us-west-2"  # Your AWS region
)
```

**Region Configuration:**

Replace `us-east-1` with your AWS region where IAM Identity Center is configured:
- `us-east-1` (US East - N. Virginia)
- `us-west-2` (US West - Oregon)
- `eu-west-1` (Europe - Ireland)
- `ap-southeast-1` (Asia Pacific - Singapore)
- etc.

---

## Convenience Functions

The `create_provider_config` function provides a convenient way to create any provider configuration:

```python
from src.core.auth.sso import create_provider_config

# Google
google = create_provider_config("google", client_id="...", client_secret="...")

# Microsoft with tenant
microsoft = create_provider_config(
    "microsoft",
    client_id="...",
    client_secret="...",
    tenant_id="common"
)

# GitHub
github = create_provider_config("github", client_id="...", client_secret="...")

# LinkedIn
linkedin = create_provider_config("linkedin", client_id="...", client_secret="...")

# AWS with region
aws = create_provider_config(
    "aws",
    client_id="...",
    client_secret="...",
    region="us-west-2"
)
```

Supported provider names (case-insensitive):
- `google`
- `microsoft`, `azure` (aliases)
- `github`
- `linkedin`
- `aws`, `aws-sso` (aliases)

## Testing Your Configuration

After configuring your IdP, test the authentication flow:

1. Start the proxy with SSO enabled:
   ```bash
   python -m src.anthropic_server --sso-config config/sso_auth.yaml
   ```

2. Make a request without authentication:
   ```bash
   curl http://localhost:8080/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}'
   ```

3. You should receive a sandbox response with an authentication URL

4. Open the authentication URL in a browser

5. Complete the SSO flow with your IdP

6. Follow the authorization flow (confirmation code or API)

7. Receive your agent token

8. Configure your AI agent with the token

## Troubleshooting

### Common Issues

**"Provider not configured" error**
- Verify the provider name in your configuration matches exactly
- Check that the provider section is properly indented in YAML

**"Authorization endpoint not found" error**
- For OIDC providers (Google, Microsoft, AWS): Verify the discovery URL is correct
- For manual OAuth2 (GitHub, LinkedIn): Verify authorize_url and token_url are set

**"Invalid client" error**
- Double-check your client ID and client secret
- Ensure the redirect URI in your IdP matches exactly: `http://localhost:8080/auth/callback`

**"Scope not granted" error**
- Verify the requested scopes are enabled in your IdP application settings
- Some providers require explicit approval for certain scopes

**Email not returned**
- GitHub: User may have email privacy enabled. The proxy will use a placeholder.
- LinkedIn: Ensure the "email" scope is requested and approved.

### Debug Mode

Enable debug logging to see detailed SSO flow information:

```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml --log-level DEBUG
```

## Security Best Practices

1. **Keep secrets secure**: Never commit client secrets to version control
2. **Use environment variables**: Store secrets in environment variables or secure vaults
3. **Restrict redirect URIs**: Only add necessary redirect URIs to your IdP configuration
4. **Use HTTPS in production**: Always use HTTPS for production deployments
5. **Rotate secrets regularly**: Periodically rotate client secrets
6. **Monitor access logs**: Review authentication logs for suspicious activity

## Next Steps

- [Configure Authorization](./sso_authorization.md) - Set up single-user or enterprise authorization
- [Agent Configuration](./sso_agent_setup.md) - Configure AI agents with tokens
- [Troubleshooting Guide](./sso_troubleshooting.md) - Common issues and solutions
