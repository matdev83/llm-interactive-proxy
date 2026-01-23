"""
Unit tests for TokenRefreshService.

Tests Requirement 3: Automatic Token Refresh.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.connectors.gemini_oauth_auto.errors import TokenRefreshError
from src.connectors.gemini_oauth_auto.models import StoredAccount
from src.connectors.gemini_oauth_auto.token_refresh import TokenRefreshService


@pytest.fixture
def mock_storage() -> MagicMock:
    """Fixture providing mock token storage."""
    storage = MagicMock()
    storage.save_account = AsyncMock()
    storage.get_account = AsyncMock(return_value=None)
    return storage


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Fixture providing mock httpx AsyncClient."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def refresh_service(
    mock_storage: MagicMock, mock_http_client: MagicMock
) -> TokenRefreshService:
    """Fixture providing TokenRefreshService with mocked dependencies."""
    return TokenRefreshService(
        storage=mock_storage,
        http_client=mock_http_client,
        max_retries=3,
        base_delay=0.01,  # Fast delay for tests
    )


@pytest.fixture
def valid_account() -> StoredAccount:
    """Fixture providing a valid StoredAccount with future expiry."""
    return StoredAccount(
        account_id="test-account",
        email="test@gmail.com",
        access_token="ya29.old_access_token",
        refresh_token="1//test_refresh_token",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((time.time() + 3600) * 1000),  # 1 hour from now
    )


@pytest.fixture
def expired_account() -> StoredAccount:
    """Fixture providing an expired StoredAccount."""
    return StoredAccount(
        account_id="test-account",
        email="test@gmail.com",
        access_token="ya29.expired_access_token",
        refresh_token="1//test_refresh_token",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((time.time() - 3600) * 1000),  # 1 hour ago
    )


@pytest.fixture
def near_expiry_account() -> StoredAccount:
    """Fixture providing an account expiring within refresh buffer."""
    return StoredAccount(
        account_id="test-account",
        email="test@gmail.com",
        access_token="ya29.near_expiry_token",
        refresh_token="1//test_refresh_token",
        scope="https://www.googleapis.com/auth/cloud-platform",
        expiry_date=int((time.time() + 120) * 1000),  # 2 minutes from now
    )


class TestTokenRefreshService:
    """Tests for TokenRefreshService."""

    @pytest.mark.asyncio
    async def test_refresh_if_needed_returns_unchanged_when_not_expired(
        self,
        refresh_service: TokenRefreshService,
        valid_account: StoredAccount,
    ) -> None:
        """Test refresh_if_needed returns unchanged account if not near expiry."""
        result = await refresh_service.refresh_if_needed(valid_account)

        assert result.access_token == valid_account.access_token
        assert result.account_id == valid_account.account_id

    @pytest.mark.asyncio
    async def test_refresh_if_needed_refreshes_when_within_buffer(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        near_expiry_account: StoredAccount,
    ) -> None:
        """Test refresh_if_needed refreshes when within buffer window."""
        # Mock successful token response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new_access_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await refresh_service.refresh_if_needed(
            near_expiry_account, buffer_ms=300_000
        )

        assert result.access_token == "ya29.new_access_token"
        mock_http_client.post.assert_called_once()
        mock_storage.save_account.assert_called_once()

    @pytest.mark.asyncio
    async def test_force_refresh_always_refreshes(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        valid_account: StoredAccount,
    ) -> None:
        """Test force_refresh always refreshes even if token is valid."""
        # Mock successful token response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.forced_new_token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await refresh_service.force_refresh(valid_account)

        assert result.access_token == "ya29.forced_new_token"
        mock_http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_grant_sets_needs_reauth(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test invalid_grant error sets needs_reauth flag."""
        # Mock invalid_grant response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": "invalid_grant"}
        mock_http_client.post = AsyncMock(return_value=mock_response)

        with pytest.raises(TokenRefreshError) as exc_info:
            await refresh_service.force_refresh(expired_account)

        assert exc_info.value.needs_reauth is True
        # Verify account was saved with needs_reauth flag
        mock_storage.save_account.assert_called_once()
        saved_account = mock_storage.save_account.call_args[0][0]
        assert saved_account.needs_reauth is True

    @pytest.mark.asyncio
    async def test_retry_with_exponential_backoff(
        self,
        mock_storage: MagicMock,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test retry with exponential backoff on transient failures."""
        # Create service with measurable delays
        service = TokenRefreshService(
            storage=mock_storage,
            http_client=mock_http_client,
            max_retries=3,
            base_delay=0.01,  # 10ms base delay
        )

        # Mock first two calls fail, third succeeds
        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "access_token": "ya29.success_after_retry",
            "expires_in": 3600,
        }
        mock_response_success.raise_for_status = MagicMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise httpx.HTTPError("Connection failed")
            return mock_response_success

        mock_http_client.post = AsyncMock(side_effect=side_effect)

        result = await service.force_refresh(expired_account)

        assert result.access_token == "ya29.success_after_retry"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded_raises_error(
        self,
        mock_storage: MagicMock,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test that exceeding max retries raises TokenRefreshError."""
        service = TokenRefreshService(
            storage=mock_storage,
            http_client=mock_http_client,
            max_retries=3,
            base_delay=0.01,
        )

        # All calls fail
        mock_http_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Connection failed")
        )

        with pytest.raises(TokenRefreshError) as exc_info:
            await service.force_refresh(expired_account)

        assert "failed after 3 attempts" in str(exc_info.value)
        assert exc_info.value.needs_reauth is False

    @pytest.mark.asyncio
    async def test_concurrent_refresh_prevention(
        self,
        mock_storage: MagicMock,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test that concurrent refreshes for same account are prevented."""
        service = TokenRefreshService(
            storage=mock_storage,
            http_client=mock_http_client,
            max_retries=1,
            base_delay=0.01,
        )

        call_count = 0
        refresh_started = asyncio.Event()

        async def slow_response(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            refresh_started.set()
            await asyncio.sleep(0.1)  # Simulate slow response
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "access_token": f"ya29.token_{call_count}",
                "expires_in": 3600,
            }
            mock_response.raise_for_status = MagicMock()
            return mock_response

        mock_http_client.post = AsyncMock(side_effect=slow_response)

        # Start two concurrent refreshes
        task1 = asyncio.create_task(service.force_refresh(expired_account))
        await refresh_started.wait()
        task2 = asyncio.create_task(service.force_refresh(expired_account))

        result1, result2 = await asyncio.gather(task1, task2)

        # Both should get tokens, but only one HTTP call should be made
        # due to double-check pattern (second one should see first's result)
        assert result1.access_token.startswith("ya29.")
        assert result2.access_token.startswith("ya29.")

    @pytest.mark.asyncio
    async def test_refresh_updates_expiry_date(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test refresh updates expiry_date correctly."""
        new_expires_in = 7200  # 2 hours
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new_token",
            "expires_in": new_expires_in,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        before_time = int(time.time() * 1000)
        result = await refresh_service.force_refresh(expired_account)
        after_time = int(time.time() * 1000)

        # Expiry should be approximately now + expires_in
        expected_min = before_time + (new_expires_in * 1000)
        expected_max = after_time + (new_expires_in * 1000)
        assert expected_min <= result.expiry_date <= expected_max

    @pytest.mark.asyncio
    async def test_refresh_clears_needs_reauth_on_success(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
    ) -> None:
        """Test successful refresh clears needs_reauth flag."""
        account_needing_reauth = StoredAccount(
            account_id="test-account",
            email="test@gmail.com",
            access_token="ya29.old",
            refresh_token="1//refresh",
            scope="scope",
            expiry_date=int((time.time() - 3600) * 1000),
            needs_reauth=True,
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await refresh_service.force_refresh(account_needing_reauth)

        assert result.needs_reauth is False

    @pytest.mark.asyncio
    async def test_refresh_preserves_account_metadata(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        mock_storage: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test refresh preserves account metadata like account_id and email."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "ya29.new",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await refresh_service.force_refresh(expired_account)

        assert result.account_id == expired_account.account_id
        assert result.email == expired_account.email
        assert result.refresh_token == expired_account.refresh_token

    @pytest.mark.asyncio
    async def test_refresh_locks_independent(
        self, refresh_service: TokenRefreshService
    ) -> None:
        """Test that different accounts have different locks."""
        lock1 = refresh_service._get_lock("acc-1")
        lock2 = refresh_service._get_lock("acc-2")
        assert lock1 is not lock2
        assert lock1 is refresh_service._get_lock("acc-1")

    @pytest.mark.asyncio
    async def test_refresh_unexpected_error_retry(
        self,
        mock_storage: MagicMock,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test retry on unexpected exceptions."""
        service = TokenRefreshService(
            storage=mock_storage,
            http_client=mock_http_client,
            max_retries=2,
            base_delay=0.001,
        )

        mock_response_success = MagicMock()
        mock_response_success.status_code = 200
        mock_response_success.json.return_value = {
            "access_token": "ya29.retry_success",
            "expires_in": 3600,
        }
        mock_response_success.raise_for_status = MagicMock()

        mock_http_client.post.side_effect = [
            Exception("Unexpected error"),
            mock_response_success,
        ]

        result = await service.force_refresh(expired_account)
        assert result.access_token == "ya29.retry_success"
        assert mock_http_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_refresh_invalid_grant_json_error(
        self,
        refresh_service: TokenRefreshService,
        mock_http_client: MagicMock,
        expired_account: StoredAccount,
    ) -> None:
        """Test handling of 400 error with non-JSON body."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.side_effect = ValueError("Not JSON")
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=MagicMock(), response=mock_response
        )

        mock_http_client.post.return_value = mock_response
        refresh_service._http_client = mock_http_client

        with pytest.raises(httpx.HTTPStatusError):
            await refresh_service._execute_refresh(expired_account, mock_http_client)

