# SSO Configuration Options

This document provides a complete reference for all SSO authentication configuration options.

## Configuration Methods

The LLM Proxy supports three methods for configuring SSO authentication:

1. **YAML Configuration File** (Recommended)
2. **Environment Variables**
3. **CLI Flags**

**Priority order**: CLI flags > Environment variables > Config file

## YAML Configuration File

### Complete Example

Create `config/sso_auth.yaml`:

```yaml
sso:
  # Enable SSO authentication
  enabled: true
  
  # Authorization configuration
  authorization:
    # Mode: "single_user" or "enterprise"
    mode: "single_user"
    
    # SSO session lifetime in hours (default: 24)
    session_lifetime_hours: 24
    
    # Single-user mode settings
    confirmation_code_expiry_minutes: 10
    max_confirmation_attempts: 3
    
    # Enterprise mode settings
    api_url: "https://company.com/api/authorize"
    api_timeout_seconds: 5

  # Optional invisible captcha for the public login form (Cloudflare Turnstile)
  captcha:
    enabled: true
    provider: "cloudflare_turnstile"
    site_key: "turnstile_site_key"
    secret_key: "turnstile_secret_key"
    widget_mode: "invisible"
  
  # Identity providers
  # All five providers (Google, Microsoft, GitHub, LinkedIn, AWS) are available
  # by default when configured. To disable a specific provider, set enabled: false
  providers:
    # Google OAuth2/OIDC
    google:
      enabled: true  # Optional: set to false to disable this provider
      type: "oauth2"
      client_id: "123.apps.googleusercontent.com"
      client_secret: "GOCSPX-secret"
      discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
    
    # Microsoft Azure AD/Entra ID
    microsoft:
      enabled: true  # Optional: set to false to disable this provider
      type: "oauth2"
      client_id: "12345678-1234-1234-1234-123456789012"
      client_secret: "secret"
      discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
    
    # GitHub OAuth2
    github:
      enabled: true  # Optional: set to false to disable this provider
      type: "oauth2"
      client_id: "Iv1.abc123"
      client_secret: "secret"
      authorize_url: "https://github.com/login/oauth/authorize"
      token_url: "https://github.com/login/oauth/access_token"
      userinfo_url: "https://api.github.com/user"
      scopes: ["user:email", "read:user"]
    
    # LinkedIn OAuth2
    linkedin:
      enabled: true  # Optional: set to false to disable this provider
      type: "oauth2"
      client_id: "abc123"
      client_secret: "secret"
      authorize_url: "https://www.linkedin.com/oauth/v2/authorization"
      token_url: "https://www.linkedin.com/oauth/v2/accessToken"
      scopes: ["openid", "profile", "email"]
    
    # AWS IAM Identity Center
    aws:
      enabled: true  # Optional: set to false to disable this provider
      type: "oauth2"
      client_id: "abc123"
      client_secret: "secret"
      discovery_url: "https://oidc.us-west-2.amazonaws.com/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Start with Configuration File

```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

## Configuration Options Reference

### Top-Level Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `enabled` | boolean | Yes | false | Enable SSO authentication |

### Authorization Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `mode` | string | Yes | - | Authorization mode: "single_user" or "enterprise" |
| `session_lifetime_hours` | integer | No | 24 | SSO session lifetime in hours |
| `confirmation_code_expiry_minutes` | integer | No | 10 | Confirmation code expiry (single-user mode) |
| `max_confirmation_attempts` | integer | No | 3 | Maximum confirmation code attempts |
| `api_url` | string | Conditional | - | Authorization API URL (enterprise mode) |
| `api_timeout_seconds` | integer | No | 5 | Authorization API timeout in seconds |

### Captcha Options

Use Cloudflare Turnstile to protect the public `/auth/login` form without pre-registering your URL.

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `captcha.enabled` | boolean | No | false | Enable captcha verification on the login form |
| `captcha.provider` | string | No | cloudflare_turnstile | Captcha provider (Turnstile supports unregistered domains) |
| `captcha.site_key` | string | Conditional | - | Site key from Turnstile dashboard |
| `captcha.secret_key` | string | Conditional | - | Secret key used for server-side verification |
| `captcha.verify_url` | string | No | Turnstile default | Override verification endpoint |
| `captcha.widget_mode` | string | No | invisible | Widget mode: `invisible` or `managed` |
| `captcha.timeout_seconds` | number | No | 5.0 | HTTP timeout for verification call |

### Provider Options

**Provider Selection Behavior:**
- All five supported providers (Google, Microsoft, GitHub, LinkedIn, AWS IAM Identity Center) are available by default when configured
- A provider appears on the login page if it has valid credentials AND is not explicitly disabled
- At least one provider must be enabled for SSO mode to start
- Providers without credentials or with `enabled: false` are automatically hidden from the login page

#### Common Provider Options

| Option | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `enabled` | boolean | No | true | Enable/disable this provider. Set to false to hide from login page |
| `type` | string | Yes | - | Must be "oauth2" |
| `client_id` | string | Yes | - | OAuth2 client ID from IdP |
| `client_secret` | string | Yes | - | OAuth2 client secret from IdP |
| `scopes` | array | Yes | - | List of OAuth2 scopes to request |

#### OAuth2/OIDC with Discovery (Google, Microsoft, AWS)

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `discovery_url` | string | Yes | OIDC discovery endpoint URL |

#### OAuth2 Manual Configuration (GitHub, LinkedIn)

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `type` | string | Yes | Must be "oauth2" |
| `client_id` | string | Yes | OAuth2 client ID from IdP |
| `client_secret` | string | Yes | OAuth2 client secret from IdP |
| `authorize_url` | string | Yes | OAuth2 authorization endpoint |
| `token_url` | string | Yes | OAuth2 token endpoint |
| `userinfo_url` | string | No | User info endpoint (if not in token) |
| `scopes` | array | Yes | List of OAuth2 scopes to request |

## Environment Variables

### Basic Configuration

```bash
# Enable SSO
export SSO_ENABLED=true

# Authorization mode
export SSO_AUTHORIZATION_MODE=single_user  # or "enterprise"

# Session lifetime
export SSO_SESSION_LIFETIME_HOURS=24

# Single-user mode settings
export SSO_CONFIRMATION_CODE_EXPIRY_MINUTES=10
export SSO_MAX_CONFIRMATION_ATTEMPTS=3

# Enterprise mode settings
export SSO_AUTHORIZATION_API_URL=https://company.com/api/authorize
export SSO_AUTHORIZATION_API_TIMEOUT=5

# Invisible captcha (Cloudflare Turnstile)
export SSO_CAPTCHA_ENABLED=true
export SSO_CAPTCHA_SITE_KEY=turnstile_site_key
export SSO_CAPTCHA_SECRET_KEY=turnstile_secret_key
export SSO_CAPTCHA_PROVIDER=cloudflare_turnstile
export SSO_CAPTCHA_WIDGET_MODE=invisible
```

### Provider Configuration

#### Single Provider (Simplified)

```bash
# Provider selection
export SSO_PROVIDER=google  # or "microsoft", "github", "linkedin", "aws"

# Provider credentials
export SSO_CLIENT_ID=your_client_id
export SSO_CLIENT_SECRET=your_client_secret

# Optional: Microsoft tenant ID
export SSO_MICROSOFT_TENANT_ID=common

# Optional: AWS region
export SSO_AWS_REGION=us-west-2
```

#### Multiple Providers (Advanced)

```bash
# Google
export SSO_GOOGLE_CLIENT_ID=google_id
export SSO_GOOGLE_CLIENT_SECRET=google_secret

# Microsoft
export SSO_MICROSOFT_CLIENT_ID=microsoft_id
export SSO_MICROSOFT_CLIENT_SECRET=microsoft_secret
export SSO_MICROSOFT_TENANT_ID=common

# GitHub
export SSO_GITHUB_CLIENT_ID=github_id
export SSO_GITHUB_CLIENT_SECRET=github_secret

# LinkedIn
export SSO_LINKEDIN_CLIENT_ID=linkedin_id
export SSO_LINKEDIN_CLIENT_SECRET=linkedin_secret

# AWS
export SSO_AWS_CLIENT_ID=aws_id
export SSO_AWS_CLIENT_SECRET=aws_secret
export SSO_AWS_REGION=us-west-2
```

### Start with Environment Variables

```bash
python -m src.anthropic_server
```

## CLI Flags

### Basic Flags

```bash
python -m src.anthropic_server \
  --sso-enabled \
  --sso-auth-mode single_user \
  --sso-session-lifetime 24
```

### Single Provider Configuration

```bash
python -m src.anthropic_server \
  --sso-enabled \
  --sso-provider google \
  --sso-client-id "your_client_id" \
  --sso-client-secret "your_client_secret" \
  --sso-auth-mode single_user
```

### Complete Flag Reference

| Flag | Type | Description |
|------|------|-------------|
| `--sso-enabled` | boolean | Enable SSO authentication |
| `--sso-config PATH` | string | Path to SSO configuration file |
| `--sso-provider NAME` | string | Provider name (google, microsoft, github, linkedin, aws) |
| `--sso-client-id ID` | string | OAuth2 client ID |
| `--sso-client-secret SECRET` | string | OAuth2 client secret |
| `--sso-auth-mode MODE` | string | Authorization mode (single_user or enterprise) |
| `--sso-session-lifetime HOURS` | integer | Session lifetime in hours |
| `--sso-authorization-api-url URL` | string | Authorization API URL (enterprise mode) |
| `--sso-microsoft-tenant-id ID` | string | Microsoft tenant ID |
| `--sso-aws-region REGION` | string | AWS region for IAM Identity Center |

## Configuration Examples

### Example 1: Single-User with Google (YAML)

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

### Example 2: Single-User with Google (Environment Variables)

```bash
export SSO_ENABLED=true
export SSO_PROVIDER=google
export SSO_CLIENT_ID=123.apps.googleusercontent.com
export SSO_CLIENT_SECRET=GOCSPX-secret
export SSO_AUTHORIZATION_MODE=single_user
export SSO_SESSION_LIFETIME_HOURS=24
```

### Example 3: Single-User with Google (CLI Flags)

```bash
python -m src.anthropic_server \
  --sso-enabled \
  --sso-provider google \
  --sso-client-id "123.apps.googleusercontent.com" \
  --sso-client-secret "GOCSPX-secret" \
  --sso-auth-mode single_user \
  --sso-session-lifetime 24
```

### Example 4: Enterprise with Microsoft (YAML)

```yaml
sso:
  enabled: true
  authorization:
    mode: "enterprise"
    api_url: "https://company.com/api/authorize"
    api_timeout_seconds: 5
    session_lifetime_hours: 48
  providers:
    microsoft:
      type: "oauth2"
      client_id: "12345678-1234-1234-1234-123456789012"
      client_secret: "secret"
      discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

### Example 5: Multiple Providers (YAML)

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
    
    microsoft:
      type: "oauth2"
      client_id: "microsoft_id"
      client_secret: "microsoft_secret"
      discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
      scopes: ["openid", "email", "profile"]
```

## Provider-Specific Configuration

### Google

**Discovery URL**: `https://accounts.google.com/.well-known/openid-configuration`

**Required Scopes**: `["openid", "email", "profile"]`

**Configuration**:
```yaml
google:
  type: "oauth2"
  client_id: "YOUR_ID.apps.googleusercontent.com"
  client_secret: "GOCSPX-YOUR_SECRET"
  discovery_url: "https://accounts.google.com/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

### Microsoft Azure AD/Entra ID

**Discovery URL (Multi-tenant)**: `https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration`

**Discovery URL (Single-tenant)**: `https://login.microsoftonline.com/{TENANT_ID}/v2.0/.well-known/openid-configuration`

**Required Scopes**: `["openid", "email", "profile"]`

**Tenant Options**:
- `common` - Multi-tenant (personal + work/school)
- `organizations` - Work/school accounts only
- `consumers` - Personal Microsoft accounts only
- Specific tenant ID - Single tenant

**Configuration**:
```yaml
microsoft:
  type: "oauth2"
  client_id: "12345678-1234-1234-1234-123456789012"
  client_secret: "YOUR_SECRET"
  discovery_url: "https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

### GitHub

**Authorize URL**: `https://github.com/login/oauth/authorize`

**Token URL**: `https://github.com/login/oauth/access_token`

**Userinfo URL**: `https://api.github.com/user`

**Required Scopes**: `["user:email", "read:user"]`

**Configuration**:
```yaml
github:
  type: "oauth2"
  client_id: "Iv1.YOUR_CLIENT_ID"
  client_secret: "YOUR_SECRET"
  authorize_url: "https://github.com/login/oauth/authorize"
  token_url: "https://github.com/login/oauth/access_token"
  userinfo_url: "https://api.github.com/user"
  scopes: ["user:email", "read:user"]
```

### LinkedIn

**Authorize URL**: `https://www.linkedin.com/oauth/v2/authorization`

**Token URL**: `https://www.linkedin.com/oauth/v2/accessToken`

**Required Scopes**: `["openid", "profile", "email"]`

**Configuration**:
```yaml
linkedin:
  type: "oauth2"
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_SECRET"
  authorize_url: "https://www.linkedin.com/oauth/v2/authorization"
  token_url: "https://www.linkedin.com/oauth/v2/accessToken"
  scopes: ["openid", "profile", "email"]
```

### AWS IAM Identity Center

**Discovery URL**: `https://oidc.{REGION}.amazonaws.com/.well-known/openid-configuration`

**Required Scopes**: `["openid", "email", "profile"]`

**Regions**: Replace `{REGION}` with your AWS region (e.g., `us-west-2`, `eu-west-1`)

**Configuration**:
```yaml
aws:
  type: "oauth2"
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_SECRET"
  discovery_url: "https://oidc.us-west-2.amazonaws.com/.well-known/openid-configuration"
  scopes: ["openid", "email", "profile"]
```

## Security Best Practices

### Protecting Secrets

**Never commit secrets to version control**:

```yaml
# BAD - secrets in config file
sso:
  providers:
    google:
      client_secret: "GOCSPX-actual-secret"  # Don't do this!
```

**Use environment variables**:

```yaml
# GOOD - reference environment variables
sso:
  providers:
    google:
      client_secret: "${GOOGLE_CLIENT_SECRET}"
```

```bash
export GOOGLE_CLIENT_SECRET=GOCSPX-actual-secret
```

**Use secret managers** (AWS Secrets Manager, HashiCorp Vault, etc.):

```python
import boto3

secrets = boto3.client('secretsmanager')
secret = secrets.get_secret_value(SecretId='sso/google/client_secret')
os.environ['GOOGLE_CLIENT_SECRET'] = secret['SecretString']
```

### File Permissions

Restrict access to configuration files:

```bash
# Set restrictive permissions
chmod 600 config/sso_auth.yaml

# Verify permissions
ls -l config/sso_auth.yaml
# Should show: -rw------- (owner read/write only)
```

### Redirect URI Security

**Use exact matches**:
```yaml
# IdP configuration
redirect_uris:
  - "http://localhost:8080/auth/callback"  # Exact match required
```

**Use HTTPS in production**:
```yaml
# Production
redirect_uris:
  - "https://proxy.company.com/auth/callback"  # HTTPS only
```

**Minimize redirect URIs**:
```yaml
# Only add necessary URIs
redirect_uris:
  - "https://proxy.company.com/auth/callback"
  # Don't add unnecessary URIs
```

## Validation and Testing

### Validate Configuration

Test your configuration before starting the proxy:

```bash
# Dry-run mode (validates config without starting server)
python -m src.anthropic_server --sso-config config/sso_auth.yaml --validate-only
```

### Test Authentication Flow

1. Start the proxy:
```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

2. Make an unauthenticated request:
```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}'
```

3. Verify you receive a sandbox response with authentication URL

4. Open the authentication URL in a browser and complete the flow

### Debug Mode

Enable debug logging to troubleshoot configuration issues:

```bash
python -m src.anthropic_server \
  --sso-config config/sso_auth.yaml \
  --log-level DEBUG
```

## Troubleshooting

### Configuration Not Loading

**Symptom**: SSO not enabled despite configuration

**Solutions**:
- Verify file path is correct
- Check YAML syntax (use a YAML validator)
- Ensure file has correct permissions (readable by proxy process)
- Check for typos in configuration keys

### Provider Not Found

**Symptom**: "Provider 'google' not configured" error

**Solutions**:
- Verify provider name matches exactly (case-sensitive)
- Check provider section is properly indented in YAML
- Ensure provider has all required fields

### Invalid Client Credentials

**Symptom**: "Invalid client" or "Unauthorized" errors

**Solutions**:
- Double-check client ID and secret
- Verify credentials are for the correct environment (dev vs prod)
- Ensure redirect URI matches exactly in IdP configuration
- Check that credentials haven't expired or been revoked

### Environment Variables Not Working

**Symptom**: Configuration from environment variables not applied

**Solutions**:
- Verify environment variables are exported (use `echo $VAR_NAME`)
- Check variable names match exactly (case-sensitive)
- Ensure no typos in variable names
- Restart shell/terminal after setting variables

## Next Steps

- **[Identity Provider Setup](./sso_idp_setup.md)** - Configure specific identity providers
- **[Authorization Configuration](./sso_authorization.md)** - Set up authorization modes
- **[Agent Configuration](./sso_agent_setup.md)** - Configure AI agents with tokens
- **[Troubleshooting](./sso_troubleshooting.md)** - Common issues and solutions
