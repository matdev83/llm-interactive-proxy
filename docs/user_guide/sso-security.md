# SSO Security Considerations

This document explains the security features of the SSO authentication system and provides best practices for secure deployment.

## Security Architecture

### Defense in Depth

The SSO authentication system implements multiple layers of security:

1. **Authentication Layer**: SSO via trusted identity providers
2. **Authorization Layer**: Confirmation codes or external API
3. **Token Layer**: Secure token generation and storage
4. **Session Layer**: Sandbox isolation and session management
5. **Rate Limiting Layer**: Brute-force protection

### Threat Model

The system is designed to protect against:

- **Unauthorized access**: Unauthenticated users cannot access the proxy
- **Token theft**: Stolen tokens are hashed and cannot be reversed
- **Brute-force attacks**: Rate limiting and exponential backoff
- **Session hijacking**: Sandbox isolation prevents session continuation
- **Timing attacks**: Constant-time comparison for token verification
- **Replay attacks**: Time-limited confirmation codes and SSO sessions

## Token Storage Security

### Argon2id Hashing

Agent tokens are hashed using Argon2id, the winner of the Password Hashing Competition and recommended by OWASP.

**Algorithm**: Argon2id (hybrid of Argon2i and Argon2d)

**Parameters** (2025 recommendations):
- **Memory**: 64 MB minimum (65536 KB)
- **Iterations**: 3 minimum
- **Parallelism**: 4 threads minimum
- **Salt**: 16 bytes, cryptographically random
- **Output**: 32 bytes

**Why Argon2id?**
- **Memory-hard**: Resistant to GPU/ASIC attacks
- **Side-channel resistant**: Argon2i component protects against timing attacks
- **Brute-force resistant**: Argon2d component maximizes resistance
- **Configurable**: Parameters can be tuned for security/performance balance

**Example Hash**:
```
$argon2id$v=19$m=65536,t=3,p=4$random_salt$hash_output
```

### No Plaintext Storage

**What is stored**:
- Token hash (Argon2id output)
- User identity (email, user ID)
- Metadata (timestamps, provider, status)

**What is NOT stored**:
- Plaintext tokens
- SSO credentials
- Identity provider secrets

**Database Record**:
```sql
CREATE TABLE agent_tokens (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,  -- Argon2id hash, not plaintext
    user_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    provider TEXT NOT NULL,
    is_authenticated INTEGER NOT NULL,
    is_active INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_authenticated_at TEXT,
    auth_expires_at TEXT
);
```

### Constant-Time Comparison

Token verification uses constant-time comparison to prevent timing attacks:

```python
import hmac

def verify_token(provided_token: str, stored_hash: str) -> bool:
    # Compute hash of provided token
    provided_hash = hash_token(provided_token)
    
    # Constant-time comparison (prevents timing attacks)
    return hmac.compare_digest(provided_hash, stored_hash)
```

**Why constant-time?**
- Prevents attackers from learning information about the hash through timing
- Standard string comparison (`==`) leaks information via execution time
- `hmac.compare_digest` always takes the same time regardless of input

### Database Security

**File Permissions**:
```bash
# Database file is created with restrictive permissions
chmod 600 /path/to/sso_auth.db

# Only owner can read/write
ls -l /path/to/sso_auth.db
-rw------- 1 user user 12345 Jan 15 10:30 sso_auth.db
```

**Encryption at Rest** (optional):
```bash
# Use encrypted filesystem or database encryption
# Example: LUKS, dm-crypt, or SQLCipher
```

**Backup Security**:
- Encrypt database backups
- Store backups in secure locations
- Restrict access to backup files
- Regularly test backup restoration

## Sandbox Isolation

### What is Sandbox Mode?

Sandbox mode is a restricted state where unauthenticated users receive only a login banner instead of accessing the proxy.

**Purpose**:
- Prevent information leakage to unauthenticated users
- Ensure authentication state doesn't leak into conversations
- Force explicit authentication before access

### How Sandbox Isolation Works

```
1. Unauthenticated request arrives
   |
   v
2. Proxy detects no valid token
   |
   v
3. Proxy returns sandbox response (login banner)
   |
   v
4. User authenticates and receives token
   |
   v
5. User configures agent with token
   |
   v
6. New request with token is authenticated
   |
   v
7. Proxy routes to backend (normal operation)
```

### Sandbox History Detection

The proxy detects and rejects requests containing sandbox content in conversation history:

```python
def detect_sandbox_history(messages: list[dict]) -> bool:
    """Check if conversation history contains sandbox login banner."""
    for message in messages:
        content = message.get("content", "")
        if "authentication required" in content.lower():
            return True
        if "http://localhost:8080/auth/login" in content:
            return True
    return False
```

**Why?**
- Prevents authentication state from leaking into unauthenticated sessions
- Ensures users start fresh after authentication
- Prevents session continuation attacks

### Session Isolation Properties

1. **No state carryover**: Sandbox sessions cannot continue after authentication
2. **History rejection**: Requests with sandbox content are rejected
3. **Fresh start**: Users must configure agent with token for new session
4. **No information leakage**: Sandbox responses contain no sensitive information

## Rate Limiting and Brute-Force Protection

### Confirmation Code Protection (Single-User Mode)

**Attempt Limits**:
- Maximum 3 attempts per authorization session
- After 3 failures, must re-authenticate via SSO

**Exponential Backoff**:
```
Attempt 1: No delay
Attempt 2: 2 second delay
Attempt 3: 4 second delay
After 3 failures: Must re-authenticate (exponential backoff on SSO attempts)
```

**Per-IP Rate Limiting**:
- Track failed attempts by IP address
- Exponential backoff increases with each failure
- Prevents distributed brute-force attacks

**Code Expiry**:
- Confirmation codes expire after 10 minutes (configurable)
- Expired codes require re-authentication
- Prevents replay attacks

### SSO Rate Limiting

After exhausting confirmation code attempts:

```
1st SSO failure: 2 second wait
2nd SSO failure: 4 second wait
3rd SSO failure: 8 second wait
4th SSO failure: 16 second wait
...
Max wait: 300 seconds (5 minutes)
```

**Implementation**:
```python
def calculate_backoff(attempts: int) -> int:
    """Calculate exponential backoff in seconds."""
    base_delay = 2
    max_delay = 300
    delay = base_delay * (2 ** attempts)
    return min(delay, max_delay)
```

### Authorization API Rate Limiting (Enterprise Mode)

**Timeout Protection**:
- Default timeout: 5 seconds
- Prevents hanging on slow/unresponsive APIs
- Fails closed (denies access on timeout)

**Retry Logic**:
- No automatic retries (fail fast)
- User must re-authenticate if API fails
- Prevents amplification attacks

## SSO Session Security

### Session Lifetime

**Default**: 24 hours (configurable)

**Rationale**:
- Balance between security and convenience
- Shorter than typical password sessions
- Long enough to avoid frequent re-authentication

**Configuration**:
```yaml
authorization:
  session_lifetime_hours: 24  # Adjust based on security requirements
```

### Session Expiry Handling

When a session expires:

1. **Detection**: Proxy checks `auth_expires_at` timestamp
2. **Response**: Returns sandbox with re-authentication URL
3. **User action**: User re-authenticates via SSO
4. **Restoration**: Session is restored with same token
5. **No reconfiguration**: Agent continues with same token

### Session Revocation

**Immediate revocation**:
```sql
UPDATE agent_tokens
SET is_authenticated = 0, auth_expires_at = NULL
WHERE token_hash = ?;
```

**Soft delete** (for audit):
```sql
UPDATE agent_tokens
SET is_active = 0
WHERE token_hash = ?;
```

## Identity Provider Security

### OAuth2/OIDC Security

**State Parameter**:
- Cryptographically random state parameter
- Prevents CSRF attacks
- Validated on callback

**PKCE** (Proof Key for Code Exchange):
- Recommended for public clients
- Prevents authorization code interception
- Supported by most modern IdPs

**Redirect URI Validation**:
- Exact match required by IdPs
- No wildcards or partial matches
- Prevents open redirect attacks

### Client Secret Protection

**Storage**:
- Never commit to version control
- Use environment variables or secret managers
- Restrict access to secrets

**Rotation**:
- Rotate secrets periodically (e.g., every 90 days)
- Update configuration after rotation
- Revoke old secrets after transition period

**Example** (using environment variables):
```yaml
providers:
  google:
    client_secret: "${GOOGLE_CLIENT_SECRET}"
```

```bash
export GOOGLE_CLIENT_SECRET=GOCSPX-actual-secret
```

### Scope Minimization

**Principle of least privilege**:
- Request only necessary scopes
- Review scopes regularly
- Remove unused scopes

**Example**:
```yaml
# GOOD - minimal scopes
scopes: ["openid", "email"]

# BAD - excessive scopes
scopes: ["openid", "email", "profile", "calendar", "drive", "contacts"]
```

## Network Security

### HTTPS in Production

**Always use HTTPS for production deployments**:

```yaml
# GOOD - HTTPS
server:
  host: "0.0.0.0"
  port: 443
  tls:
    cert: "/path/to/cert.pem"
    key: "/path/to/key.pem"

# BAD - HTTP in production
server:
  host: "0.0.0.0"
  port: 80
```

**Why HTTPS?**
- Encrypts token transmission
- Prevents man-in-the-middle attacks
- Required by most IdPs for production
- Industry best practice

### Firewall Configuration

**Restrict access to proxy**:

```bash
# Allow only specific IPs
iptables -A INPUT -p tcp --dport 8080 -s 192.168.1.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8080 -j DROP

# Or use firewall-cmd
firewall-cmd --add-rich-rule='rule family="ipv4" source address="192.168.1.0/24" port port="8080" protocol="tcp" accept'
```

**VPN Access**:
- Require VPN for remote access
- Use corporate VPN or WireGuard
- Restrict proxy to VPN subnet

### Reverse Proxy

**Use reverse proxy for additional security**:

```nginx
# Nginx configuration
server {
    listen 443 ssl;
    server_name proxy.company.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Audit and Monitoring

### Logging

**What to log**:
- Authentication attempts (success/failure)
- Authorization decisions (granted/denied)
- Token generation and revocation
- SSO session expiry and renewal
- Rate limit violations
- Configuration changes

**Example log entries**:
```
2025-01-15 10:30:45 INFO SSO authentication successful: user=alice@example.com provider=google
2025-01-15 10:30:46 INFO Authorization granted: user=alice@example.com mode=single_user
2025-01-15 10:30:47 INFO Token generated: user=alice@example.com token_id=abc123
2025-01-15 14:30:00 WARNING Rate limit exceeded: ip=192.168.1.100 attempts=5
2025-01-15 18:00:00 INFO Session expired: user=alice@example.com token_id=abc123
```

### Log Security

**Protect log files**:
```bash
# Restrictive permissions
chmod 600 /var/log/llm-proxy/auth.log

# Rotate logs regularly
logrotate -f /etc/logrotate.d/llm-proxy
```

**What NOT to log**:
- Plaintext tokens
- Client secrets
- Confirmation codes (except in single-user mode)
- Full request/response bodies (may contain sensitive data)

### Monitoring and Alerting

**Monitor for**:
- Unusual authentication patterns
- High rate of failed attempts
- Authorization API failures
- Token generation spikes
- Session expiry anomalies

**Alert on**:
- Repeated authentication failures from same IP
- Authorization API downtime
- Database errors
- Configuration changes
- Suspicious access patterns

## Compliance Considerations

### GDPR

**Data minimization**:
- Store only necessary user data
- Don't store unnecessary IdP information
- Implement data retention policies

**Right to erasure**:
- Support token revocation
- Implement user data deletion
- Maintain audit trail of deletions

**Data portability**:
- Allow users to export their data
- Provide token usage history
- Support data format standards

### SOC 2

**Access controls**:
- Implement role-based access control
- Audit access to sensitive data
- Restrict administrative access

**Logging and monitoring**:
- Comprehensive audit logs
- Real-time monitoring and alerting
- Log retention and archival

**Incident response**:
- Document security incidents
- Implement incident response procedures
- Regular security reviews

### HIPAA (if applicable)

**Encryption**:
- Encrypt data at rest and in transit
- Use FIPS 140-2 compliant algorithms
- Implement key management

**Access controls**:
- Unique user identification
- Automatic logoff after inactivity
- Audit controls

## Security Best Practices

### Deployment

1. **Use HTTPS**: Always use HTTPS in production
2. **Restrict access**: Use firewall rules and VPN
3. **Rotate secrets**: Regularly rotate client secrets and tokens
4. **Monitor logs**: Implement comprehensive logging and monitoring
5. **Update regularly**: Keep proxy and dependencies updated
6. **Backup securely**: Encrypt and secure database backups

### Configuration

1. **Minimize scopes**: Request only necessary OAuth2 scopes
2. **Strong sessions**: Use appropriate session lifetime (24-48 hours)
3. **Rate limiting**: Enable rate limiting and exponential backoff
4. **Secure storage**: Use environment variables or secret managers
5. **Validate input**: Validate all configuration inputs

### Operations

1. **Regular audits**: Review access logs and authorization decisions
2. **Incident response**: Have a plan for security incidents
3. **User training**: Educate users on token security
4. **Access review**: Regularly review who has access
5. **Penetration testing**: Conduct regular security assessments

## Security Checklist

### Pre-Deployment

- [ ] HTTPS configured with valid certificate
- [ ] Firewall rules configured
- [ ] Client secrets stored securely (not in version control)
- [ ] Database file permissions set to 600
- [ ] Logging configured and tested
- [ ] Monitoring and alerting set up
- [ ] Backup strategy implemented
- [ ] Incident response plan documented

### Post-Deployment

- [ ] Regular log reviews scheduled
- [ ] Secret rotation schedule established
- [ ] User access reviewed quarterly
- [ ] Security updates applied promptly
- [ ] Backup restoration tested
- [ ] Penetration testing scheduled
- [ ] Compliance requirements met
- [ ] Documentation kept up to date

## Incident Response

### Token Compromise

If a token is compromised:

1. **Immediate action**: Revoke the token
2. **Investigation**: Review logs for unauthorized access
3. **Notification**: Notify affected users
4. **Remediation**: Generate new token for user
5. **Review**: Analyze how compromise occurred
6. **Prevention**: Implement additional controls

### Authorization API Breach

If authorization API is compromised:

1. **Immediate action**: Disable enterprise mode or switch to single-user
2. **Investigation**: Assess scope of breach
3. **Notification**: Notify all users
4. **Remediation**: Secure API and rotate credentials
5. **Review**: Conduct security audit
6. **Prevention**: Implement additional API security

### Database Breach

If database is compromised:

1. **Immediate action**: Revoke all tokens
2. **Investigation**: Determine what data was accessed
3. **Notification**: Notify all users and authorities (if required)
4. **Remediation**: Secure database and restore from backup
5. **Review**: Conduct comprehensive security review
6. **Prevention**: Implement encryption at rest and additional controls

## Next Steps

- **[Troubleshooting](./sso_troubleshooting.md)** - Common issues and solutions
- **[Configuration Options](./sso_configuration.md)** - Complete configuration reference
- **[Agent Configuration](./sso_agent_setup.md)** - Configure AI agents with tokens
