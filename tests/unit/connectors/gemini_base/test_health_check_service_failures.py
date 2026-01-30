"""
Unit tests for health check service failure paths and edge cases.

Tests verify error handling, retries, and recovery scenarios for
GeminiHealthCheckService. Covers Requirements 4.1, 4.2, 4.3.
"""

from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from src.connectors.gemini_base.endpoints import StandardCodeAssistEndpoint
from src.connectors.gemini_base.health_check_service import GeminiHealthCheckService
from src.connectors.gemini_base.models import GeminiOAuthCredentials
from src.core.common.exceptions import AuthenticationError, BackendError


@pytest.fixture
def mock_credential_coordinator() -> Mock:
    """Create a mock ICredentialCoordinator."""
    coordinator = Mock()
    coordinator.refresh_if_needed = AsyncMock(return_value=True)
    credentials = GeminiOAuthCredentials(
        access_token="test_access_token",
        refresh_token="test_refresh_token",
        expiry_date=9999999999999,
        project_id="test-project",
    )
    coordinator.credentials = credentials
    return coordinator


@pytest.fixture
def mock_endpoint_config() -> StandardCodeAssistEndpoint:
    """Create a mock IEndpointConfig."""
    return StandardCodeAssistEndpoint()


@pytest.fixture
def mock_http_client() -> Mock:
    """Create a mock httpx.AsyncClient."""
    return Mock(spec=httpx.AsyncClient)


@pytest.fixture
def health_check_service(
    mock_credential_coordinator: Mock,
    mock_endpoint_config: StandardCodeAssistEndpoint,
    mock_http_client: Mock,
) -> GeminiHealthCheckService:
    """Create a GeminiHealthCheckService instance."""
    return GeminiHealthCheckService(
        credential_coordinator=mock_credential_coordinator,
        endpoint_config=mock_endpoint_config,
        http_client=mock_http_client,
        backend_name="test-backend",
    )


class TestHealthCheckRecovery:
    """Test health check recovery scenarios."""

    @pytest.mark.asyncio
    async def test_health_check_recovers_after_initial_failure(
        self,
        mock_credential_coordinator: Mock,
        mock_endpoint_config: StandardCodeAssistEndpoint,
        mock_http_client: Mock,
    ) -> None:
        """Verify health check recovery after initial failure."""
        # Create two services to simulate recovery
        service1 = GeminiHealthCheckService(
            credential_coordinator=mock_credential_coordinator,
            endpoint_config=mock_endpoint_config,
            http_client=mock_http_client,
            backend_name="test-backend",
        )

        # First call fails
        mock_response = Mock()
        mock_response.status_code = 500
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await service1.ensure_healthy()
        assert service1._health_checked is True  # Still marked as checked

        # Second service with successful check
        service2 = GeminiHealthCheckService(
            credential_coordinator=mock_credential_coordinator,
            endpoint_config=mock_endpoint_config,
            http_client=mock_http_client,
            backend_name="test-backend",
        )

        # Now it succeeds
        mock_response.status_code = 200
        await service2.ensure_healthy()

        assert service2._health_checked is True

    @pytest.mark.asyncio
    async def test_endpoint_fail(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify behavior when loadCodeAssist fails."""
        # Endpoint returns 500
        fail_response = Mock()
        fail_response.status_code = 500
        mock_http_client.post = AsyncMock(return_value=fail_response)

        result = await health_check_service._perform_health_check()

        assert result is False
        mock_http_client.post.assert_called_once()  # loadCodeAssist


class TestNetworkErrorHandling:
    """Test network error handling scenarios."""

    @pytest.mark.asyncio
    async def test_connection_refused_handled(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify connection refused error is handled gracefully."""
        mock_http_client.post = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_dns_resolution_failure_handled(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify DNS resolution failure is handled gracefully."""
        mock_http_client.post = AsyncMock(
            side_effect=httpx.RequestError("DNS resolution failed")
        )

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_ssl_error_handled(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify SSL error is handled gracefully."""
        mock_http_client.post = AsyncMock(
            side_effect=httpx.RequestError("SSL certificate verify failed")
        )

        result = await health_check_service._perform_health_check()

        assert result is False


class TestCredentialInteraction:
    """Test credential interaction during health checks."""

    @pytest.mark.asyncio
    async def test_refresh_called_before_health_check(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_credential_coordinator: Mock,
        mock_http_client: Mock,
    ) -> None:
        """Verify refresh_if_needed is called before performing health check."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_http_client.post = AsyncMock(return_value=mock_response)

        await health_check_service.ensure_healthy()

        mock_credential_coordinator.refresh_if_needed.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_skipped_when_credentials_removed(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_credential_coordinator: Mock,
    ) -> None:
        """Verify health check returns False when credentials become None."""
        mock_credential_coordinator.credentials = None

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_ensure_healthy_raises_on_refresh_failure(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_credential_coordinator: Mock,
    ) -> None:
        """Verify BackendError raised when refresh fails."""
        mock_credential_coordinator.refresh_if_needed = AsyncMock(return_value=False)

        with pytest.raises(BackendError) as exc_info:
            await health_check_service.ensure_healthy()

        assert "Failed to refresh OAuth token" in exc_info.value.message

    @pytest.mark.asyncio
    async def test_authentication_error_during_refresh_propagated(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_credential_coordinator: Mock,
    ) -> None:
        """Verify AuthenticationError from refresh is propagated."""
        mock_credential_coordinator.refresh_if_needed = AsyncMock(
            side_effect=AuthenticationError("Token expired")
        )

        with pytest.raises(AuthenticationError) as exc_info:
            await health_check_service.ensure_healthy()

        assert "Token expired" in exc_info.value.message


class TestHTTPResponseCodes:
    """Test HTTP response code handling."""

    @pytest.mark.asyncio
    async def test_401_response_returns_false(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify 401 response is handled as failure."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_403_response_returns_false(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify 403 response is handled as failure."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_429_response_returns_false(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify 429 rate limit response is handled as failure."""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await health_check_service._perform_health_check()

        assert result is False

    @pytest.mark.asyncio
    async def test_503_response_returns_false(
        self,
        health_check_service: GeminiHealthCheckService,
        mock_http_client: Mock,
    ) -> None:
        """Verify 503 service unavailable is handled as failure."""
        mock_response = Mock()
        mock_response.status_code = 503
        mock_http_client.post = AsyncMock(return_value=mock_response)

        result = await health_check_service._perform_health_check()

        assert result is False
