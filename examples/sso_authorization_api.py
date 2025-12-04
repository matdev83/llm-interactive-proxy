#!/usr/bin/env python3
"""
Example Authorization API for SSO Authentication (Enterprise Mode).

This is a simple FastAPI-based authorization API that can be used for testing
the SSO authentication enterprise mode. In production, you would replace this
with your organization's actual authorization logic.

Usage:
    1. Install FastAPI and uvicorn:
       pip install fastapi uvicorn

    2. Run the server:
       python examples/sso_authorization_api.py

    3. Configure the proxy to use this authorization API:
       --sso-authorization-api-url http://localhost:8001/authorize

The API accepts POST requests with the following JSON payload:
    {
        "user_id": "user@example.com",
        "user_email": "user@example.com",
        "client_ip": "192.168.1.100"
    }

And returns:
    {
        "authorized": true/false
    }
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
import uvicorn


app = FastAPI(title="SSO Authorization API Example")


class AuthorizationRequest(BaseModel):
    """Authorization request payload."""

    user_id: str
    user_email: EmailStr
    client_ip: str


class AuthorizationResponse(BaseModel):
    """Authorization response."""

    authorized: bool


# Example: Whitelist of authorized users
# In production, this would query your user database, LDAP, or other auth system
AUTHORIZED_USERS = {
    "admin@example.com",
    "user@example.com",
    "developer@example.com",
}

# Example: Whitelist of authorized IP ranges
# In production, you might check against VPN ranges or office networks
AUTHORIZED_IP_PREFIXES = [
    "127.0.",  # Localhost
    "192.168.",  # Private network
    "10.",  # Private network
]


@app.post("/authorize", response_model=AuthorizationResponse)
async def authorize(request: AuthorizationRequest) -> AuthorizationResponse:
    """
    Authorize a user based on their identity and IP address.

    This is a simple example that checks:
    1. If the user's email is in the authorized users list
    2. If the client IP is from an authorized network

    In production, you would implement your organization's actual
    authorization logic here, such as:
    - Checking group membership in Active Directory
    - Verifying user roles in your database
    - Checking license seats
    - Enforcing time-based access policies
    - Checking IP allowlists/denylists
    - Integrating with your IAM system
    """
    print(f"Authorization request: {request.user_email} from {request.client_ip}")

    # Check if user is in authorized list
    if request.user_email not in AUTHORIZED_USERS:
        print(f"  -> DENIED: User {request.user_email} not in authorized list")
        return AuthorizationResponse(authorized=False)

    # Check if IP is from authorized network
    ip_authorized = any(
        request.client_ip.startswith(prefix) for prefix in AUTHORIZED_IP_PREFIXES
    )

    if not ip_authorized:
        print(f"  -> DENIED: IP {request.client_ip} not from authorized network")
        return AuthorizationResponse(authorized=False)

    print(f"  -> AUTHORIZED: User {request.user_email} from {request.client_ip}")
    return AuthorizationResponse(authorized=True)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


if __name__ == "__main__":
    print("Starting SSO Authorization API Example")
    print("=" * 60)
    print("Authorized users:")
    for user in AUTHORIZED_USERS:
        print(f"  - {user}")
    print()
    print("Authorized IP prefixes:")
    for prefix in AUTHORIZED_IP_PREFIXES:
        print(f"  - {prefix}*")
    print("=" * 60)
    print()
    print("API will be available at: http://localhost:8001")
    print("Authorization endpoint: http://localhost:8001/authorize")
    print()
    print("Configure the proxy with:")
    print("  --sso-authorization-api-url http://localhost:8001/authorize")
    print()

    uvicorn.run(app, host="127.0.0.1", port=8001)
