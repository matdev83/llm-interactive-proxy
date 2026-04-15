# Access Modes

Explicit security boundary enforcement through operational modes for local development and production deployments.

## Overview

The proxy supports two distinct access modes that enforce appropriate security boundaries based on your deployment context:

- **Single User Mode** (default): Designed for local development with a single developer. Allows OAuth-based connectors, optional authentication, and enforces localhost-only binding.
- **Multi User Mode**: Designed for production and shared deployments. Blocks OAuth-based connectors, requires authentication for non-localhost binding, and rejects desktop-specific features.

Access modes prevent common misconfigurations that could:
- Expose personal OAuth credentials in shared/production environments
- Allow unauthenticated remote access
- Enable desktop features on server deployments

**Key Characteristics:**
- Access mode is immutable after startup (no runtime switching)
- Mode is selected via CLI flags or configuration file
- Defaults to Single User Mode for backward compatibility

## Single User Mode

**Purpose**: Local development by a single developer.

### Allowed Behaviors

- **OAuth Connectors**: Full access to OAuth-based connectors (e.g., `gemini-oauth-auto`, `qwen-oauth`, `openai-codex`)
- **Host Binding**: Must bind to `127.0.0.1` only (localhost)
- **Authentication**: Optional - can be disabled for convenience
- **OAuth Debugging Flags**: Allowed (e.g., `--enable-gemini-oauth-auto-backend-debugging-override`)
- **OAuth Auto-Replacement**: `--allow-oauth-auto-replacement` flag is allowed
- **Desktop Notifications**: Allowed; see [Desktop notifications (defaults and precedence)](#desktop-notifications-defaults-and-precedence) below

### Desktop notifications (defaults and precedence)

The proxy can show **OS desktop notifications** for operator-relevant events (for example Gemini OAuth verification issues, Kiro monthly quota exhaustion when using the `kiro-oauth-auto` backend, and similar hooks). Whether they actually appear depends on **config, bind address, and access mode**.

**Auto-detection when `notifications.enabled` is unset (`null`)**

If you do **not** set `notifications.enabled` in YAML (and do not override via CLI/env), the effective setting is **automatic**:

- **On** when the bind host is considered local: `127.0.0.1`, `localhost`, or `::1`
- **Off** for other bind addresses (for example `0.0.0.0`)

The default application host is `127.0.0.1`. **Single User Mode always requires `host: 127.0.0.1`**, so a typical local dev setup with no notification config gets **notifications enabled by default**—you do **not** need `--enable-notifications` for that case.

**Explicit overrides (highest wins)**

1. CLI: `--enable-notifications` or `--disable-notifications` (forces on or off regardless of auto)
2. Environment: `LLM_PROXY_ENABLE_NOTIFICATIONS` (truthy/falsey string, when wired in your build)
3. YAML: `notifications.enabled: true` or `false`
4. Otherwise: auto-detection from bind host as above

Use **`--disable-notifications`** (or `notifications.enabled: false`) when you want silence on loopback. Use **`--enable-notifications`** mainly to **force on** after turning them off in config, or when you rely on explicit overrides rather than auto.

**Multi User Mode interaction**

Multi User Mode **rejects** desktop notifications entirely. Note the trap: on **`127.0.0.1`**, auto-detection still evaluates to **enabled**. So for `--multi-user-mode --host=127.0.0.1` you must **explicitly** set `notifications.enabled: false` or pass **`--disable-notifications`**—“leaving notifications unset” is **not** enough. For `0.0.0.0`, auto is off, but keeping `enabled: false` in production config is still clearer.

### Optional Installation for OAuth Connectors

Install the OAuth connector package extra before using OAuth backends:

```bash
pip install llm-interactive-proxy[oauth]
```

The optional package owns extracted OAuth connector implementations and exposes
them to core through plugin entry points.

### Restrictions

- **Host Binding**: Cannot bind to any IP address other than `127.0.0.1`

### Use Cases

- Local development and testing
- Personal AI agent experimentation
- Rapid prototyping with personal credentials
- Debugging OAuth flows

### Example Usage

```bash
# Minimal startup (defaults to Single User Mode)
./.venv/Scripts/python.exe -m src.core.cli

# Explicit Single User Mode with OAuth connector
./.venv/Scripts/python.exe -m src.core.cli --single-user-mode --default-backend gemini-oauth-auto:gemini-exp-1206

# With authentication disabled for convenience
./.venv/Scripts/python.exe -m src.core.cli --disable-auth

# Silence desktop notifications (default single-user on 127.0.0.1 has them ON via auto-detect)
./.venv/Scripts/python.exe -m src.core.cli --disable-notifications

# Force notifications ON (only needed if you disabled them in config or want an explicit override)
./.venv/Scripts/python.exe -m src.core.cli --enable-notifications
```

### Configuration File

```yaml
access_mode:
  mode: single_user

host: 127.0.0.1
port: 8000

auth:
  disable_auth: true  # Optional for local development

# Desktop notifications: omit this block entirely → auto (127.0.0.1 → enabled).
# Use enabled: false to turn them off. enabled: true is redundant on default loopback.
notifications:
  enabled: false
```

## Multi User Mode

**Purpose**: Production and shared deployments where multiple users access the proxy.

### Allowed Behaviors

- **Static Credential Connectors**: Full access to API key-based connectors (e.g., `openai`, `anthropic`, `gemini`)
- **Host Binding**: Can bind to any IP address (e.g., `0.0.0.0`, specific network interfaces)
- **Localhost Binding**: Can bind to `127.0.0.1` with or without authentication
- **Non-Localhost Binding**: Requires authentication (API keys or SSO)

### Restrictions

- **OAuth Connectors**: All OAuth-based connectors are blocked and filtered during startup
- **OAuth Debugging Flags**: All OAuth debugging override flags are rejected
- **OAuth Auto-Replacement**: `--allow-oauth-auto-replacement` flag is rejected
- **Desktop Notifications**: Desktop notifications are **rejected** when the effective setting is “enabled” (including **auto-enable on `127.0.0.1`** if `notifications.enabled` is left unset—see [Desktop notifications](#desktop-notifications-defaults-and-precedence))
- **Non-Localhost Without Auth**: Cannot bind to non-localhost addresses without authentication enabled

### Use Cases

- Team/organization proxy deployments
- Production environments
- Shared development servers
- Cloud/container deployments
- Multi-tenant scenarios

### Example Usage

```bash
# Multi User Mode with API key authentication
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1,key2

# Multi User Mode with SSO (requires SSO configuration)
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --sso-enabled

# Multi User Mode on localhost (auth optional)
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=127.0.0.1

# Multi User Mode with specific backend
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1 --default-backend openai:gpt-4o
```

### Configuration File

```yaml
access_mode:
  mode: multi_user

host: 0.0.0.0
port: 8000

auth:
  disable_auth: false
  api_keys:
    - "production-key-1"
    - "production-key-2"

# OR use SSO
sso:
  enabled: true
  # ... SSO configuration ...

notifications:
  enabled: false  # Required in Multi User Mode (or use --disable-notifications)
```

## Configuration

### CLI Flags

| Flag | Description | Default |
|------|-------------|---------|
| `--single-user-mode` | Enable Single User Mode | Implied if no flag specified |
| `--multi-user-mode` | Enable Multi User Mode | Not set |

**Mutual Exclusivity**: Cannot specify both `--single-user-mode` and `--multi-user-mode` simultaneously.

### Configuration Precedence

1. **CLI flags** (highest priority)
2. **Environment variables**
3. **Configuration file** (`config.yaml`)
4. **Default** (Single User Mode)

### Environment Variables

```bash
# Set access mode via environment
export LLM_PROXY_ACCESS_MODE=multi_user

# Then start proxy
./.venv/Scripts/python.exe -m src.core.cli --host=0.0.0.0 --api-keys key1
```

## Validation Rules

The proxy validates access mode configuration during startup and refuses to start if validation fails.

### Single User Mode Validation

| Check | Rule | Error Example |
|-------|------|---------------|
| Host Binding | Must be `127.0.0.1` | "Single User Mode requires binding to 127.0.0.1 only. Current host: 0.0.0.0. Use --multi-user-mode for remote access." |

### Multi User Mode Validation

| Check | Rule | Error Example |
|-------|------|---------------|
| Non-Localhost Authentication | Non-localhost binding requires authentication | "Multi User Mode requires authentication when binding to non-localhost addresses. Current host: 0.0.0.0. Enable authentication via API keys or SSO." |
| OAuth Debugging Flags | OAuth override flags are rejected | "OAuth debugging override flags are not allowed in Multi User Mode: --enable-gemini-oauth-auto-backend-debugging-override. OAuth connectors are blocked in production deployments." |
| OAuth Auto-Replacement | `--allow-oauth-auto-replacement` is rejected | "OAuth auto-replacement (--allow-oauth-auto-replacement) is not allowed in Multi User Mode. OAuth connectors are blocked in production deployments." |
| Desktop Notifications | Effective notifications must be **off** (including **auto-on** on `127.0.0.1` when `enabled` is unset) | "Desktop notifications are not allowed in Multi User Mode. Multi User Mode is for dedicated servers, not desktop computers. Use --disable-notifications or switch to Single User Mode." |

### Error Message Format

All validation errors provide:
1. **What failed**: Clear statement of which validation rule was violated
2. **Current configuration**: Shows the conflicting setting
3. **How to fix**: Actionable guidance on resolving the issue
4. **Alternative options**: Suggests valid alternatives (e.g., switching modes)

## OAuth Connector Filtering

### What Gets Filtered

In Multi User Mode, the following connectors are automatically filtered during startup:

**By Naming Pattern:**
- Connectors containing `-oauth-` (e.g., `gemini-oauth-auto`, `gemini-oauth-free`, `gemini-oauth-plan`)
- Connectors ending with `-oauth` (e.g., `qwen-oauth`)

**By Property:**
- Connectors with `has_static_credentials = False`

**Known OAuth Connectors:**
- `gemini-oauth-auto`
- `gemini-oauth-free`
- `gemini-oauth-plan`
- `qwen-oauth`
- `openai-codex` (uses OAuth via auth.json)

### Filtering Behavior

```
# Single User Mode startup logs
INFO: Starting LLM Proxy in Single User Mode (default)
DEBUG: Loaded OAuth connectors: gemini-oauth-auto, qwen-oauth, openai-codex

# Multi User Mode startup logs
INFO: Starting LLM Proxy in Multi User Mode
INFO: Skipped OAuth connectors in Multi User Mode (OAuth not allowed in production)
```

### Backend Registry Impact

- **Single User Mode**: OAuth connectors appear in backend registry and can be selected
- **Multi User Mode**: OAuth connectors never appear in backend registry, requests to OAuth backends fail with clear error

## Health Endpoint

### Checking Current Mode

Query the `/internal/health` endpoint to verify the current access mode:

```bash
curl http://localhost:8000/internal/health | jq .access_mode
```

**Response:**

```json
{
  "access_mode": "single_user",
  "service_provider_present": true,
  "IRequestProcessor_resolvable": true,
  ...
}
```

**Possible Values:**
- `"single_user"`: Running in Single User Mode
- `"multi_user"`: Running in Multi User Mode

## Migration Guide

### From Default (Single User) to Multi User Mode

If you're currently running the proxy without explicit access mode configuration and want to deploy to production:

**Step 1: Review Your Configuration**

```bash
# Check if you're using OAuth connectors
grep -r "oauth" config/config.yaml

# Check current backend selection
curl http://localhost:8000/v1/models | jq '.data[] | select(.id | contains("oauth"))'
```

**Step 2: Switch to Static Credential Connectors**

Replace OAuth backends with API key-based alternatives:

| OAuth Connector | Static Credential Alternative |
|----------------|-------------------------------|
| `gemini-oauth-auto` | `gemini` (requires `GEMINI_API_KEY`) |
| `qwen-oauth` | `qwen` (requires API key configuration) |
| `openai-codex` | `openai` (requires `OPENAI_API_KEY`) |

**Step 3: Enable Authentication**

```yaml
# config/config.yaml
auth:
  disable_auth: false
  api_keys:
    - "your-production-key-1"
    - "your-production-key-2"
```

Or use SSO (see [SSO Authentication Guide](sso-authentication.md)).

**Step 4: Update Startup Command**

```bash
# Old (Single User Mode, implicit)
./.venv/Scripts/python.exe -m src.core.cli

# New (Multi User Mode, explicit)
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0
```

**Step 5: Disable Desktop Notifications**

Multi User Mode always rejects enabled desktop notifications. If your host is `127.0.0.1`, **auto-detection still enables notifications** when `notifications.enabled` is unset, so you **must** disable them explicitly:

```yaml
# config/config.yaml
notifications:
  enabled: false
```

Or pass `--disable-notifications` on the command line.

Single User Mode on loopback did **not** require `--enable-notifications` for notifications to work; removing that flag alone does not satisfy Multi User Mode if notifications are still “on” via auto or YAML.

**Step 6: Verify Configuration**

```bash
# Start the proxy
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0

# Check access mode
curl http://localhost:8000/internal/health | jq .access_mode
# Should return: "multi_user"

# Verify OAuth connectors are filtered
curl http://localhost:8000/v1/models | jq '.data[] | select(.id | contains("oauth"))'
# Should return: empty (no OAuth connectors)
```

## Troubleshooting

### Error: "Cannot specify both --single-user-mode and --multi-user-mode"

**Cause**: Both access mode flags specified simultaneously.

**Solution**: Remove one of the flags. Choose the appropriate mode for your deployment:
```bash
# Wrong
./.venv/Scripts/python.exe -m src.core.cli --single-user-mode --multi-user-mode

# Correct - Single User Mode
./.venv/Scripts/python.exe -m src.core.cli --single-user-mode

# Correct - Multi User Mode
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode
```

### Error: "Single User Mode requires binding to 127.0.0.1 only"

**Cause**: Attempting to bind to a non-localhost address in Single User Mode.

**Solution**: Either bind to localhost or switch to Multi User Mode:
```bash
# Option 1: Bind to localhost
./.venv/Scripts/python.exe -m src.core.cli --host=127.0.0.1

# Option 2: Switch to Multi User Mode
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1
```

### Error: "Multi User Mode requires authentication when binding to non-localhost addresses"

**Cause**: Attempting to bind to a non-localhost address without authentication in Multi User Mode.

**Solution**: Enable authentication via API keys or SSO:
```bash
# With API keys
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1,key2

# With SSO (requires SSO configuration)
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --sso-enabled

# Or bind to localhost without authentication requirement
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=127.0.0.1
```

### Error: "OAuth debugging override flags are not allowed in Multi User Mode"

**Cause**: Attempting to use OAuth debugging flags in Multi User Mode.

**Solution**: Remove the OAuth debugging override flags:
```bash
# Wrong
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --enable-gemini-oauth-auto-backend-debugging-override

# Correct
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1
```

**Why**: OAuth connectors are designed for personal credentials and should not be used in production/shared environments.

### Error: "OAuth auto-replacement is not allowed in Multi User Mode"

**Cause**: `--allow-oauth-auto-replacement` flag specified in Multi User Mode.

**Solution**: Remove the flag:
```bash
# Wrong
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --allow-oauth-auto-replacement

# Correct
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --host=0.0.0.0 --api-keys key1
```

### Error: "Desktop notifications are not allowed in Multi User Mode"

**Cause**: Desktop notifications are **enabled** for the resolved configuration. That includes **`notifications.enabled: true`**, CLI `--enable-notifications`, **or** leaving `enabled` unset while binding to `127.0.0.1` (auto-detect turns notifications **on** for localhost).

**Solution**: Disable notifications or switch to Single User Mode:
```bash
# Option 1: Disable notifications (CLI)
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --disable-notifications

# Option 2: Disable in config (required for multi-user on 127.0.0.1 if auto would enable)
# config/config.yaml
notifications:
  enabled: false

# Option 3: Switch to Single User Mode (if appropriate). Notifications stay on by default on 127.0.0.1 unless you disable them.
./.venv/Scripts/python.exe -m src.core.cli --single-user-mode
```

**Why**: Multi User Mode targets server-style deployments; desktop notifications are treated as a single-user / workstation feature.

### OAuth Connector Not Found

**Symptom**: Requests to OAuth backends fail with "Backend not found" error in Multi User Mode.

**Cause**: OAuth connectors are filtered in Multi User Mode.

**Solution**: Switch to static credential connectors:
```bash
# Instead of gemini-oauth-auto, use gemini with API key
export GEMINI_API_KEY="your-api-key"
./.venv/Scripts/python.exe -m src.core.cli --multi-user-mode --default-backend gemini:gemini-exp-1206
```

In Single User Mode, ensure the optional package is installed when OAuth
connectors are not available:

```bash
pip install llm-interactive-proxy[oauth]
```

### Health Endpoint Shows Wrong Mode

**Symptom**: `/internal/health` reports unexpected access mode.

**Diagnosis**:
```bash
# Check health endpoint
curl http://localhost:8000/internal/health | jq .access_mode

# Check startup logs
grep "Starting LLM Proxy" var/logs/llm-proxy.log
```

**Solution**: Verify configuration precedence (CLI flags override config file).

## Best Practices

### Development

1. **Use Single User Mode**: Default mode is appropriate for local development
2. **Keep OAuth Credentials Private**: Never commit OAuth credentials to version control
3. **Disable Authentication**: Use `--disable-auth` for convenience in local development
4. **Desktop Notifications**: On default loopback (`127.0.0.1`), they are **already on** via auto-detect unless you set `notifications.enabled: false` or `--disable-notifications`. Use those when you want a silent tray; use `--enable-notifications` only to **force** them on after disabling in config

### Production

1. **Use Multi User Mode**: Explicitly specify `--multi-user-mode` for clarity
2. **Enable Authentication**: Always require API keys or SSO for non-localhost binding
3. **Use Static Credentials**: Only use API key-based connectors
4. **Disable Notifications**: Server environments don't need desktop notifications
5. **Monitor Access Mode**: Regularly check `/internal/health` to verify mode
6. **Document Mode Choice**: Add comments to configuration files explaining mode selection

### Security

1. **Never Share OAuth Credentials**: OAuth connectors use personal credentials
2. **Rotate API Keys**: Regularly rotate production API keys
3. **Audit Access Mode**: Verify access mode matches deployment context
4. **Review Logs**: Monitor startup logs for OAuth connector filtering messages
5. **Validate Configuration**: Test mode switching in staging before production

## Related Documentation

- [Quick Start Guide](quick-start.md)
- [Configuration Guide](configuration.md)
- [SSO Authentication](sso-authentication.md)
- [Backend Overview](backends/overview.md)
- [Security Best Practices](security/authentication.md)
