"""
Property-based tests for SSO authorization service (Enterprise Mode).

These tests verify correctness properties for authorization API integration
using Hypothesis.
"""

import os
import tempfile
from contextlib import asynccontextmanager, suppress

import httpx
import pytest
import respx
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.config import AuthorizationConfig
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.rate_limit_service import RateLimitService


@asynccontextmanager
async def temp_database_context():
    """Context manager for creating a temporary database."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as f:
        db_path = f.name

    try:
        # Initialize database schema
        db_manager = DatabaseManager(db_path)
        await db_manager.initialize_schema()

        yield db_path, db_manager
    finally:
        # Cleanup
        with suppress(Exception):
            os.unlink(db_path)


def create_authorization_service(
    db_manager: DatabaseManager, api_url: str
) -> AuthorizationService:
    """Helper to create authorization service for testing."""
    config = AuthorizationConfig(
        mode="enterprise",
        api_url=api_url,
        api_timeout=10,
    )
    rate_limit_service = RateLimitService(db_manager)
    return AuthorizationService(
        mode=AuthorizationMode.ENTERPRISE,
        config=config,
        database_manager=db_manager,
        rate_limit_service=rate_limit_service,
    )


# Feature: sso-authentication, Property 18: Authorization API Invocation
@pytest.mark.asyncio
@settings(
    max_examples=5,  # Reduced from 6 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=100),
    client_ip=st.ip_addresses(v=4).map(str),
)
async def test_property_18_authorization_api_invocation(user_email, user_id, client_ip):
    """
    Property 18: Authorization API Invocation

    For any successful SSO authentication in enterprise mode,
    the proxy SHALL make exactly one HTTP request to the configured
    authorization API URL.

    Validates: Requirements 7.1
    """
    async with temp_database_context() as (temp_database, db_manager):
        # Configure mock authorization API
        api_url = "https://auth.example.com/authorize"

        async with respx.mock:
            # Mock the API endpoint
            route = respx.post(api_url).mock(
                return_value=httpx.Response(200, json={"authorized": True})
            )

            # Create service in enterprise mode
            service = create_authorization_service(db_manager, api_url)

            # Query authorization API
            result = await service.query_authorization_api(
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
            )

            # Verify exactly one request was made
            assert route.called, "Authorization API should be called"
            assert (
                route.call_count == 1
            ), f"Expected exactly 1 API call, got {route.call_count}"

            # Verify result
            assert (
                result.authorized is not None
            ), "Result should have authorization decision"


# Feature: sso-authentication, Property 19: Authorization API Request Payload
@pytest.mark.asyncio
@settings(
    max_examples=5,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=100),
    client_ip=st.ip_addresses(v=4).map(str),
)
async def test_property_19_authorization_api_request_payload(
    user_email, user_id, client_ip
):
    """
    Property 19: Authorization API Request Payload

    For any authorization API request, the request body SHALL contain
    the user's SSO identity (email or ID) and the client's IP address.

    Validates: Requirements 7.2
    """
    async with temp_database_context() as (temp_database, db_manager):
        # Configure mock authorization API
        api_url = "https://auth.example.com/authorize"

        # Capture request
        captured_request = None

        def capture_request(request):
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json={"authorized": True})

        async with respx.mock:
            respx.post(api_url).mock(side_effect=capture_request)

            # Create service in enterprise mode
            service = create_authorization_service(db_manager, api_url)

            # Query authorization API
            await service.query_authorization_api(
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
            )

            # Verify request payload
            assert captured_request is not None, "Request should be captured"

            # Parse request body
            import json

            payload = json.loads(captured_request.content)

            # Verify required fields are present
            assert "user_id" in payload, "Payload should contain user_id"
            assert "user_email" in payload, "Payload should contain user_email"
            assert "client_ip" in payload, "Payload should contain client_ip"

            # Verify values match
            assert (
                payload["user_id"] == user_id
            ), f"Expected user_id {user_id}, got {payload['user_id']}"
            assert (
                payload["user_email"] == user_email
            ), f"Expected user_email {user_email}, got {payload['user_email']}"
            assert (
                payload["client_ip"] == client_ip
            ), f"Expected client_ip {client_ip}, got {payload['client_ip']}"


# Feature: sso-authentication, Property 20: Authorization API Success Path
@pytest.mark.asyncio
@settings(
    max_examples=5,  # Reduced from 10 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=50),  # Reduced from 100 for performance
    client_ip=st.ip_addresses(v=4).map(str),
    # Test both boolean and integer (0/1) responses
    authorized_value=st.sampled_from([True, 1]),
)
async def test_property_20_authorization_api_success_path(
    user_email, user_id, client_ip, authorized_value
):
    """
    Property 20: Authorization API Success Path

    For any authorization API response returning true/1,
    the proxy SHALL authorize the user and generate a valid agent token.

    Note: This test verifies authorization succeeds. Token generation
    is handled by a different service and tested separately.

    Validates: Requirements 7.3
    """
    async with temp_database_context() as (temp_database, db_manager):
        # Configure mock authorization API
        api_url = "https://auth.example.com/authorize"

        async with respx.mock:
            # Mock the API endpoint with authorized response
            respx.post(api_url).mock(
                return_value=httpx.Response(200, json={"authorized": authorized_value})
            )

            # Create service in enterprise mode
            service = create_authorization_service(db_manager, api_url)

            # Query authorization API
            result = await service.query_authorization_api(
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
            )

            # Verify authorization succeeded
            assert result.authorized is True, (
                f"Expected authorized=True for value {authorized_value}, "
                f"got {result.authorized}"
            )
            assert (
                result.error is None
            ), f"Expected no error on success, got {result.error}"


# Feature: sso-authentication, Property 21: Authorization API Denial Path
@pytest.mark.asyncio
@settings(
    max_examples=5,  # Reduced from 10 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=100),
    client_ip=st.ip_addresses(v=4).map(str),
    # Test both boolean and integer (0) responses
    denied_value=st.sampled_from([False, 0]),
)
async def test_property_21_authorization_api_denial_path(
    user_email, user_id, client_ip, denied_value
):
    """
    Property 21: Authorization API Denial Path

    For any authorization API response returning false/0,
    the proxy SHALL deny access and return an "access denied" message
    without generating a token.

    Validates: Requirements 7.4
    """
    async with temp_database_context() as (temp_database, db_manager):
        # Configure mock authorization API
        api_url = "https://auth.example.com/authorize"

        async with respx.mock:
            # Mock the API endpoint with denied response
            respx.post(api_url).mock(
                return_value=httpx.Response(200, json={"authorized": denied_value})
            )

            # Create service in enterprise mode
            service = create_authorization_service(db_manager, api_url)

            # Query authorization API
            result = await service.query_authorization_api(
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
            )

            # Verify authorization was denied
            assert result.authorized is False, (
                f"Expected authorized=False for value {denied_value}, "
                f"got {result.authorized}"
            )


# Feature: sso-authentication, Property 22: Authorization API Error Handling
@pytest.mark.asyncio
@settings(
    max_examples=8,  # Reduced from 10 for performance
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    user_email=st.emails(),
    user_id=st.text(min_size=1, max_size=100),
    client_ip=st.ip_addresses(v=4).map(str),
    # Test various error scenarios
    error_scenario=st.sampled_from(
        [
            "timeout",
            "connection_error",
            "http_500",
            "http_404",
            "invalid_json",
        ]
    ),
)
async def test_property_22_authorization_api_error_handling(
    user_email, user_id, client_ip, error_scenario
):
    """
    Property 22: Authorization API Error Handling

    For any authorization API error (timeout, connection failure,
    non-2xx response, invalid response format), the proxy SHALL
    deny access and log the error.

    Validates: Requirements 7.5
    """
    async with temp_database_context() as (temp_database, db_manager):
        # Configure mock authorization API
        api_url = "https://auth.example.com/authorize"

        async with respx.mock:
            # Mock different error scenarios
            if error_scenario == "timeout":
                respx.post(api_url).mock(side_effect=httpx.TimeoutException("Timeout"))
            elif error_scenario == "connection_error":
                respx.post(api_url).mock(
                    side_effect=httpx.ConnectError("Connection failed")
                )
            elif error_scenario == "http_500":
                respx.post(api_url).mock(
                    return_value=httpx.Response(500, text="Internal Server Error")
                )
            elif error_scenario == "http_404":
                respx.post(api_url).mock(
                    return_value=httpx.Response(404, text="Not Found")
                )
            elif error_scenario == "invalid_json":
                respx.post(api_url).mock(
                    return_value=httpx.Response(200, text="not valid json")
                )

            # Create service in enterprise mode
            service = create_authorization_service(db_manager, api_url)

            # Query authorization API
            result = await service.query_authorization_api(
                user_id=user_id,
                user_email=user_email,
                client_ip=client_ip,
            )

            # Verify authorization was denied on error
            assert result.authorized is False, (
                f"Expected authorized=False on error scenario {error_scenario}, "
                f"got {result.authorized}"
            )

            # Verify error message is present
            assert result.error is not None, (
                f"Expected error message on error scenario {error_scenario}, "
                f"got None"
            )
            assert (
                len(result.error) > 0
            ), f"Expected non-empty error message on error scenario {error_scenario}"
