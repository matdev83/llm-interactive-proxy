"""Tests for the HTTPHealthChecker class."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.core.domain.configuration.health_check_config import HttpCheckConfig
from src.core.domain.events.health_events import HttpCheckFailed, HttpCheckSucceeded
from src.core.services.event_bus import EventBus
from src.core.services.health.endpoint_registry import EndpointRegistry
from src.core.services.health.http_checker import HTTPHealthChecker


class TestHTTPHealthChecker:
    """Tests for HTTPHealthChecker."""

    @pytest.fixture
    def event_bus(self) -> EventBus:
        """Create event bus for testing."""
        return EventBus()

    @pytest.fixture
    def registry(self) -> EndpointRegistry:
        """Create endpoint registry for testing."""
        return EndpointRegistry()

    @pytest.fixture
    def config(self) -> HttpCheckConfig:
        """Create HTTP check config for testing."""
        return HttpCheckConfig(
            enabled=True,
            timeout_seconds=5,
            method="HEAD",
            accept_any_response=True,
        )

    @pytest.fixture
    def checker(
        self,
        event_bus: EventBus,
        registry: EndpointRegistry,
        config: HttpCheckConfig,
    ) -> HTTPHealthChecker:
        """Create HTTP checker for testing."""
        return HTTPHealthChecker(
            event_bus=event_bus,
            endpoint_registry=registry,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_check_endpoint_success(
        self,
        checker: HTTPHealthChecker,
        event_bus: EventBus,
    ) -> None:
        """Test successful HTTP check emits success event."""
        received: list[HttpCheckSucceeded] = []

        async def capture_event(event: HttpCheckSucceeded) -> None:
            received.append(event)

        event_bus.subscribe(HttpCheckSucceeded, capture_event)

        # Create a mock client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)

        checker._client = mock_client

        await checker.check_endpoint("https://api.openai.com/v1")

        assert len(received) == 1
        assert received[0].api_url == "https://api.openai.com/v1"
        assert received[0].status_code == 200

    @pytest.mark.asyncio
    async def test_check_endpoint_timeout(
        self,
        checker: HTTPHealthChecker,
        event_bus: EventBus,
    ) -> None:
        """Test timeout emits failure event."""
        received: list[HttpCheckFailed] = []

        async def capture_event(event: HttpCheckFailed) -> None:
            received.append(event)

        event_bus.subscribe(HttpCheckFailed, capture_event)

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        checker._client = mock_client

        await checker.check_endpoint("https://api.openai.com/v1")

        assert len(received) == 1
        assert "Timeout" in received[0].error

    @pytest.mark.asyncio
    async def test_check_endpoint_connection_error(
        self,
        checker: HTTPHealthChecker,
        event_bus: EventBus,
    ) -> None:
        """Test connection error emits failure event."""
        received: list[HttpCheckFailed] = []

        async def capture_event(event: HttpCheckFailed) -> None:
            received.append(event)

        event_bus.subscribe(HttpCheckFailed, capture_event)

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(
            side_effect=httpx.ConnectError("connection refused")
        )

        checker._client = mock_client

        await checker.check_endpoint("https://api.openai.com/v1")

        assert len(received) == 1
        assert "Connection error" in received[0].error

    @pytest.mark.asyncio
    async def test_accept_any_response_4xx(
        self,
        checker: HTTPHealthChecker,
        event_bus: EventBus,
    ) -> None:
        """Test that 4xx response is accepted when accept_any_response is True."""
        received_success: list[HttpCheckSucceeded] = []
        received_failure: list[HttpCheckFailed] = []

        async def capture_success(event: HttpCheckSucceeded) -> None:
            received_success.append(event)

        async def capture_failure(event: HttpCheckFailed) -> None:
            received_failure.append(event)

        event_bus.subscribe(HttpCheckSucceeded, capture_success)
        event_bus.subscribe(HttpCheckFailed, capture_failure)

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.is_success = False

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)

        checker._client = mock_client

        await checker.check_endpoint("https://api.openai.com/v1")

        # With accept_any_response=True, 404 is still a success
        assert len(received_success) == 1
        assert len(received_failure) == 0
        assert received_success[0].status_code == 404

    @pytest.mark.asyncio
    async def test_reject_non_success_response(
        self,
        event_bus: EventBus,
        registry: EndpointRegistry,
    ) -> None:
        """Test that non-success responses are rejected when accept_any_response is False."""
        config = HttpCheckConfig(
            enabled=True,
            timeout_seconds=5,
            accept_any_response=False,
        )
        checker = HTTPHealthChecker(
            event_bus=event_bus,
            endpoint_registry=registry,
            config=config,
        )

        received_failure: list[HttpCheckFailed] = []

        async def capture_failure(event: HttpCheckFailed) -> None:
            received_failure.append(event)

        event_bus.subscribe(HttpCheckFailed, capture_failure)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.is_success = False

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)

        checker._client = mock_client

        await checker.check_endpoint("https://api.openai.com/v1")

        assert len(received_failure) == 1
        assert "HTTP 500" in received_failure[0].error

    @pytest.mark.asyncio
    async def test_disabled_checker_does_nothing(
        self,
        event_bus: EventBus,
        registry: EndpointRegistry,
    ) -> None:
        """Test that disabled checker doesn't make requests."""
        config = HttpCheckConfig(enabled=False)
        checker = HTTPHealthChecker(
            event_bus=event_bus,
            endpoint_registry=registry,
            config=config,
        )

        received: list[HttpCheckSucceeded | HttpCheckFailed] = []

        async def capture_event(event: HttpCheckSucceeded | HttpCheckFailed) -> None:
            received.append(event)

        event_bus.subscribe(HttpCheckSucceeded, capture_event)
        event_bus.subscribe(HttpCheckFailed, capture_event)

        await checker.check_endpoint("https://api.openai.com/v1")

        # No events should be emitted
        assert len(received) == 0

    def test_build_probe_url_no_path(
        self,
        checker: HTTPHealthChecker,
    ) -> None:
        """Test probe URL building without custom path."""
        url = checker._build_probe_url("https://api.openai.com/v1/")
        assert url == "https://api.openai.com/v1"

    def test_build_probe_url_with_path(
        self,
        event_bus: EventBus,
        registry: EndpointRegistry,
    ) -> None:
        """Test probe URL building with custom path."""
        config = HttpCheckConfig(path="/health")
        checker = HTTPHealthChecker(
            event_bus=event_bus,
            endpoint_registry=registry,
            config=config,
        )

        url = checker._build_probe_url("https://api.openai.com/v1")
        assert url == "https://api.openai.com/v1/health"

    @pytest.mark.asyncio
    async def test_check_all_endpoints(
        self,
        checker: HTTPHealthChecker,
        registry: EndpointRegistry,
        event_bus: EventBus,
    ) -> None:
        """Test checking all registered endpoints."""
        # Register endpoints
        registry.register_backend("openai.1", "https://api.openai.com/v1")
        registry.register_backend("anthropic.1", "https://api.anthropic.com")

        received: list[HttpCheckSucceeded] = []

        async def capture_event(event: HttpCheckSucceeded) -> None:
            received.append(event)

        event_bus.subscribe(HttpCheckSucceeded, capture_event)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)

        checker._client = mock_client

        await checker.check_all_endpoints()

        # Should have checked both endpoints
        assert len(received) == 2
