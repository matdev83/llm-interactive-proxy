"""Property-based tests for SSO authorization service.

Feature: sso-authentication
Properties: 15, 16
Validates: Requirements 6.3, 6.5
"""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import respx
from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.authorization_service import (
    AuthorizationMode,
    AuthorizationService,
)
from src.core.auth.sso.config import AuthorizationConfig
from src.core.auth.sso.database import DatabaseManager
from src.core.auth.sso.rate_limit_service import RateLimitService
from tests.utils.hypothesis_config import property_test_settings


@contextmanager
def temp_db_path():
    """Context manager for temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


# Strategies
@st.composite
def authorization_config_strategy(draw: st.DrawFn) -> AuthorizationConfig:
    """Generate valid AuthorizationConfig."""
    return AuthorizationConfig(
        mode=draw(st.sampled_from(["single_user", "enterprise"])),
        api_url=draw(
            st.one_of(
                st.none(),
                st.text(
                    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
                    min_size=1,
                ).map(lambda s: f"https://example.com/{s}"),
            )
        ),
        api_timeout=draw(st.integers(min_value=1, max_value=60)),
        confirmation_code_expiry_minutes=draw(st.integers(min_value=5, max_value=60)),
        max_confirmation_attempts=draw(st.integers(min_value=3, max_value=10)),
    )


@given(config=authorization_config_strategy())
@property_test_settings()
@pytest.mark.slow  # Uses database operations - 49s
def test_property_15_confirmation_code_attempt_decrement(
    config: AuthorizationConfig,
) -> None:
    """
    Property 15: Confirmation Code Attempt Decrement.

    For any incorrect confirmation code entry in single-user mode, the remaining
    attempts counter SHALL decrease by exactly 1.

    Validates: Requirements 6.3

    Feature: sso-authentication, Property 15: Confirmation Code Attempt Decrement
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.SINGLE_USER,
                config,
                db_manager,
                rate_limit_service,
            )

            # Create pending auth
            sso_state = "test-state"
            user_email = "test@example.com"
            client_ip = "127.0.0.1"

            # Manually create one to capture the code (since generate is random)
            # But create_pending_authorization logs it, doesn't return it.
            # However, for INCORRECT code test, we can just use "wrong-code".
            await service.create_pending_authorization(
                sso_state, user_email, "user-id", "google", client_ip
            )

            # Verify initial state
            import aiosqlite

            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT attempts_remaining FROM pending_authorizations WHERE sso_state = ?",
                    (sso_state,),
                )
                row = await cursor.fetchone()
                initial_attempts = row["attempts_remaining"]
                assert initial_attempts == config.max_confirmation_attempts

            # Verify with wrong code
            result = await service.verify_confirmation_code(
                sso_state, "wrong-code", client_ip
            )

            # Check result
            assert result.success is False
            assert result.attempts_remaining == initial_attempts - 1

            # Verify database state
            async with aiosqlite.connect(db_path) as db:
                db.row_factory = aiosqlite.Row
                cursor = await db.execute(
                    "SELECT attempts_remaining FROM pending_authorizations WHERE sso_state = ?",
                    (sso_state,),
                )
                row = await cursor.fetchone()
                current_attempts = row["attempts_remaining"]
                assert current_attempts == initial_attempts - 1

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_16_correct_confirmation_code_success(
    config: AuthorizationConfig,
) -> None:
    """
    Property 16: Correct Confirmation Code Success.

    For any correct confirmation code entry in single-user mode, the proxy
    SHALL return success and cleanup the pending authorization.

    Validates: Requirements 6.5

    Feature: sso-authentication, Property 16: Correct Confirmation Code Success
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.SINGLE_USER,
                config,
                db_manager,
                rate_limit_service,
            )

            sso_state = "test-state-success"
            client_ip = "127.0.0.1"

            # To test success, we need to know the code.
            # Since generate_confirmation_code is random and called internally,
            # we can monkeypatch it or check the database hash (hard because hash is one-way).
            # Better: monkeypatch generate_confirmation_code to return known code.
            known_code = "123456"
            original_generate = service.generate_confirmation_code
            service.generate_confirmation_code = lambda: known_code

            try:
                await service.create_pending_authorization(
                    sso_state, "test@example.com", "user-id", "google", client_ip
                )
            finally:
                service.generate_confirmation_code = original_generate

            # Verify with correct code
            result = await service.verify_confirmation_code(
                sso_state, known_code, client_ip
            )

            assert result.success is True
            # Attempts remaining is irrelevant on success, but usually returns what was there

            # Verify pending auth is deleted
            import aiosqlite

            async with aiosqlite.connect(db_path) as db:
                cursor = await db.execute(
                    "SELECT count(*) FROM pending_authorizations WHERE sso_state = ?",
                    (sso_state,),
                )
                row = await cursor.fetchone()
                assert row[0] == 0

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_18_authorization_api_invocation(
    config: AuthorizationConfig,
) -> None:
    """
    Property 18: Authorization API Invocation.

    For any successful SSO authentication in enterprise mode, the proxy SHALL
    make exactly one HTTP request to the configured authorization API URL.

    Validates: Requirements 7.1

    Feature: sso-authentication, Property 18: Authorization API Invocation
    """
    if config.api_url is None:
        return

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.ENTERPRISE,
                config,
                db_manager,
                rate_limit_service,
            )

            user_id = "user-123"
            user_email = "test@example.com"
            client_ip = "192.168.1.1"

            # Mock API
            async with respx.mock as mock:
                route = mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, json={"authorized": True})
                )

                result = await service.query_authorization_api(
                    user_id, user_email, client_ip
                )

                assert result.authorized is True
                assert route.called
                assert route.call_count == 1

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_19_authorization_api_request_payload(
    config: AuthorizationConfig,
) -> None:
    """
    Property 19: Authorization API Request Payload.

    For any authorization API request, the request body SHALL contain the
    user's SSO identity (email or ID) and the client's IP address.

    Validates: Requirements 7.2

    Feature: sso-authentication, Property 19: Authorization API Request Payload
    """
    if config.api_url is None:
        return

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.ENTERPRISE,
                config,
                db_manager,
                rate_limit_service,
            )

            user_id = str(uuid4())
            user_email = "test@example.com"
            client_ip = "10.0.0.1"

            # Mock API
            async with respx.mock as mock:
                route = mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, json={"authorized": True})
                )

                await service.query_authorization_api(user_id, user_email, client_ip)

                assert route.called
                request = route.calls.last.request
                payload = request.read().decode("utf-8")
                import json

                data = json.loads(payload)

                assert data["user_id"] == user_id
                assert data["user_email"] == user_email
                assert data["client_ip"] == client_ip

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_20_authorization_api_success_path(
    config: AuthorizationConfig,
) -> None:
    """
    Property 20: Authorization API Success Path.

    For any authorization API response returning true/1, the proxy SHALL
    authorize the user.

    Validates: Requirements 7.3

    Feature: sso-authentication, Property 20: Authorization API Success Path
    """
    if config.api_url is None:
        return

    async def run_test():
        with temp_db_path() as db_path:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.ENTERPRISE,
                config,
                db_manager,
                rate_limit_service,
            )

            # Test JSON response
            async with respx.mock as mock:
                mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, json={"authorized": True})
                )
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is True

            # Test simple boolean body (if supported fallback)
            async with respx.mock as mock:
                mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, text="true")
                )
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is True

            # Test integer 1 body
            async with respx.mock as mock:
                mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, text="1")
                )
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is True

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_21_authorization_api_denial_path(
    config: AuthorizationConfig,
) -> None:
    """
    Property 21: Authorization API Denial Path.

    For any authorization API response returning false/0, the proxy SHALL
    deny access.

    Validates: Requirements 7.4

    Feature: sso-authentication, Property 21: Authorization API Denial Path
    """
    if config.api_url is None:
        return

    async def run_test():
        with temp_db_path() as db_path:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.ENTERPRISE,
                config,
                db_manager,
                rate_limit_service,
            )

            # Test JSON response
            async with respx.mock as mock:
                mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, json={"authorized": False})
                )
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is False

            # Test simple boolean body
            async with respx.mock as mock:
                mock.post(config.api_url).mock(
                    return_value=httpx.Response(200, text="false")
                )
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is False

    asyncio.run(run_test())


@given(config=authorization_config_strategy())
@property_test_settings()
def test_property_22_authorization_api_error_handling(
    config: AuthorizationConfig,
) -> None:
    """
    Property 22: Authorization API Error Handling.

    For any authorization API error (timeout, connection failure, non-2xx
    response), the proxy SHALL deny access.

    Validates: Requirements 7.5

    Feature: sso-authentication, Property 22: Authorization API Error Handling
    """
    if config.api_url is None:
        return

    async def run_test():
        with temp_db_path() as db_path:
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()
            rate_limit_service = RateLimitService(db_manager)
            service = AuthorizationService(
                AuthorizationMode.ENTERPRISE,
                config,
                db_manager,
                rate_limit_service,
            )

            # Test 500 error
            async with respx.mock as mock:
                mock.post(config.api_url).mock(return_value=httpx.Response(500))
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is False
                assert result.error is not None

            # Test connection error
            async with respx.mock as mock:
                mock.post(config.api_url).mock(side_effect=httpx.ConnectError("Fail"))
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is False
                assert result.error is not None

            # Test timeout
            async with respx.mock as mock:
                mock.post(config.api_url).mock(side_effect=httpx.TimeoutException("TO"))
                result = await service.query_authorization_api("u1", "e1", "127.0.0.1")
                assert result.authorized is False
                assert result.error == "API timeout"

    asyncio.run(run_test())
