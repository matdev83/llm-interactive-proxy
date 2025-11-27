# Brute-Force Protection

Automatic protection against repeated invalid API key authentication attempts.

## Overview

The proxy includes built-in brute-force protection that tracks invalid authentication attempts per client IP address. When a client exceeds the allowed number of failed attempts, the proxy automatically blocks further requests from that IP for a progressively increasing duration. This prevents attackers from guessing API keys through repeated trial-and-error attempts.

Brute-force protection is enabled by default and works transparently alongside the authentication system.

## Key Features

- Per-IP tracking of invalid authentication attempts
- Exponential backoff blocking with configurable multiplier
- Automatic reset on successful authentication
- Configurable attempt limits and time windows
- Trusted IP bypass for internal services
- Endpoint bypass list for public resources (docs, health checks)
- Detailed logging of blocked attempts

## How It Works

1. **Tracking**: Each client IP's failed authentication attempts are tracked in memory
2. **Threshold**: After exceeding the maximum allowed attempts, the IP is blocked
3. **Blocking**: Blocked IPs receive `429 Too Many Requests` responses with a `Retry-After` header
4. **Exponential Backoff**: Block duration doubles with each repeated failure (up to a maximum)
5. **Reset**: Successful authentication immediately resets the failure counter for that IP
6. **Expiration**: Failed attempt counters expire after the configured TTL (time-to-live)

## Default Behavior

- **Max Failed Attempts**: 5 attempts per IP
- **Time Window**: 15 minutes (900 seconds)
- **Initial Block Duration**: 30 seconds
- **Block Multiplier**: 2.0 (doubles each time)
- **Maximum Block Duration**: 1 hour (3600 seconds)

**Example Blocking Sequence**:

1. First 5 invalid attempts: Allowed (within 15-minute window)
2. 6th invalid attempt: Blocked for 30 seconds
3. 7th invalid attempt (after 30s): Blocked for 60 seconds
4. 8th invalid attempt (after 60s): Blocked for 120 seconds
5. 9th invalid attempt (after 120s): Blocked for 240 seconds
6. Further attempts: Blocked for 3600 seconds (max cap)

## Configuration

### CLI Arguments

```bash
# Enable/disable brute-force protection
python -m src.core.cli --enable-brute-force-protection
python -m src.core.cli --disable-brute-force-protection

# Configure thresholds
python -m src.core.cli \
  --auth-max-failed-attempts 10 \
  --auth-brute-force-ttl 1800 \
  --auth-brute-force-initial-block 60 \
  --auth-brute-force-multiplier 2.5 \
  --auth-brute-force-max-block 7200
```

**CLI Flags**:

- `--enable-brute-force-protection` / `--disable-brute-force-protection`: Enable or disable protection
- `--auth-max-failed-attempts <int>`: Maximum failed attempts before blocking (default: 5)
- `--auth-brute-force-ttl <seconds>`: Time window for counting attempts (default: 900)
- `--auth-brute-force-initial-block <seconds>`: Initial block duration (default: 30)
- `--auth-brute-force-multiplier <float>`: Block duration multiplier (default: 2.0)
- `--auth-brute-force-max-block <seconds>`: Maximum block duration (default: 3600)

### Environment Variables

```bash
# Enable/disable protection
export BRUTE_FORCE_PROTECTION_ENABLED=true

# Configure thresholds
export BRUTE_FORCE_MAX_FAILED_ATTEMPTS=10
export BRUTE_FORCE_TTL_SECONDS=1800
export BRUTE_FORCE_INITIAL_BLOCK_SECONDS=60
export BRUTE_FORCE_BLOCK_MULTIPLIER=2.5
export BRUTE_FORCE_MAX_BLOCK_SECONDS=7200
```

### YAML Configuration

```yaml
auth:
  brute_force_protection:
    enabled: true
    max_failed_attempts: 5
    ttl_seconds: 900
    initial_block_seconds: 30
    block_multiplier: 2.0
    max_block_seconds: 3600
```

## Usage Examples

### Standard Production Configuration

Use default settings for most production deployments:

```bash
# Default settings are secure for most use cases
python -m src.core.cli --default-backend openai
```

### Stricter Protection

For high-security environments, reduce the allowed attempts:

```bash
python -m src.core.cli \
  --auth-max-failed-attempts 3 \
  --auth-brute-force-initial-block 60 \
  --auth-brute-force-max-block 7200
```

Or via YAML:

```yaml
auth:
  brute_force_protection:
    enabled: true
    max_failed_attempts: 3
    ttl_seconds: 900
    initial_block_seconds: 60
    block_multiplier: 2.0
    max_block_seconds: 7200
```

### More Lenient Protection

For development or internal networks with trusted users:

```bash
python -m src.core.cli \
  --auth-max-failed-attempts 10 \
  --auth-brute-force-ttl 3600 \
  --auth-brute-force-initial-block 15
```

### Disable Protection

For local development only (not recommended for production):

```bash
python -m src.core.cli --disable-brute-force-protection
```

Or via environment variable:

```bash
export BRUTE_FORCE_PROTECTION_ENABLED=false
python -m src.core.cli
```

## Use Cases

### Preventing API Key Guessing

Protect against attackers trying to guess your proxy API key:

```yaml
auth:
  brute_force_protection:
    enabled: true
    max_failed_attempts: 5
    ttl_seconds: 900
    initial_block_seconds: 30
    block_multiplier: 2.0
    max_block_seconds: 3600
```

After 5 failed attempts within 15 minutes, the attacker's IP is blocked for 30 seconds, then 60 seconds, then 120 seconds, etc.

### High-Security Environments

For sensitive deployments, use stricter limits:

```yaml
auth:
  brute_force_protection:
    enabled: true
    max_failed_attempts: 3
    ttl_seconds: 600
    initial_block_seconds: 120
    block_multiplier: 3.0
    max_block_seconds: 14400
```

This allows only 3 attempts in 10 minutes, with longer block durations.

### Internal Network Deployment

For internal networks with trusted users, use more lenient settings:

```yaml
auth:
  brute_force_protection:
    enabled: true
    max_failed_attempts: 10
    ttl_seconds: 1800
    initial_block_seconds: 15
    block_multiplier: 1.5
    max_block_seconds: 1800
```

### Development and Testing

Disable protection for local development:

```bash
export BRUTE_FORCE_PROTECTION_ENABLED=false
python -m src.core.cli
```

**Warning**: Never disable brute-force protection in production or when the proxy is exposed to the internet.

## Bypass Lists

### Trusted IPs

Certain IP addresses are automatically trusted and bypass brute-force checks:

- Localhost (`127.0.0.1`, `::1`)
- Internal network ranges (configurable)

### Public Endpoints

The following endpoints bypass brute-force protection:

- `/docs` - API documentation
- `/openapi.json` - OpenAPI specification
- `/redoc` - ReDoc documentation
- Health check endpoints

These endpoints are public and don't require authentication, so they don't count toward failed attempt limits.

## Troubleshooting

### 429 Too Many Requests Error

**Problem**: Client receives `429 Too Many Requests` response.

**Cause**: The client IP has exceeded the maximum failed authentication attempts.

**Response Headers**:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 60
Content-Type: application/json

{
  "error": {
    "message": "Too many failed authentication attempts. Please try again later.",
    "type": "rate_limit_exceeded",
    "retry_after": 60
  }
}
```

**Solutions**:

1. **Wait**: Wait for the duration specified in the `Retry-After` header (in seconds)
2. **Check Key**: Verify you're using the correct proxy API key
3. **Review Logs**: Check proxy logs for details about the blocked IP
4. **Adjust Settings**: If legitimate users are being blocked, increase `max_failed_attempts`

### Legitimate Users Being Blocked

**Problem**: Valid users are being blocked due to typos or configuration errors.

**Solutions**:

1. **Increase Attempts**: Raise the `max_failed_attempts` threshold:
   ```bash
   python -m src.core.cli --auth-max-failed-attempts 10
   ```

2. **Increase TTL**: Extend the time window for counting attempts:
   ```bash
   python -m src.core.cli --auth-brute-force-ttl 1800
   ```

3. **Reduce Initial Block**: Lower the initial block duration:
   ```bash
   python -m src.core.cli --auth-brute-force-initial-block 15
   ```

### Shared IP Addresses

**Problem**: Multiple users behind a NAT or proxy share the same IP, causing false positives.

**Solutions**:

1. **Increase Limits**: Raise thresholds to accommodate multiple users:
   ```yaml
   auth:
     brute_force_protection:
       max_failed_attempts: 20
       ttl_seconds: 1800
   ```

2. **Use Trusted IPs**: Configure the shared IP as trusted (if it's an internal network)

3. **Disable Protection**: As a last resort, disable brute-force protection (not recommended)

### Monitoring Blocked Attempts

**Problem**: Need to monitor and analyze blocked authentication attempts.

**Solution**: Review proxy logs for brute-force protection events:

```bash
# Search for blocked attempts in logs
grep "Too many failed authentication attempts" logs/proxy.log

# Count blocked IPs
grep "Blocked IP" logs/proxy.log | awk '{print $NF}' | sort | uniq -c
```

## Security Best Practices

1. **Keep Enabled**: Always enable brute-force protection in production environments

2. **Monitor Logs**: Regularly review logs for blocked IPs and patterns of attack

3. **Adjust Thresholds**: Tune settings based on your environment and user behavior

4. **Combine with Rate Limiting**: Use brute-force protection alongside other rate limiting mechanisms

5. **Use Strong Keys**: Brute-force protection is most effective when combined with strong, random API keys

6. **Alert on Blocks**: Set up monitoring alerts for repeated brute-force blocks, which may indicate an attack

7. **Review Bypass Lists**: Periodically review trusted IPs and ensure they're still appropriate

8. **Test Configuration**: Test your brute-force protection settings in a staging environment before deploying to production

## Related Features

- [Authentication](authentication.md) - API key authentication configuration
- [Key Hygiene](key-hygiene.md) - API key redaction in logs and wire captures
