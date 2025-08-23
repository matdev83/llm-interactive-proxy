# import json # F401: Removed

import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend
from src.core.common.exceptions import ServiceUnavailableError

# from starlette.responses import StreamingResponse # F401: Removed
from src.core.domain.chat import ChatMessage, ChatRequest

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(_: str, api_key: str) -> dict[str, str]:
    # Create a mock config dictionary for testing
    mock_config = {
        "app_site_url": "http://localhost:test",
        "app_x_title": "TestProxy",
    }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": mock_config["app_site_url"],
        "X-Title": mock_config["app_x_title"],
    }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        backend = OpenRouterBackend(client=client)
        # Call initialize with required arguments
        await backend.initialize(
            api_key="test_key",  # A dummy API key for initialization
            key_name="openrouter",
            openrouter_headers_provider=mock_get_openrouter_headers,
        )
        yield backend


@pytest.fixture
def sample_chat_request_data() -> ChatRequest:
    """Return a minimal chat request without optional fields set."""
    return ChatRequest(
        model="test-model", messages=[ChatMessage(role="user", content="Hello")]
    )


@pytest.fixture
def sample_processed_messages() -> list[ChatMessage]:
    return [ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
@pytest.mark.httpx_mock()
async def test_chat_completions_request_error(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: ChatRequest,
    sample_processed_messages: list[ChatMessage],
):
    httpx_mock.add_exception(httpx.ConnectError("Connection failed"))

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model="test-model",
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers,
            key_name="test_key",
            api_key="FAKE_KEY",
        )

    # Check that the ServiceUnavailableError contains the error information
    assert "Connection failed" in str(exc_info.value)
    assert "Could not connect to backend" in str(exc_info.value)
