"""Unit tests for AuthMiddleware.

Tests token extraction, validation logic, and expiry handling.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiosqlite import Error as DatabaseError
from freezegun import freeze_time
from src.core.auth.sso.exceptions import TokenError
from src.core.auth.sso.middleware import AuthMiddleware


class TestAuthMiddleware:
    """Test suite for AuthMiddleware."""

    @pytest.fixture
    def mock_token_service(self) -> MagicMock:
        """Create mock token service."""
        service = MagicMock()
        service.verify_token = MagicMock(return_value=True)
        return service

    @pytest.fixture
    def mock_token_repository(self) -> MagicMock:
        """Create mock token repository."""
        repo = MagicMock()
        repo.get_all_token_hashes = AsyncMock(return_value=[])
        repo.find_by_hash = AsyncMock(return_value=None)
        repo.update_auth_status = AsyncMock()
        return repo

    @pytest.fixture
    def mock_sandbox_handler(self) -> MagicMock:
        """Create mock sandbox handler."""
        handler = MagicMock()
        handler.generate_login_banner = AsyncMock(
            return_value={"id": "sandbox", "choices": []}
        )
        handler.detect_sandbox_history = MagicMock(return_value=False)
        return handler

    @pytest.fixture
    def middleware(
        self,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> AuthMiddleware:
        """Create AuthMiddleware instance."""
        return AuthMiddleware(
            mock_token_service, mock_token_repository, mock_sandbox_handler
        )

    # =========================================================================
    # Token Extraction Tests
    # =========================================================================

    def test_extract_bearer_token_valid(self, middleware: AuthMiddleware) -> None:
        """Test extracting valid Bearer token."""
        request = {"headers": {"Authorization": "Bearer test-token-123"}}

        token = middleware.extract_bearer_token(request)

        assert token == "test-token-123"

    def test_extract_bearer_token_case_insensitive(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test that Authorization header is case-insensitive."""
        request = {"headers": {"authorization": "Bearer test-token-123"}}

        token = middleware.extract_bearer_token(request)

        assert token == "test-token-123"

    def test_extract_bearer_token_mixed_case(self, middleware: AuthMiddleware) -> None:
        """Test Authorization header with mixed case."""
        request = {"headers": {"AuThOrIzAtIoN": "Bearer test-token-123"}}

        token = middleware.extract_bearer_token(request)

        assert token == "test-token-123"

    def test_extract_bearer_token_missing_header(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with missing Authorization header."""
        request = {"headers": {}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_missing_headers_dict(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with missing headers dictionary."""
        request = {}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_wrong_scheme(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with wrong authentication scheme."""
        request = {"headers": {"Authorization": "Basic dXNlcjpwYXNz"}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_malformed_single_part(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with malformed header (single part)."""
        request = {"headers": {"Authorization": "BearerTokenWithoutSpace"}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_malformed_three_parts(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with malformed header (three parts)."""
        request = {"headers": {"Authorization": "Bearer token extra"}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_empty_string(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with empty Authorization header."""
        request = {"headers": {"Authorization": ""}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_non_string_value(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test extraction with non-string Authorization value."""
        request = {"headers": {"Authorization": 12345}}

        token = middleware.extract_bearer_token(request)

        assert token is None

    def test_extract_bearer_token_bearer_case_insensitive(
        self, middleware: AuthMiddleware
    ) -> None:
        """Test that Bearer scheme is case-insensitive."""
        request = {"headers": {"Authorization": "bearer test-token-123"}}

        token = middleware.extract_bearer_token(request)

        assert token == "test-token-123"

    # =========================================================================
    # Token Validation Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_validate_token_not_found(
        self,
        middleware: AuthMiddleware,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation when token is not found in database."""
        mock_token_repository.get_all_token_hashes.return_value = []

        result = await middleware.validate_token("unknown-token")

        assert result.is_valid is False
        assert result.user_id is None
        assert result.is_authenticated is False
        assert result.token_id is None

    @pytest.mark.asyncio
    async def test_validate_token_database_error(
        self,
        middleware: AuthMiddleware,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation when database query fails."""
        mock_token_repository.get_all_token_hashes.side_effect = DatabaseError(
            "DB Error"
        )

        result = await middleware.validate_token("test-token")

        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_validate_token_verification_error(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation when token verification raises exception."""
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.side_effect = TokenError(
            "Token verification failed",
            details={"error": "Verify error"},
        )

        result = await middleware.validate_token("test-token")

        assert result.is_valid is False

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_validate_token_inactive(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation when token is inactive."""
        from src.core.auth.sso.models import TokenRecord

        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        inactive_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=False,  # Inactive
            created_at=frozen_time,
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        mock_token_repository.find_by_hash.return_value = inactive_token

        result = await middleware.validate_token("test-token")

        assert result.is_valid is False

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_validate_token_expired_session(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation when SSO session has expired."""
        from src.core.auth.sso.models import TokenRecord

        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        expired_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time - timedelta(hours=1),  # Expired
        )
        mock_token_repository.find_by_hash.return_value = expired_token

        result = await middleware.validate_token("test-token")

        assert result.is_valid is True
        assert result.is_authenticated is False
        assert result.user_id == "user123"
        assert result.token_id == "token-id"

        # Verify that auth status was updated
        mock_token_repository.update_auth_status.assert_awaited_once_with(
            "token-id", authenticated=False, expiry=None
        )

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_validate_token_valid_authenticated(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation with valid authenticated token."""
        from src.core.auth.sso.models import TokenRecord

        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        valid_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time + timedelta(hours=1),  # Not expired
        )
        mock_token_repository.find_by_hash.return_value = valid_token

        result = await middleware.validate_token("test-token")

        assert result.is_valid is True
        assert result.is_authenticated is True
        assert result.user_id == "user123"
        assert result.token_id == "token-id"

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_validate_token_valid_unauthenticated(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
    ) -> None:
        """Test validation with valid but unauthenticated token."""
        from src.core.auth.sso.models import TokenRecord

        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        unauthenticated_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=False,  # Not authenticated
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        mock_token_repository.find_by_hash.return_value = unauthenticated_token

        result = await middleware.validate_token("test-token")

        assert result.is_valid is True
        assert result.is_authenticated is False
        assert result.user_id == "user123"
        assert result.token_id == "token-id"

    # =========================================================================
    # Sandbox History Detection Tests
    # =========================================================================

    def test_detect_sandbox_history_delegates_to_handler(
        self,
        middleware: AuthMiddleware,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test that sandbox detection delegates to handler."""
        messages = [{"role": "user", "content": "Hello"}]
        mock_sandbox_handler.detect_sandbox_history.return_value = True

        result = middleware.detect_sandbox_history(messages)

        assert result is True
        mock_sandbox_handler.detect_sandbox_history.assert_called_once_with(messages)

    # =========================================================================
    # Request Processing Tests
    # =========================================================================

    @pytest.mark.asyncio
    async def test_call_no_token(
        self,
        middleware: AuthMiddleware,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with no token."""
        request = {"headers": {}}

        response = await middleware(request)

        assert response is not None
        mock_sandbox_handler.generate_login_banner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_call_invalid_token(
        self,
        middleware: AuthMiddleware,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with invalid token."""
        request = {"headers": {"Authorization": "Bearer invalid-token"}}
        mock_token_repository.get_all_token_hashes.return_value = []

        response = await middleware(request)

        assert response is not None
        mock_sandbox_handler.generate_login_banner.assert_awaited_once()

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_call_unauthenticated_token(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with unauthenticated token."""
        from src.core.auth.sso.models import TokenRecord

        request = {"headers": {"Authorization": "Bearer test-token"}}
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        unauthenticated_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=False,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=None,
            auth_expires_at=None,
        )
        mock_token_repository.find_by_hash.return_value = unauthenticated_token

        response = await middleware(request)

        assert response is not None
        mock_sandbox_handler.generate_login_banner.assert_awaited_once()

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_call_sandbox_history_detected(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing when sandbox history is detected."""
        from src.core.auth.sso.models import TokenRecord

        request = {
            "headers": {"Authorization": "Bearer test-token"},
            "messages": [{"role": "assistant", "content": "# Authentication Required"}],
        }
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        valid_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time + timedelta(hours=1),
        )
        mock_token_repository.find_by_hash.return_value = valid_token
        mock_sandbox_handler.detect_sandbox_history.return_value = True

        response = await middleware(request)

        assert response is not None
        mock_sandbox_handler.generate_login_banner.assert_awaited_once()

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_call_valid_authenticated_no_sandbox(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with valid authenticated token and no sandbox."""
        from src.core.auth.sso.models import TokenRecord

        request = {
            "headers": {"Authorization": "Bearer test-token"},
            "messages": [{"role": "user", "content": "Hello"}],
        }
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        valid_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time + timedelta(hours=1),
        )
        mock_token_repository.find_by_hash.return_value = valid_token
        mock_sandbox_handler.detect_sandbox_history.return_value = False

        response = await middleware(request)

        # Should return None to allow request to proceed
        assert response is None
        mock_sandbox_handler.generate_login_banner.assert_not_awaited()

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_call_empty_messages_list(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with empty messages list."""
        from src.core.auth.sso.models import TokenRecord

        request = {
            "headers": {"Authorization": "Bearer test-token"},
            "messages": [],
        }
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        valid_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time + timedelta(hours=1),
        )
        mock_token_repository.find_by_hash.return_value = valid_token
        mock_sandbox_handler.detect_sandbox_history.return_value = False

        response = await middleware(request)

        assert response is None

    @pytest.mark.asyncio
    @freeze_time("2024-01-01 12:00:00")
    async def test_call_missing_messages_key(
        self,
        middleware: AuthMiddleware,
        mock_token_service: MagicMock,
        mock_token_repository: MagicMock,
        mock_sandbox_handler: MagicMock,
    ) -> None:
        """Test request processing with missing messages key."""
        from src.core.auth.sso.models import TokenRecord

        request = {"headers": {"Authorization": "Bearer test-token"}}
        mock_token_repository.get_all_token_hashes.return_value = ["hash1"]
        mock_token_service.verify_token.return_value = True

        frozen_time = datetime.now(timezone.utc)
        valid_token = TokenRecord(
            id="token-id",
            token_hash="hash1",
            user_id="user123",
            user_email="user@example.com",
            provider="google",
            is_authenticated=True,
            is_active=True,
            created_at=frozen_time,
            last_authenticated_at=frozen_time,
            auth_expires_at=frozen_time + timedelta(hours=1),
        )
        mock_token_repository.find_by_hash.return_value = valid_token
        mock_sandbox_handler.detect_sandbox_history.return_value = False

        response = await middleware(request)

        assert response is None
        # Should pass empty list to detect_sandbox_history
        mock_sandbox_handler.detect_sandbox_history.assert_called_once_with([])
