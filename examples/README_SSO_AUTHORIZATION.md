# SSO Authorization API Example

This directory contains an example authorization API for testing the SSO authentication enterprise mode.

## Overview

The authorization API is called after successful SSO authentication to determine if a user should be granted access to the proxy. This allows organizations to implement custom authorization logic based on:

- User identity (email, ID)
- Client IP address
- Group membership
- License seats
- Time-based policies
- Any other business logic

## Quick Start

### 1. Install Dependencies

```bash
pip install fastapi uvicorn
```

### 2. Run the Example API

```bash
python examples/sso_authorization_api.py
```

The API will start on `http://localhost:8001`

### 3. Configure the Proxy

Start the proxy with the authorization API URL:

```bash
python -m src.anthropic_server \
    --sso-enabled \
    --sso-provider google \
    --sso-auth-mode enterprise \
    --sso-authorization-api-url http://localhost:8001/authorize
```

## API Specification

### Authorization Endpoint

**POST** `/authorize`

**Request Body:**
```json
{
    "user_id": "user@example.com",
    "user_email": "user@example.com",
    "client_ip": "192.168.1.100"
}
```

**Response:**
```json
{
    "authorized": true
}
```

or

```json
{
    "authorized": false
}
```

**Status Codes:**
- `200 OK`: Authorization decision made (check `authorized` field)
- `400 Bad Request`: Invalid request payload
- `500 Internal Server Error`: Server error

## Customization

The example API (`sso_authorization_api.py`) includes two simple authorization checks:

1. **User Whitelist**: Checks if the user's email is in `AUTHORIZED_USERS`
2. **IP Whitelist**: Checks if the client IP starts with an authorized prefix

### Adding Users

Edit the `AUTHORIZED_USERS` set in `sso_authorization_api.py`:

```python
AUTHORIZED_USERS = {
    "admin@example.com",
    "user@example.com",
    "developer@example.com",
    "your-email@example.com",  # Add your email here
}
```

### Adding IP Ranges

Edit the `AUTHORIZED_IP_PREFIXES` list:

```python
AUTHORIZED_IP_PREFIXES = [
    "127.0.",      # Localhost
    "192.168.",    # Private network
    "10.",         # Private network
    "203.0.113.",  # Your office network
]
```

## Production Implementation

For production use, you should implement proper authorization logic:

### Database Integration

```python
import asyncpg

async def authorize(request: AuthorizationRequest) -> AuthorizationResponse:
    # Query your user database
    async with asyncpg.create_pool(DATABASE_URL) as pool:
        user = await pool.fetchrow(
            "SELECT * FROM users WHERE email = $1 AND is_active = true",
            request.user_email
        )
        
        if not user:
            return AuthorizationResponse(authorized=False)
        
        # Check user permissions, roles, etc.
        return AuthorizationResponse(authorized=True)
```

### Active Directory / LDAP Integration

```python
from ldap3 import Server, Connection

def check_ad_group(user_email: str, required_group: str) -> bool:
    server = Server('ldap://your-ad-server.com')
    conn = Connection(server, user='bind_user', password='bind_password')
    conn.bind()
    
    # Search for user and check group membership
    conn.search(
        'dc=example,dc=com',
        f'(mail={user_email})',
        attributes=['memberOf']
    )
    
    if conn.entries:
        groups = conn.entries[0].memberOf.values
        return required_group in groups
    
    return False
```

### License Seat Management

```python
async def authorize(request: AuthorizationRequest) -> AuthorizationResponse:
    # Check if user has an available license seat
    active_sessions = await get_active_session_count()
    max_seats = await get_license_seat_count()
    
    if active_sessions >= max_seats:
        # Check if this user already has an active session
        has_active_session = await user_has_active_session(request.user_id)
        if not has_active_session:
            return AuthorizationResponse(authorized=False)
    
    return AuthorizationResponse(authorized=True)
```

### Time-Based Access

```python
from datetime import datetime, time

async def authorize(request: AuthorizationRequest) -> AuthorizationResponse:
    # Only allow access during business hours
    now = datetime.now().time()
    business_start = time(9, 0)  # 9 AM
    business_end = time(17, 0)   # 5 PM
    
    if not (business_start <= now <= business_end):
        return AuthorizationResponse(authorized=False)
    
    return AuthorizationResponse(authorized=True)
```

## Security Considerations

1. **HTTPS**: In production, always use HTTPS for the authorization API
2. **Authentication**: Consider adding API key authentication between the proxy and authorization API
3. **Rate Limiting**: Implement rate limiting to prevent abuse
4. **Logging**: Log all authorization decisions for audit purposes
5. **Timeouts**: The proxy has a configurable timeout (default 10 seconds)
6. **Error Handling**: Return `authorized: false` on errors (fail closed)

## Testing

You can test the authorization API directly using curl:

```bash
curl -X POST http://localhost:8001/authorize \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user@example.com",
    "user_email": "user@example.com",
    "client_ip": "192.168.1.100"
  }'
```

Expected response:
```json
{"authorized":true}
```

## Troubleshooting

### API Not Responding

- Check that the API is running: `curl http://localhost:8001/health`
- Verify the port is not in use by another application
- Check firewall settings

### Authorization Always Fails

- Check the API logs for authorization decisions
- Verify your email is in `AUTHORIZED_USERS`
- Verify your IP matches one of the `AUTHORIZED_IP_PREFIXES`
- Test the API directly with curl (see Testing section)

### Proxy Can't Connect to API

- Verify the API URL in proxy configuration
- Check that the API is accessible from the proxy server
- Verify network connectivity and firewall rules
- Check proxy logs for connection errors

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [OAuth 2.0 Specification](https://oauth.net/2/)
- [SAML 2.0 Specification](http://docs.oasis-open.org/security/saml/Post2.0/sstc-saml-tech-overview-2.0.html)
