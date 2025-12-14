"""Property-based tests for SSO AuthMiddleware.

Feature: sso-authentication
Properties: 4, 9, 10, 12, 13, 25
Validates: Requirements 2.1, 2.2, 2.3, 4.1, 4.2, 5.1, 5.2, 5.3, 9.1, 9.2, 9.3
"""

from __future__ import annotations

import asyncio
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from hypothesis import given
from hypothesis import strategies as st
from src.core.auth.sso.database import DatabaseManager, TokenRepository
from src.core.auth.sso.middleware import AuthMiddleware
from src.core.auth.sso.models import TokenRecord
from src.core.auth.sso.sandbox_handler import SandboxHandler
from src.core.auth.sso.token_service import TokenService
from tests.utils.hypothesis_config import property_test_settings


@contextmanager
def temp_db_path():
    """Context manager for temporary database path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield str(Path(tmpdir) / "test.db")


# Strategies for generating test data


@st.composite
def request_without_token_strategy(draw: st.DrawFn) -> dict:
    """Generate request without Bearer token."""
    # Request can have no headers, empty headers, or headers without Authorization
    choice = draw(st.integers(min_value=0, max_value=2))

    if choice == 0:
        # No headers at all
        return {"messages": []}
    elif choice == 1:
        # Empty headers
        return {"headers": {}, "messages": []}
    else:
        # Headers without Authorization
        return {
            "headers": {
                "Content-Type": "application/json",
                "User-Agent": "test-agent",
            },
            "messages": [],
        }


@st.composite
def request_with_unknown_token_strategy(draw: st.DrawFn) -> dict:
    """Generate request with unknown/invalid Bearer token."""
    # Generate random token that won't be in database
    token = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"
            ),
            min_size=43,
            max_size=100,
        )
    )

    return {
        "headers": {
            "Authorization": f"Bearer {token}",
        },
        "messages": [],
    }


@st.composite
def request_with_malformed_auth_strategy(draw: st.DrawFn) -> dict:
    """Generate request with malformed Authorization header."""
    choice = draw(st.integers(min_value=0, max_value=4))

    if choice == 0:
        # Missing Bearer scheme
        auth_header = draw(st.text(min_size=1, max_size=100))
    elif choice == 1:
        # Wrong scheme
        token = draw(st.text(min_size=1, max_size=100))
        auth_header = f"Basic {token}"
    elif choice == 2:
        # Multiple spaces
        token = draw(st.text(min_size=1, max_size=100))
        auth_header = f"Bearer  {token}"
    elif choice == 3:
        # No token after Bearer
        auth_header = "Bearer"
    else:
        # Extra parts
        token = draw(st.text(min_size=1, max_size=100))
        extra = draw(st.text(min_size=1, max_size=100))
        auth_header = f"Bearer {token} {extra}"

    return {
        "headers": {
            "Authorization": auth_header,
        },
        "messages": [],
    }


@st.composite
def messages_with_sandbox_marker_strategy(draw: st.DrawFn) -> list[dict]:
    """Generate message list containing sandbox markers."""
    # Choose a sandbox marker
    markers = [
        "# Authentication Required",
        "Authentication Required",
        "Welcome to the LLM Proxy with SSO authentication",
    ]
    marker = draw(st.sampled_from(markers))

    # Generate some messages
    num_messages = draw(st.integers(min_value=1, max_value=5))
    marker_position = draw(st.integers(min_value=0, max_value=num_messages - 1))
    messages = []

    for i in range(num_messages):
        # Place the marker in the designated position
        if i == marker_position:
            content = f"Some text before {marker} some text after"
        else:
            content = draw(st.text(min_size=1, max_size=100))

        messages.append(
            {
                "role": draw(st.sampled_from(["user", "assistant"])),
                "content": content,
            }
        )

    return messages


# Property tests


@given(request=request_without_token_strategy())
@property_test_settings()
def test_property_4_unauthenticated_request_sandbox_response(
    request: dict,
) -> None:
    """
    Property 4: Unauthenticated Request Sandbox Response.

    For any request without a valid Bearer token (missing, empty, or unknown
    token), the proxy SHALL return a sandbox response containing the login
    banner instead of processing the request.

    Validates: Requirements 2.1, 2.2, 2.3

    Feature: sso-authentication, Property 4: Unauthenticated Request Sandbox Response
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Execute
            response = await middleware(request)

            # Verify
            assert response is not None, "Should return sandbox response"
            assert isinstance(response, dict), "Response should be a dictionary"

            # Verify it's a valid chat completion response
            assert "id" in response
            assert "object" in response
            assert response["object"] == "chat.completion"
            assert "choices" in response
            assert len(response["choices"]) > 0

            # Verify it contains authentication instructions
            content = response["choices"][0]["message"]["content"]
            assert "Authentication Required" in content
            assert "http://localhost:8080/auth/login" in content

    asyncio.run(run_test())


@given(request=request_with_unknown_token_strategy())
@property_test_settings()
def test_property_9_unknown_token_rejection(
    request: dict,
) -> None:
    """
    Property 9: Unknown Token Rejection.

    For any Bearer token that does not match any stored token hash, the proxy
    SHALL treat the request as unauthenticated and return a sandbox response.

    Validates: Requirements 4.1

    Feature: sso-authentication, Property 9: Unknown Token Rejection
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Execute
            response = await middleware(request)

            # Verify
            assert (
                response is not None
            ), "Should return sandbox response for unknown token"
            assert isinstance(response, dict), "Response should be a dictionary"
            assert response["object"] == "chat.completion"

            # Verify it contains authentication instructions
            content = response["choices"][0]["message"]["content"]
            assert "Authentication Required" in content

    asyncio.run(run_test())


@given(
    request1=request_with_unknown_token_strategy(),
    request2=request_with_unknown_token_strategy(),
)
@property_test_settings(max_examples=50)
def test_property_10_token_response_indistinguishability(
    request1: dict,
    request2: dict,
) -> None:
    """
    Property 10: Token Response Indistinguishability.

    For any two invalid Bearer tokens (regardless of format, length, or
    content), the sandbox responses returned SHALL be identical in structure
    and timing characteristics.

    Validates: Requirements 4.2

    Feature: sso-authentication, Property 10: Token Response Indistinguishability
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Execute
            response1 = await middleware(request1)
            response2 = await middleware(request2)

            # Verify both are sandbox responses
            assert response1 is not None
            assert response2 is not None

            # Verify structure is identical (excluding timestamp)
            assert response1["object"] == response2["object"]
            assert response1["model"] == response2["model"]
            assert len(response1["choices"]) == len(response2["choices"])

            # Verify content is identical
            content1 = response1["choices"][0]["message"]["content"]
            content2 = response2["choices"][0]["message"]["content"]
            assert (
                content1 == content2
            ), "Responses should be identical for all invalid tokens"

            # Verify finish_reason is identical
            assert (
                response1["choices"][0]["finish_reason"]
                == response2["choices"][0]["finish_reason"]
            )

    asyncio.run(run_test())


@given(request=request_with_malformed_auth_strategy())
@property_test_settings(max_examples=50)
def test_property_4_malformed_auth_header_sandbox_response(
    request: dict,
) -> None:
    """
    Property 4: Malformed Authorization header sandbox response.

    For any request with a malformed Authorization header, the proxy SHALL
    return a sandbox response.

    Validates: Requirements 2.1

    Feature: sso-authentication, Property 4: Unauthenticated Request Sandbox Response
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Execute
            response = await middleware(request)

            # Verify
            assert (
                response is not None
            ), "Should return sandbox response for malformed auth"
            assert isinstance(response, dict)
            assert response["object"] == "chat.completion"

    asyncio.run(run_test())


@given(messages=messages_with_sandbox_marker_strategy())
@property_test_settings(max_examples=50)
def test_property_26_sandbox_session_isolation(
    messages: list[dict],
) -> None:
    """
    Property 26: Sandbox Session Isolation.

    For any request containing conversation history with a sandbox login
    banner message, the proxy SHALL reject the request and return a new
    sandbox response, regardless of the Bearer token's validity.

    Validates: Requirements 10.1, 10.2, 10.4, 10.5

    Feature: sso-authentication, Property 26: Sandbox Session Isolation
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Create a valid token and store it
            plaintext_token, token_hash = token_service.generate_token()
            token_record = TokenRecord(
                id=str(uuid4()),
                token_hash=token_hash,
                user_id="test-user",
                user_email="test@example.com",
                provider="google",
                is_authenticated=True,
                is_active=True,
                created_at=datetime.utcnow(),
                last_authenticated_at=datetime.utcnow(),
                auth_expires_at=datetime.utcnow() + timedelta(hours=24),
            )
            await token_repository.store_token(token_record)

            # Create request with valid token but sandbox history
            request = {
                "headers": {
                    "Authorization": f"Bearer {plaintext_token}",
                },
                "messages": messages,
            }

            # Execute
            response = await middleware(request)

            # Verify
            assert (
                response is not None
            ), "Should return sandbox response even with valid token"
            assert isinstance(response, dict)
            assert response["object"] == "chat.completion"

            # Verify it's a new sandbox response (not continuing the session)
            content = response["choices"][0]["message"]["content"]
            assert "Authentication Required" in content

    asyncio.run(run_test())


@given(
    session_lifetime_hours=st.integers(min_value=1, max_value=48),
)
@property_test_settings()
def test_property_13_session_expiry_status_change(
    session_lifetime_hours: int,
) -> None:
    """
    Property 13: Session Expiry Status Change.

    For any authenticated agent token, when the SSO session expiry time
    passes, the token's authentication status SHALL change to unauthenticated.

    Validates: Requirements 5.2

    Feature: sso-authentication, Property 13: Session Expiry Status Change
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Create a token with expired session
            plaintext_token, token_hash = token_service.generate_token()
            expired_time = datetime.utcnow() - timedelta(hours=1)  # Expired 1 hour ago

            token_record = TokenRecord(
                id=str(uuid4()),
                token_hash=token_hash,
                user_id="test-user",
                user_email="test@example.com",
                provider="google",
                is_authenticated=True,  # Initially authenticated
                is_active=True,
                created_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 2),
                last_authenticated_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 1),
                auth_expires_at=expired_time,  # Expired
            )
            await token_repository.store_token(token_record)

            # Create request with expired token
            # Note: request variable is not used as we test validate_token directly
            # request = {
            #     "headers": {
            #         "Authorization": f"Bearer {plaintext_token}",
            #     },
            #     "messages": [],
            # }

            # Execute - this should detect expiry and update status
            validation_result = await middleware.validate_token(plaintext_token)

            # Verify token is valid but not authenticated
            assert validation_result.is_valid is True
            assert (
                validation_result.is_authenticated is False
            ), "Expired token should not be authenticated"

            # Verify database was updated
            updated_record = await token_repository.find_by_hash(token_hash)
            assert updated_record is not None
            assert (
                updated_record.is_authenticated is False
            ), "Database should reflect unauthenticated status"

    asyncio.run(run_test())


@given(
    session_lifetime_hours=st.integers(min_value=1, max_value=48),
)
@property_test_settings()
def test_property_25_expired_session_sandbox_response(
    session_lifetime_hours: int,
) -> None:
    """
    Property 25: Expired Session Sandbox Response.

    For any request with a valid but expired agent token (SSO session expired),
    the proxy SHALL return a sandbox response containing the re-authentication
    URL.

    Validates: Requirements 9.1, 9.2

    Feature: sso-authentication, Property 25: Expired Session Sandbox Response
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Create a token with expired session
            plaintext_token, token_hash = token_service.generate_token()
            expired_time = datetime.utcnow() - timedelta(hours=1)

            token_record = TokenRecord(
                id=str(uuid4()),
                token_hash=token_hash,
                user_id="test-user",
                user_email="test@example.com",
                provider="google",
                is_authenticated=True,  # Initially authenticated
                is_active=True,
                created_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 2),
                last_authenticated_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 1),
                auth_expires_at=expired_time,
            )
            await token_repository.store_token(token_record)

            # Create request with expired token
            request = {
                "headers": {
                    "Authorization": f"Bearer {plaintext_token}",
                },
                "messages": [],
            }

            # Execute
            response = await middleware(request)

            # Verify
            assert (
                response is not None
            ), "Should return sandbox response for expired session"
            assert isinstance(response, dict)
            assert response["object"] == "chat.completion"

            # Verify it contains re-authentication instructions
            content = response["choices"][0]["message"]["content"]
            assert "Authentication Required" in content
            assert "http://localhost:8080/auth/login" in content

    asyncio.run(run_test())


@given(
    num_requests=st.integers(min_value=2, max_value=10),
)
@property_test_settings()
def test_property_4_consistent_sandbox_responses(
    num_requests: int,
) -> None:
    """
    Property 4: Consistent sandbox responses.

    For any sequence of unauthenticated requests, all sandbox responses
    SHALL have consistent structure and content.

    Validates: Requirements 2.1, 2.2, 2.3

    Feature: sso-authentication, Property 4: Unauthenticated Request Sandbox Response
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            # Generate multiple requests without tokens
            responses = []
            for _ in range(num_requests):
                request = {"messages": []}
                response = await middleware(request)
                responses.append(response)

            # Verify all responses are identical (excluding timestamp)
            first_response = responses[0]
            for response in responses[1:]:
                assert response["object"] == first_response["object"]
                assert response["model"] == first_response["model"]
                assert (
                    response["choices"][0]["message"]["content"]
                    == first_response["choices"][0]["message"]["content"]
                )

    asyncio.run(run_test())


@given(
    session_lifetime_hours=st.integers(min_value=1, max_value=48),
    user_id=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=5,
        max_size=50,
    ),
    user_email=st.emails(),
)
@property_test_settings(max_examples=50)
def test_property_12_reauthentication_status_update(
    session_lifetime_hours: int,
    user_id: str,
    user_email: str,
) -> None:
    """
    Property 12: Re-authentication Status Update.

    For any existing agent token, when the associated user completes SSO
    re-authentication, the token's authentication status SHALL be updated
    to authenticated without generating a new token.

    Validates: Requirements 5.1, 5.3, 9.3

    Feature: sso-authentication, Property 12: Re-authentication Status Update
    """

    async def run_test():
        with temp_db_path() as db_path:
            # Setup
            db_manager = DatabaseManager(db_path)
            await db_manager.initialize_schema()

            # Use fast configuration for tests
            token_service = TokenService.create_for_environment()
            token_repository = TokenRepository(db_path)

            # Create an initial token for the user (expired session)
            plaintext_token, token_hash = token_service.generate_token()
            expired_time = datetime.utcnow() - timedelta(hours=1)

            original_token_record = TokenRecord(
                id=str(uuid4()),
                token_hash=token_hash,
                user_id=user_id,
                user_email=user_email,
                provider="google",
                is_authenticated=False,  # Session expired
                is_active=True,
                created_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 2),
                last_authenticated_at=datetime.utcnow()
                - timedelta(hours=session_lifetime_hours + 1),
                auth_expires_at=expired_time,
            )
            await token_repository.store_token(original_token_record)

            # Simulate re-authentication: find existing token by user_id
            existing_token = await token_repository.find_by_user_id(user_id)
            assert existing_token is not None, "Should find existing token"
            assert existing_token.id == original_token_record.id, "Should be same token"

            # Update auth status (simulating successful re-authentication)
            new_expiry = datetime.utcnow() + timedelta(hours=session_lifetime_hours)
            await token_repository.update_auth_status(
                existing_token.id,
                authenticated=True,
                expiry=new_expiry,
            )

            # Verify the token was updated, not replaced
            updated_token = await token_repository.find_by_hash(token_hash)
            assert updated_token is not None, "Token should still exist"
            assert (
                updated_token.id == original_token_record.id
            ), "Token ID should not change"
            assert (
                updated_token.token_hash == token_hash
            ), "Token hash should not change"
            assert (
                updated_token.is_authenticated is True
            ), "Token should now be authenticated"
            assert updated_token.auth_expires_at is not None, "Should have new expiry"
            assert (
                updated_token.auth_expires_at > datetime.utcnow()
            ), "Expiry should be in future"

            # Verify no new token was created for this user
            all_hashes = await token_repository.get_all_token_hashes()
            assert (
                len(all_hashes) == 1
            ), "Should still have only one token for this user"
            assert (
                all_hashes[0] == token_hash
            ), "Should be the original token, not a new one"

            # Verify the token can now be used for authentication
            sandbox_handler = SandboxHandler("http://localhost:8080/auth/login")
            middleware = AuthMiddleware(
                token_service, token_repository, sandbox_handler
            )

            request = {
                "headers": {
                    "Authorization": f"Bearer {plaintext_token}",
                },
                "messages": [],
            }

            response = await middleware(request)
            assert (
                response is None
            ), "Re-authenticated token should allow request to proceed"

    asyncio.run(run_test())
