# SSO Authorization Configuration

After a user successfully authenticates via SSO (Single Sign-On), the LLM Proxy performs an authorization check to determine if the user should be granted access. This document explains the two authorization modes and how to configure them.

## Authorization Modes

### Single-User Mode

Best for personal use or small teams where the server administrator controls access.

**How it works:**
1. User completes SSO authentication
2. Proxy generates a 6-digit confirmation code
3. Code is logged to the server console (WARNING level)
4. User enters the code in the web interface
5. Upon correct code entry, proxy generates and displays the agent token

**Use when:**
- Running the proxy locally for personal use
- Small team with trusted users
- No external authorization infrastructure
- Simple access control is sufficient

### Enterprise Mode

Best for organizations with existing authorization systems or complex access control requirements.

**How it works:**
1. User completes SSO authentication
2. Proxy queries an external authorization API
3. API receives user identity and IP address
4. API returns true/false to grant/deny access
5. If approved, proxy generates and displays the agent token

**Use when:**
- Need centralized access control
- Integration with existing authorization systems
- Complex authorization rules (roles, groups, IP restrictions)
- Audit and compliance requirements
- Multiple proxy instances with shared authorization

## Single-User Mode Configuration

### Basic Configuration

```yaml
sso:
  enabled: true
  authorization:
    mode: "single_user"
    session_lifetime_hours: 24
    confirmation_code_expiry_minutes: 10
    max_confirmation_attempts: 3
  providers:
    google:
      # ... provider config ...
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mode` | string | - | Must be "single_user" |
| `session_lifetime_hours` | integer | 24 | SSO session lifetime in hours |
| `confirmation_code_expiry_minutes` | integer | 10 | How long confirmation code is valid |
| `max_confirmation_attempts` | integer | 3 | Maximum attempts before re-authentication required |

### Authentication Flow

```
1. User authenticates via SSO (Google, Microsoft, etc.)
   |
   v
2. Proxy generates 6-digit confirmation code
   |
   v
3. Proxy logs code to server console:
   WARNING: SSO Authorization Required
   User: user@example.com
   Confirmation Code: 123456
   |
   v
4. User sees web page: "Check server console for confirmation code"
   |
   v
5. User enters code in web form
   |
   v
6. If correct: Display agent token
   If incorrect: Decrement attempts, show remaining attempts
   If exhausted: Require re-authentication
```

### Server Console Interaction

When a user completes SSO authentication, you'll see output like this in the server console:

```
2025-01-15 10:30:45 WARNING SSO Authorization Required
2025-01-15 10:30:45 WARNING User: alice@example.com
2025-01-15 10:30:45 WARNING Provider: google
2025-01-15 10:30:45 WARNING Confirmation Code: 847293
2025-01-15 10:30:45 WARNING Code expires in 10 minutes
```

**Important**: The confirmation code is only displayed in the server console. The user must have access to the console to complete authorization.

### Security Features

#### Rate Limiting

Failed confirmation code attempts trigger exponential backoff:

- **1st failure**: No delay
- **2nd failure**: 2 second delay
- **3rd failure**: 4 second delay
- **After 3 failures**: Must re-authenticate via SSO

#### Brute-Force Protection

- Maximum 3 attempts per authorization session
- Exponential backoff between SSO attempts after failures
- Per-IP rate limiting to prevent distributed attacks

#### Code Expiry

- Confirmation codes expire after 10 minutes (configurable)
- Expired codes require re-authentication
- Prevents replay attacks

### Troubleshooting Single-User Mode

#### Code Not Appearing in Console

**Symptom**: No confirmation code logged after SSO authentication

**Solutions**:
- Check log level is set to WARNING or lower (INFO, DEBUG)
- Verify SSO authentication completed successfully
- Check server logs for errors during authorization
- Ensure authorization mode is set to "single_user"

#### Code Expired

**Symptom**: "Confirmation code expired" error

**Solutions**:
- Re-authenticate via SSO to generate a new code
- Increase `confirmation_code_expiry_minutes` if needed
- Ensure server and client clocks are synchronized

#### Too Many Failed Attempts

**Symptom**: "Maximum attempts exceeded" error

**Solutions**:
- Re-authenticate via SSO to get a new code
- Verify you're entering the code correctly (no spaces, correct digits)
- Check for typos in the code
- Ensure code hasn't expired

#### Rate Limited

**Symptom**: "Please wait before trying again" message

**Solutions**:
- Wait for the specified time period
- Exponential backoff increases with each failure
- After waiting, re-authenticate via SSO

## Enterprise Mode Configuration

### Basic Configuration

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
      # ... provider config ...
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `mode` | string | - | Must be "enterprise" |
| `api_url` | string | - | Authorization API endpoint URL |
| `api_timeout_seconds` | integer | 5 | Request timeout in seconds |
| `session_lifetime_hours` | integer | 24 | SSO session lifetime in hours |

### Authentication Flow

```
1. User authenticates via SSO
   |
   v
2. Proxy sends POST request to authorization API:
   {
     "user_id": "alice@example.com",
     "user_email": "alice@example.com",
     "provider": "microsoft",
     "client_ip": "192.168.1.100"
   }
   |
   v
3. Authorization API processes request:
   - Check user roles/groups
   - Verify IP allowlist
   - Check time-based restrictions
   - Query internal systems
   |
   v
4. API returns response:
   {"authorized": true}  or  {"authorized": false}
   |
   v
5. If authorized: Display agent token
   If denied: Display "Access Denied" message
   If error: Display error and deny access
```

### Authorization API Specification

#### Request Format

**Method**: POST

**URL**: Configured in `api_url`

**Headers**:
```
Content-Type: application/json
User-Agent: LLM-Proxy/1.0
```

**Body**:
```json
{
  "user_id": "alice@example.com",
  "user_email": "alice@example.com",
  "provider": "microsoft",
  "client_ip": "192.168.1.100",
  "timestamp": "2025-01-15T10:30:45Z"
}
```

**Fields**:
- `user_id`: User identifier from IdP (usually email)
- `user_email`: User email address from IdP
- `provider`: Identity provider name (google, microsoft, github, linkedin, aws)
- `client_ip`: Client IP address making the request
- `timestamp`: ISO 8601 timestamp of the authorization request

#### Response Format

**Success (Authorized)**:
```json
{
  "authorized": true
}
```

**Success (Denied)**:
```json
{
  "authorized": false,
  "reason": "User not in allowed group"
}
```

**Error**:
```json
{
  "error": "Internal server error",
  "details": "Database connection failed"
}
```

**HTTP Status Codes**:
- `200 OK`: Authorization decision made (check `authorized` field)
- `400 Bad Request`: Invalid request format
- `401 Unauthorized`: API authentication failed
- `500 Internal Server Error`: API error (access denied by default)
- `503 Service Unavailable`: API unavailable (access denied by default)

### Example Authorization API Implementations

#### Example 1: Simple Flask API

See `examples/sso_authorization_api.py` for a complete Flask implementation:

```python
from flask import Flask, request, jsonify

app = Flask(__name__)

# Allowed users (in production, use database or LDAP)
ALLOWED_USERS = {
    "alice@example.com",
    "bob@example.com"
}

@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.json
    
    user_email = data.get("user_email")
    client_ip = data.get("client_ip")
    
    # Check if user is allowed
    if user_email in ALLOWED_USERS:
        return jsonify({"authorized": True})
    else:
        return jsonify({
            "authorized": False,
            "reason": "User not in allowed list"
        })

if __name__ == "__main__":
    app.run(port=5000)
```

#### Example 2: Role-Based Authorization

```python
from flask import Flask, request, jsonify
import ldap

app = Flask(__name__)

REQUIRED_GROUP = "cn=llm-proxy-users,ou=groups,dc=company,dc=com"

@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.json
    user_email = data.get("user_email")
    
    # Query LDAP for user groups
    try:
        conn = ldap.initialize("ldap://ldap.company.com")
        conn.simple_bind_s("cn=admin,dc=company,dc=com", "password")
        
        result = conn.search_s(
            "ou=users,dc=company,dc=com",
            ldap.SCOPE_SUBTREE,
            f"(mail={user_email})",
            ["memberOf"]
        )
        
        if result:
            groups = result[0][1].get("memberOf", [])
            if REQUIRED_GROUP.encode() in groups:
                return jsonify({"authorized": True})
        
        return jsonify({
            "authorized": False,
            "reason": "User not in required group"
        })
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

#### Example 3: IP Allowlist

```python
from flask import Flask, request, jsonify
import ipaddress

app = Flask(__name__)

ALLOWED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("192.168.0.0/16")
]

@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.json
    client_ip = ipaddress.ip_address(data.get("client_ip"))
    
    # Check if IP is in allowed networks
    for network in ALLOWED_NETWORKS:
        if client_ip in network:
            return jsonify({"authorized": True})
    
    return jsonify({
        "authorized": False,
        "reason": "IP address not in allowed networks"
    })
```

#### Example 4: Time-Based Restrictions

```python
from flask import Flask, request, jsonify
from datetime import datetime, time

app = Flask(__name__)

ALLOWED_HOURS = (time(9, 0), time(17, 0))  # 9 AM to 5 PM

@app.route("/api/authorize", methods=["POST"])
def authorize():
    data = request.json
    user_email = data.get("user_email")
    
    # Check time restrictions
    now = datetime.now().time()
    if ALLOWED_HOURS[0] <= now <= ALLOWED_HOURS[1]:
        return jsonify({"authorized": True})
    else:
        return jsonify({
            "authorized": False,
            "reason": "Access only allowed during business hours"
        })
```

### Security Considerations

#### API Authentication

Protect your authorization API with authentication:

```python
from flask import Flask, request, jsonify
import hmac
import hashlib

app = Flask(__name__)
API_SECRET = "your-secret-key"

@app.route("/api/authorize", methods=["POST"])
def authorize():
    # Verify HMAC signature
    signature = request.headers.get("X-Signature")
    body = request.get_data()
    expected = hmac.new(
        API_SECRET.encode(),
        body,
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected):
        return jsonify({"error": "Invalid signature"}), 401
    
    # Process authorization...
```

Configure proxy to send signature:
```yaml
authorization:
  api_url: "https://company.com/api/authorize"
  api_secret: "your-secret-key"
```

#### HTTPS Only

Always use HTTPS for authorization API in production:

```yaml
# GOOD
authorization:
  api_url: "https://company.com/api/authorize"

# BAD - never use HTTP in production
authorization:
  api_url: "http://company.com/api/authorize"
```

#### Timeout Handling

Set appropriate timeouts to prevent hanging:

```yaml
authorization:
  api_timeout_seconds: 5  # Fail fast if API is slow
```

#### Error Handling

Always deny access on errors (fail closed):

```python
@app.route("/api/authorize", methods=["POST"])
def authorize():
    try:
        # Authorization logic...
        return jsonify({"authorized": True})
    except Exception as e:
        # Log error but deny access
        app.logger.error(f"Authorization error: {e}")
        return jsonify({
            "authorized": False,
            "reason": "Internal error"
        }), 500
```

### Troubleshooting Enterprise Mode

#### API Not Responding

**Symptom**: "Authorization API timeout" error

**Solutions**:
- Verify API URL is correct and accessible
- Check API is running and responding
- Increase `api_timeout_seconds` if API is slow
- Check network connectivity between proxy and API
- Review API logs for errors

#### API Returning Errors

**Symptom**: "Authorization API error" in logs

**Solutions**:
- Check API logs for detailed error messages
- Verify request format matches API expectations
- Ensure API has access to required resources (database, LDAP, etc.)
- Test API independently with curl or Postman

#### Always Denied

**Symptom**: All users denied access

**Solutions**:
- Check API authorization logic
- Verify user identifiers match (email format, case sensitivity)
- Review API logs to see why users are denied
- Test API with known-good user credentials

#### API Authentication Failed

**Symptom**: "401 Unauthorized" from API

**Solutions**:
- Verify API authentication credentials are configured
- Check API secret/key is correct
- Ensure authentication headers are being sent
- Review API authentication requirements

## Switching Between Modes

You can switch between single-user and enterprise modes by updating the configuration:

```yaml
# Switch to single-user mode
authorization:
  mode: "single_user"

# Switch to enterprise mode
authorization:
  mode: "enterprise"
  api_url: "https://company.com/api/authorize"
```

**Note**: Existing agent tokens remain valid when switching modes. Only new authorizations use the new mode.

## Best Practices

### Single-User Mode

1. **Secure console access**: Only authorized users should have access to server console
2. **Use strong codes**: Default 6-digit codes provide adequate security
3. **Monitor logs**: Review authorization logs for suspicious activity
4. **Set appropriate expiry**: Balance security and convenience (default 10 minutes)

### Enterprise Mode

1. **Implement proper authentication**: Protect your authorization API
2. **Use HTTPS**: Always use HTTPS for API communication
3. **Log authorization decisions**: Maintain audit trail of access grants/denials
4. **Implement rate limiting**: Prevent abuse of authorization API
5. **Fail closed**: Deny access on errors or timeouts
6. **Monitor API health**: Alert on API failures or slow responses
7. **Test thoroughly**: Verify authorization logic with various scenarios

## Next Steps

- **[Agent Configuration](./sso_agent_setup.md)** - Configure AI agents with tokens
- **[Security Considerations](./sso_security.md)** - Understand security features
- **[Troubleshooting](./sso_troubleshooting.md)** - Common issues and solutions
- **[Example Authorization API](../examples/sso_authorization_api.py)** - Complete Flask implementation
