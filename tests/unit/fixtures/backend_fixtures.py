"""Test fixtures for backend service tests.

This module provides fixtures for setting up backend service tests.
"""

from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from src.core.domain.configuration.backend_config import (
    BackendConfiguration,
    IBackendConfig,
)
from src.core.services.backend_service import BackendService


class MockBackend:
    """Mock backend for testing."""

    def __init__(self, client: httpx.AsyncClient, status_code: int = 200) -> None:
        """Initialize the mock backend.

        Args:
            client: The httpx client
            status_code: The status code to return
        """
        self.client = client
        self.status_code = status_code
        self.chat_completions = AsyncMock()
        self.chat_completions_stream = AsyncMock()

    async def get_available_models(self) -> list[str]:
        """Get available models.

        Returns:
            List[str]: A list of available models
        """
        return [
            "gpt-4-turbo",
            "my/model-v1",
            "gpt-4",
            "claude-2",
            "test-model",
            "another-model",
            "command-only-model",
            "multi",
            "foo",
        ]


@pytest.fixture
def mock_backend_factory() -> Mock:
    """Create a mock backend factory.

    Returns:
        Mock: A mock backend factory
    """
    factory = Mock()
    factory.create_backend = Mock()
    return factory


@pytest.fixture
def mock_backend(httpx_client: httpx.AsyncClient) -> MockBackend:
    """Create a mock backend.

    Args:
        httpx_client: The httpx client

    Returns:
        MockBackend: A mock backend
    """
    return MockBackend(httpx_client)


@pytest.fixture
def httpx_client() -> httpx.AsyncClient:
    """Create an httpx client.

    Returns:
        httpx.AsyncClient: An httpx client
    """
    return httpx.AsyncClient()


@pytest.fixture
def mock_rate_limiter() -> Mock:
    """Create a mock rate limiter.

    Returns:
        Mock: A mock rate limiter
    """
    rate_limiter = Mock()
    rate_limiter.wait_if_needed = AsyncMock(return_value=None)
    return rate_limiter


@pytest.fixture
def mock_config() -> Mock:
    """Create a mock config.

    Returns:
        Mock: A mock config
    """
    config = Mock()
    return config


@pytest.fixture
def mock_session_service() -> Mock:
    """Create a mock session service.

    Returns:
        Mock: A mock session service
    """
    session_service = Mock()
    return session_service


@pytest.fixture
def backend_service(
    mock_backend_factory: Mock,
    mock_backend: Mock,
    mock_rate_limiter: Mock,
    mock_config: Mock,
    mock_session_service: Mock,
) -> BackendService:
    """Create a backend service.

    Args:
        mock_backend_factory: A mock backend factory
        mock_backend: A mock backend
        mock_rate_limiter: A mock rate limiter
        mock_config: A mock config
        mock_session_service: A mock session service

    Returns:
        BackendService: A backend service
    """
    # Configure the mock factory to return our mock backend
    mock_backend_factory.create_backend.return_value = mock_backend

    # Create the backend service with all required parameters
    service = BackendService(
        factory=mock_backend_factory,
        rate_limiter=mock_rate_limiter,
        config=mock_config,
        session_service=mock_session_service,
    )
    return service


@pytest.fixture
def backend_config(
    backend_type: str = "openrouter", model: str = "test-model"
) -> IBackendConfig:
    """Create a backend configuration.

    Args:
        backend_type: The backend type
        model: The model name

    Returns:
        BackendConfiguration: A backend configuration
    """
    config: IBackendConfig = BackendConfiguration()
    config = config.with_backend(backend_type)
    config = config.with_model(model)
    return config


@pytest.fixture
def session_with_backend_config(
    test_session: Any, backend_config: IBackendConfig
) -> Any:
    """Create a session with a backend configuration.

    Args:
        test_session: A test session
        backend_config: A backend configuration

    Returns:
        Session: A session with the backend configuration
    """
    test_session.state = test_session.state.with_backend_config(backend_config)
    return test_session
