# SSO Troubleshooting Guide

This guide helps you diagnose and resolve common issues with SSO authentication.

## Quick Diagnostics

### Check Proxy Status

```bash
# Check if proxy is running
curl http://localhost:8080/health

# Expected response: {"status": "ok"}
```

### Check SSO Configuration

```bash
# Validate configuration
python -m src.anthropic_server --sso-config config/sso_auth.yaml --validate-only

# Check for syntax errors or missing fields
```

### Enable Debug Logging

```bash
# Start proxy with debug logging
python -m src.anthropic_server \
  --sso-config config/sso_auth.yaml \
  --log-level DEBUG

# Watch logs in real-time
tail -f /var/log/llm-proxy/proxy.log
```

## Common SSO Configuration Issues

### Issue: SSO Not Enabled

**Symptoms**:
- Requests are processed without authentication
- No login banner displayed
- Configuration appears to be ignored

**Diagnosis**:
```bash
# Check if SSO is enabled in config
grep -A 5 "sso:" config/sso_auth.yaml

# Check environment variables
echo $SSO_ENABLED

# Check CLI flags
ps aux | grep anthropic_server
```

**Solutions**:

1. **Verify configuration file is loaded**:
```bash
# Explicitly specify config file
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

2. **Check YAML syntax**:
```yaml
# CORRECT
sso:
  enabled: true

# INCORRECT (wrong indentation)
sso:
enabled: true
```

3. **Verify enabled flag**:
```yaml
sso:
  enabled: true  # Must be true, not "true" or 1
```

---

### Issue: Provider Not Configured

**Symptoms**:
- "Provider 'google' not configured" error
- Authentication flow doesn't start
- Provider selection page shows no providers

**Diagnosis**:
```bash
# Check provider configuration
grep -A 10 "providers:" config/sso_auth.yaml

# Verify provider name
# Names are case-sensitive: "google" not "Google"
```

**Solutions**:

1. **Check provider name matches exactly**:
```yaml
# CORRECT
providers:
  google:  # lowercase
    type: "oauth2"

# INCORRECT
providers:
  Google:  # uppercase won't work
    type: "oauth2"
```

2. **Verify all required fields are present**:
```yaml
google:
  type: "oauth2"              # Required
  client_id: "..."            # Required
  client_secret: "..."        # Required
  discovery_url: "..."        # Required for OIDC
  scopes: ["openid", "email"] # Required
```

3. **Check indentation**:
```yaml
# CORRECT
sso:
  providers:
    google:
      type: "oauth2"

# INCORRECT (wrong indentation)
sso:
providers:
  google:
    type: "oauth2"
```

---

### Issue: Invalid Client Credentials

**Symptoms**:
- "Invalid client" error from IdP
- "Unauthorized" error during OAuth2 flow
- Authentication fails after IdP login

**Diagnosis**:
```bash
# Check client ID and secret
grep -A 5 "google:" config/sso_auth.yaml

# Verify credentials in IdP console
# Google: https://console.cloud.google.com/apis/credentials
# Microsoft: https://portal.azure.com/#view/Microsoft_AAD_IAM/ActiveDirectoryMenuBlade/~/RegisteredApps
```

**Solutions**:

1. **Verify credentials are correct**:
   - Copy client ID and secret directly from IdP console
   - Check for extra spaces or line breaks
   - Ensure credentials are for the correct environment (dev vs prod)

2. **Check redirect URI matches**:
```yaml
# In IdP configuration
redirect_uris:
  - "http://localhost:8080/auth/callback"  # Must match exactly

# In proxy configuration (automatic)
# Proxy uses: http://{host}:{port}/auth/callback
```

3. **Verify credentials haven't expired**:
   - Some IdPs expire credentials after inactivity
   - Regenerate credentials if needed

---

### Issue: Redirect URI Mismatch

**Symptoms**:
- "Redirect URI mismatch" error from IdP
- "Invalid redirect_uri" error
- Authentication flow fails after IdP login

**Diagnosis**:
```bash
# Check proxy host and port
grep -E "host|port" config/sso_auth.yaml

# Expected redirect URI format:
# http://{host}:{port}/auth/callback
```

**Solutions**:

1. **Ensure exact match in IdP configuration**:
```
# If proxy runs on localhost:8080
Redirect URI: http://localhost:8080/auth/callback

# If proxy runs on custom port
Redirect URI: http://localhost:3000/auth/callback

# If proxy runs on domain
Redirect URI: https://proxy.company.com/auth/callback
```

2. **No trailing slashes**:
```
# CORRECT
http://localhost:8080/auth/callback

# INCORRECT
http://localhost:8080/auth/callback/
```

3. **Use HTTPS in production**:
```
# Development
http://localhost:8080/auth/callback

# Production
https://proxy.company.com/auth/callback
```

## Token Expiry and Re-Authentication Issues

### Issue: Session Expired

**Symptoms**:
- "Session expired" message in agent
- Sandbox response with re-authentication URL
- Agent was working, now requires authentication

**Diagnosis**:
```bash
# Check session lifetime configuration
grep "session_lifetime_hours" config/sso_auth.yaml

# Check token status in database
sqlite3 /path/to/sso_auth.db "SELECT user_email, auth_expires_at FROM agent_tokens WHERE is_active = 1;"
```

**Solutions**:

1. **Re-authenticate via web interface**:
   - Open the re-authentication URL provided in the response
   - Log in with your identity provider
   - Session is restored automatically
   - Agent continues working with same token

2. **Increase session lifetime** (if appropriate):
```yaml
authorization:
  session_lifetime_hours: 48  # Increase from default 24
```

3. **Verify system time is correct**:
```bash
# Check system time
date

# Sync time if needed
sudo ntpdate -s time.nist.gov
```

---

### Issue: Token Not Working After Re-Authentication

**Symptoms**:
- Re-authenticated successfully
- Agent still receives sandbox response
- Token appears invalid

**Diagnosis**:
```bash
# Check token status in database
sqlite3 /path/to/sso_auth.db "SELECT user_email, is_authenticated, auth_expires_at FROM agent_tokens WHERE token_hash = ?;"

# Check proxy logs for authentication errors
grep "authentication failed" /var/log/llm-proxy/proxy.log
```

**Solutions**:

1. **Verify token is configured correctly in agent**:
   - Check for extra spaces or line breaks
   - Ensure token is used as Bearer token
   - Verify agent configuration file is saved

2. **Check database was updated**:
```sql
-- Manually update if needed
UPDATE agent_tokens
SET is_authenticated = 1,
    auth_expires_at = datetime('now', '+24 hours')
WHERE token_hash = ?;
```

3. **Restart agent**:
   - Some agents cache authentication state
   - Restart agent to reload configuration

---

### Issue: Frequent Re-Authentication Required

**Symptoms**:
- Session expires too quickly
- Need to re-authenticate multiple times per day
- Session lifetime seems shorter than configured

**Diagnosis**:
```bash
# Check configured session lifetime
grep "session_lifetime_hours" config/sso_auth.yaml

# Check actual expiry times in database
sqlite3 /path/to/sso_auth.db "SELECT user_email, created_at, auth_expires_at FROM agent_tokens WHERE is_active = 1;"
```

**Solutions**:

1. **Increase session lifetime**:
```yaml
authorization:
  session_lifetime_hours: 48  # Or higher
```

2. **Check for clock skew**:
```bash
# Ensure server and client clocks are synchronized
sudo ntpdate -s time.nist.gov
```

3. **Review IdP session policies**:
   - Some IdPs have their own session limits
   - Check IdP configuration for session timeout settings

## Authorization API Issues (Enterprise Mode)

### Issue: Authorization API Not Responding

**Symptoms**:
- "Authorization API timeout" error
- "Failed to connect to authorization API" error
- All users denied access

**Diagnosis**:
```bash
# Test API connectivity
curl -X POST http://company.com/api/authorize \
  -H "Content-Type: application/json" \
  -d '{"user_email": "test@example.com", "client_ip": "127.0.0.1"}'

# Check API logs
# Check network connectivity
ping company.com
```

**Solutions**:

1. **Verify API URL is correct**:
```yaml
authorization:
  api_url: "https://company.com/api/authorize"  # Check protocol, domain, path
```

2. **Increase timeout if API is slow**:
```yaml
authorization:
  api_timeout_seconds: 10  # Increase from default 5
```

3. **Check network connectivity**:
   - Verify proxy can reach API server
   - Check firewall rules
   - Verify DNS resolution

4. **Temporarily switch to single-user mode**:
```yaml
authorization:
  mode: "single_user"  # Fallback while debugging API
```

---

### Issue: Authorization API Always Denies Access

**Symptoms**:
- All users denied access
- "Access denied" message for all authentication attempts
- API returns `{"authorized": false}`

**Diagnosis**:
```bash
# Test API with known-good user
curl -X POST http://company.com/api/authorize \
  -H "Content-Type: application/json" \
  -d '{"user_email": "admin@example.com", "client_ip": "127.0.0.1"}'

# Check API logs for authorization decisions
```

**Solutions**:

1. **Verify user is in allowed list**:
   - Check API's user database/configuration
   - Ensure user email matches exactly (case-sensitive)
   - Verify user has required roles/groups

2. **Check API logic**:
```python
# Example: Verify allowed users list
ALLOWED_USERS = {
    "alice@example.com",  # Check email format
    "bob@example.com"
}
```

3. **Review API logs**:
   - Check why users are being denied
   - Look for error messages or exceptions

---

### Issue: Authorization API Returns Errors

**Symptoms**:
- "Authorization API error" in proxy logs
- HTTP 500 errors from API
- Intermittent authorization failures

**Diagnosis**:
```bash
# Check API logs for errors
tail -f /var/log/authorization-api/error.log

# Test API independently
curl -v -X POST http://company.com/api/authorize \
  -H "Content-Type: application/json" \
  -d '{"user_email": "test@example.com", "client_ip": "127.0.0.1"}'
```

**Solutions**:

1. **Fix API errors**:
   - Review API logs for stack traces
   - Check database connectivity
   - Verify external dependencies (LDAP, etc.)

2. **Implement proper error handling**:
```python
@app.route("/api/authorize", methods=["POST"])
def authorize():
    try:
        # Authorization logic
        return jsonify({"authorized": True})
    except Exception as e:
        app.logger.error(f"Authorization error: {e}")
        return jsonify({
            "authorized": False,
            "reason": "Internal error"
        }), 500
```

3. **Add health check endpoint**:
```python
@app.route("/health", methods=["GET"])
def health():
    # Check database, LDAP, etc.
    return jsonify({"status": "ok"})
```

## Confirmation Code Issues (Single-User Mode)

### Issue: Confirmation Code Not Appearing

**Symptoms**:
- No confirmation code in server console
- Web page says "Check server console" but no code visible
- Authentication completes but no code logged

**Diagnosis**:
```bash
# Check log level
grep "log-level" /proc/$(pgrep -f anthropic_server)/cmdline

# Check logs for confirmation code
grep "Confirmation Code" /var/log/llm-proxy/proxy.log
```

**Solutions**:

1. **Set log level to WARNING or lower**:
```bash
python -m src.anthropic_server \
  --sso-config config/sso_auth.yaml \
  --log-level WARNING  # or INFO, DEBUG
```

2. **Check authorization mode**:
```yaml
authorization:
  mode: "single_user"  # Must be single_user, not enterprise
```

3. **Review logs for errors**:
```bash
# Check for errors during authorization
grep -i "error" /var/log/llm-proxy/proxy.log | tail -20
```

---

### Issue: Confirmation Code Expired

**Symptoms**:
- "Confirmation code expired" error
- Code was valid but now rejected
- Timeout during code entry

**Diagnosis**:
```bash
# Check code expiry configuration
grep "confirmation_code_expiry_minutes" config/sso_auth.yaml

# Check system time
date
```

**Solutions**:

1. **Re-authenticate to get new code**:
   - Start SSO flow again
   - New code will be generated

2. **Increase expiry time**:
```yaml
authorization:
  confirmation_code_expiry_minutes: 15  # Increase from default 10
```

3. **Verify system time is correct**:
```bash
# Sync time
sudo ntpdate -s time.nist.gov
```

---

### Issue: Too Many Failed Attempts

**Symptoms**:
- "Maximum attempts exceeded" error
- Locked out after 3 failed attempts
- Cannot enter code anymore

**Diagnosis**:
```bash
# Check attempt limit configuration
grep "max_confirmation_attempts" config/sso_auth.yaml

# Check rate limit records
sqlite3 /path/to/sso_auth.db "SELECT * FROM rate_limits;"
```

**Solutions**:

1. **Re-authenticate via SSO**:
   - Start SSO flow again to get new code
   - Attempts counter resets

2. **Verify code is correct**:
   - Check for typos
   - Ensure no spaces or extra characters
   - Code is case-sensitive (if applicable)

3. **Increase attempt limit** (if appropriate):
```yaml
authorization:
  max_confirmation_attempts: 5  # Increase from default 3
```

---

### Issue: Rate Limited

**Symptoms**:
- "Please wait before trying again" message
- Exponential backoff delay
- Cannot start new SSO flow

**Diagnosis**:
```bash
# Check rate limit records
sqlite3 /path/to/sso_auth.db "SELECT identifier, failed_attempts, blocked_until FROM rate_limits;"

# Check current time vs blocked_until
date
```

**Solutions**:

1. **Wait for backoff period**:
   - Backoff increases exponentially: 2s, 4s, 8s, 16s, etc.
   - Maximum wait: 5 minutes

2. **Clear rate limit** (if appropriate):
```sql
-- Clear rate limit for specific IP
DELETE FROM rate_limits WHERE identifier = '192.168.1.100';

-- Clear all rate limits (use with caution)
DELETE FROM rate_limits;
```

3. **Adjust rate limit settings** (future feature):
```yaml
authorization:
  rate_limit:
    max_attempts: 10
    backoff_multiplier: 2
    max_backoff_seconds: 300
```

## Agent Configuration Issues

### Issue: Agent Not Using Token

**Symptoms**:
- Agent receives sandbox response
- Token appears to be ignored
- Authentication required despite token configuration

**Diagnosis**:
```bash
# Check agent configuration
cat ~/.continue/config.json  # Continue
cat ~/.cursor/config.json    # Cursor
cat ~/.aider.conf.yml        # Aider

# Test token with curl
curl http://localhost:8080/v1/chat/completions \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}'
```

**Solutions**:

1. **Verify token is configured correctly**:
   - Check for extra spaces or line breaks
   - Ensure token is complete (no truncation)
   - Verify configuration file is saved

2. **Check token format**:
```json
// CORRECT
{
  "apiKey": "your-complete-token-here"
}

// INCORRECT (truncated)
{
  "apiKey": "your-complete-token-he..."
}
```

3. **Restart agent**:
   - Some agents cache configuration
   - Restart to reload settings

---

### Issue: Wrong Base URL

**Symptoms**:
- Connection errors
- "404 Not Found" errors
- Agent cannot reach proxy

**Diagnosis**:
```bash
# Check agent base URL configuration
grep -i "base" ~/.continue/config.json

# Test base URL
curl http://localhost:8080/v1/models
```

**Solutions**:

1. **Verify base URL format**:
```json
// CORRECT
{
  "apiBase": "http://localhost:8080/v1"
}

// INCORRECT (missing /v1)
{
  "apiBase": "http://localhost:8080"
}

// INCORRECT (extra slash)
{
  "apiBase": "http://localhost:8080/v1/"
}
```

2. **Check proxy is running on expected port**:
```bash
# Check proxy port
netstat -tlnp | grep 8080

# Or use lsof
lsof -i :8080
```

3. **Verify hostname/IP**:
```bash
# For local proxy
apiBase: "http://localhost:8080/v1"

# For remote proxy
apiBase: "https://proxy.company.com/v1"
```

## Database Issues

### Issue: Database Locked

**Symptoms**:
- "Database is locked" error
- Cannot write to database
- Concurrent access errors

**Diagnosis**:
```bash
# Check for processes using database
lsof /path/to/sso_auth.db

# Check database integrity
sqlite3 /path/to/sso_auth.db "PRAGMA integrity_check;"
```

**Solutions**:

1. **Close other connections**:
```bash
# Kill processes using database
lsof /path/to/sso_auth.db | awk 'NR>1 {print $2}' | xargs kill
```

2. **Enable WAL mode** (Write-Ahead Logging):
```sql
PRAGMA journal_mode=WAL;
```

3. **Increase timeout**:
```python
# In database connection code
conn = sqlite3.connect('sso_auth.db', timeout=30.0)
```

---

### Issue: Database Corruption

**Symptoms**:
- "Database disk image is malformed" error
- Cannot read from database
- Proxy fails to start

**Diagnosis**:
```bash
# Check database integrity
sqlite3 /path/to/sso_auth.db "PRAGMA integrity_check;"

# Check file permissions
ls -l /path/to/sso_auth.db
```

**Solutions**:

1. **Restore from backup**:
```bash
# Restore database from backup
cp /path/to/backup/sso_auth.db /path/to/sso_auth.db
```

2. **Attempt recovery**:
```bash
# Dump and recreate database
sqlite3 /path/to/sso_auth.db ".dump" > dump.sql
mv /path/to/sso_auth.db /path/to/sso_auth.db.corrupt
sqlite3 /path/to/sso_auth.db < dump.sql
```

3. **Recreate database** (last resort):
```bash
# Backup corrupt database
mv /path/to/sso_auth.db /path/to/sso_auth.db.corrupt

# Start proxy (will create new database)
python -m src.anthropic_server --sso-config config/sso_auth.yaml

# Users will need to re-authenticate
```

## Network and Connectivity Issues

### Issue: Cannot Reach IdP

**Symptoms**:
- "Failed to connect to identity provider" error
- Timeout during OAuth2 flow
- DNS resolution errors

**Diagnosis**:
```bash
# Test IdP connectivity
curl -I https://accounts.google.com

# Check DNS resolution
nslookup accounts.google.com

# Check network connectivity
ping accounts.google.com
```

**Solutions**:

1. **Check network connectivity**:
   - Verify internet connection
   - Check firewall rules
   - Verify proxy settings (if behind corporate proxy)

2. **Configure HTTP proxy** (if needed):
```bash
export HTTP_PROXY=http://corporate-proxy:8080
export HTTPS_PROXY=http://corporate-proxy:8080
```

3. **Check DNS settings**:
```bash
# Verify DNS servers
cat /etc/resolv.conf

# Test with different DNS
nslookup accounts.google.com 8.8.8.8
```

---

### Issue: Proxy Not Accessible

**Symptoms**:
- "Connection refused" error
- Cannot reach proxy from agent
- Timeout errors

**Diagnosis**:
```bash
# Check if proxy is running
ps aux | grep anthropic_server

# Check if port is listening
netstat -tlnp | grep 8080

# Test connectivity
curl http://localhost:8080/health
```

**Solutions**:

1. **Start proxy if not running**:
```bash
python -m src.anthropic_server --sso-config config/sso_auth.yaml
```

2. **Check firewall rules**:
```bash
# Check iptables
sudo iptables -L -n

# Check firewalld
sudo firewall-cmd --list-all
```

3. **Verify bind address**:
```yaml
# Listen on all interfaces
server:
  host: "0.0.0.0"
  port: 8080

# Listen on localhost only
server:
  host: "127.0.0.1"
  port: 8080
```

## Getting Help

### Collect Diagnostic Information

When reporting issues, include:

1. **Proxy version**:
```bash
python -m src.anthropic_server --version
```

2. **Configuration** (redact secrets):
```bash
cat config/sso_auth.yaml | sed 's/client_secret:.*/client_secret: REDACTED/'
```

3. **Logs** (last 50 lines):
```bash
tail -50 /var/log/llm-proxy/proxy.log
```

4. **Error messages**:
   - Full error text
   - Stack traces (if available)
   - Timestamps

5. **Steps to reproduce**:
   - What you did
   - What you expected
   - What actually happened

### Enable Verbose Logging

```bash
python -m src.anthropic_server \
  --sso-config config/sso_auth.yaml \
  --log-level DEBUG \
  --log-file /tmp/debug.log
```

### Test in Isolation

```bash
# Test SSO flow with curl
curl -v http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}'

# Test authorization API independently
curl -v -X POST http://company.com/api/authorize \
  -H "Content-Type: application/json" \
  -d '{"user_email": "test@example.com", "client_ip": "127.0.0.1"}'
```

## Next Steps

- **[Configuration Options](./sso_configuration.md)** - Complete configuration reference
- **[Security Considerations](./sso_security.md)** - Security best practices
- **[Agent Configuration](./sso_agent_setup.md)** - Configure AI agents
