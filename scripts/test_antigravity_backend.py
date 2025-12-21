"""
Test script for the Antigravity backend.

This script tests the Antigravity backend by:
1. Initializing the connector
2. Checking if credentials are loaded
3. Testing the streamGenerateContent endpoint with the correct Antigravity format
4. Verifying the connector builds the correct request body format
"""

import asyncio
import json
import logging
import sys
import uuid as uuid_mod
from unittest.mock import Mock

import httpx

# Configure logging to see debug output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Reduce noise from httpx/httpcore
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


async def test_antigravity_backend() -> None:
    """Test the Antigravity backend."""
    from src.connectors.antigravity_oauth import (
        ANTIGRAVITY_SANDBOX_ENDPOINT,
        ANTIGRAVITY_USER_AGENT,
        AntigravityOAuthConnector,
    )
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    print("=" * 60)
    print("ANTIGRAVITY BACKEND TEST")
    print("=" * 60)

    # Create connector
    config = AppConfig()
    translation_service = TranslationService()
    client = httpx.AsyncClient()

    connector = AntigravityOAuthConnector(
        client, config, translation_service, name="antigravity-oauth"
    )

    print(f"\n[1] Sandbox endpoint: {ANTIGRAVITY_SANDBOX_ENDPOINT}")
    print(f"[2] User-Agent: {ANTIGRAVITY_USER_AGENT}")

    # Initialize the connector
    print("\n[3] Initializing connector...")
    try:
        await connector.initialize()
        print(f"    - Initialized: {connector.is_functional}")
        print(
            f"    - gemini_api_base_url: {getattr(connector, 'gemini_api_base_url', 'NOT SET')}"
        )
    except Exception as e:
        print(f"    - ERROR: {e}")
        return

    # Check credentials
    print("\n[4] Checking credentials...")
    creds = getattr(connector, "_oauth_credentials", None)
    if creds:
        print(f"    - access_token: {creds.get('access_token', 'N/A')[:50]}...")
        print("    - Has credentials: YES")
    else:
        print("    - Has credentials: NO")
        return

    # Check headers
    print("\n[5] Checking headers...")
    api_headers = connector._get_api_headers()
    session_headers = connector._get_session_headers()
    print(f"    - API headers User-Agent: {api_headers.get('User-Agent', 'NOT SET')}")
    print(f"    - Session headers: {session_headers}")

    # Test the connector's request body building
    print("\n[6] Testing connector's _build_code_assist_request_body method...")
    request_data = Mock()
    request_data.id = None

    code_assist_request = {
        "contents": [{"role": "user", "parts": [{"text": "Test message"}]}],
        "generationConfig": {"temperature": 0.7},
    }

    request_body = connector._build_code_assist_request_body(
        effective_model="gemini-2.5-flash",
        project_id="test-project",
        request_data=request_data,
        code_assist_request=code_assist_request,
    )

    print(f"    - Built request body:\n{json.dumps(request_body, indent=2)}")
    print(f"    - Has 'requestId': {'requestId' in request_body}")
    print(f"    - Has 'userAgent': {'userAgent' in request_body}")
    print(f"    - Has 'requestType': {'requestType' in request_body}")
    print(f"    - Model at top level: {'model' in request_body}")
    print(f"    - No 'user_prompt_id': {'user_prompt_id' not in request_body}")

    # Test actual API call with correct format
    print("\n[7] Testing streamGenerateContent with correct Antigravity format...")
    import google.auth.transport.requests

    class StaticTokenCreds:
        def __init__(self, token: str) -> None:
            self.token = token

        def before_request(self, request, method, url, headers) -> None:
            headers["Authorization"] = f"Bearer {self.token}"

        def refresh(self, request) -> None:
            pass

    access_token = creds.get("access_token")
    auth_session = google.auth.transport.requests.AuthorizedSession(
        StaticTokenCreds(access_token)
    )

    # Apply session headers (including User-Agent)
    session_headers = connector._get_session_headers()
    for key, value in session_headers.items():
        auth_session.headers[key] = value

    url = f"{ANTIGRAVITY_SANDBOX_ENDPOINT}/v1internal:streamGenerateContent"

    # Use the CORRECT Antigravity format
    correct_request = {
        "project": "absolute-depot-xfbhg",
        "requestId": f"test-{uuid_mod.uuid4()}",
        "request": {
            "contents": [
                {"role": "user", "parts": [{"text": "Say hello in one word"}]}
            ],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 100},
        },
        "model": "gemini-2.5-flash",
        "userAgent": "antigravity",
        "requestType": "agent",
    }

    try:
        response = auth_session.request(
            method="POST",
            url=url,
            params={"alt": "sse"},
            json=correct_request,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        print(f"    - Status: {response.status_code}")
        if response.status_code == 200:
            print(f"    - Response: {response.text[:500]}")
            print("\n    [SUCCESS] API call succeeded!")
        else:
            print(f"    - Response: {response.text[:500]}")
            print("\n    [FAILED] API call returned non-200 status")
    except Exception as e:
        print(f"    - ERROR: {e}")

    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_antigravity_backend())
