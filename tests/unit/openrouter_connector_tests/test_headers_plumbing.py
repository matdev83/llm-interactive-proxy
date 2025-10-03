import httpx
import pytest
import pytest_asyncio
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend
from src.core.domain.chat import ChatMessage, ChatRequest


def mock_headers_provider(_: str, api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


class DummyIdentity:
    """Simple identity stub for tests."""

    def get_resolved_headers(self, incoming_headers):  # type: ignore[no-untyped-def]
        return {
            "X-Title": "custom-app",
            "HTTP-Referer": "https://example.test",
        }


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        from src.core.config.app_config import AppConfig

        config = AppConfig()
        backend = OpenRouterBackend(client=client, config=config)
        # Call initialize with required arguments
        await backend.initialize(
            api_key="test_key",  # A dummy API key for initialization
            key_name="openrouter",
            openrouter_headers_provider=mock_headers_provider,
        )
        yield backend


@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_headers_plumbing(
    openrouter_backend: OpenRouterBackend, httpx_mock: HTTPXMock
):
    # Arrange
    request_data = ChatRequest(
        model="openai/gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    httpx_mock.add_response(json={"id": "ok"}, status_code=200)

    # Act
    await openrouter_backend.chat_completions(
        request_data=request_data,
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="openai/gpt-3.5-turbo",
        openrouter_api_base_url="https://openrouter.ai/api/v1",
        openrouter_headers_provider=mock_headers_provider,
        key_name="test",
        api_key="TEST-HEADER",
    )

    # Assert
    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers.get("Authorization") == "Bearer TEST-HEADER"


@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_identity_headers_are_preserved(
    openrouter_backend: OpenRouterBackend, httpx_mock: HTTPXMock
):
    request_data = ChatRequest(
        model="openai/gpt-3.5-turbo",
        messages=[ChatMessage(role="user", content="Hello")],
        stream=False,
    )

    httpx_mock.add_response(json={"id": "ok"}, status_code=200)

    await openrouter_backend.chat_completions(
        request_data=request_data,
        processed_messages=[ChatMessage(role="user", content="Hello")],
        effective_model="openai/gpt-3.5-turbo",
        openrouter_api_base_url="https://openrouter.ai/api/v1",
        openrouter_headers_provider=mock_headers_provider,
        key_name="test",
        api_key="TEST-HEADER",
        identity=DummyIdentity(),
    )

    req = httpx_mock.get_request()
    assert req is not None
    assert req.headers.get("Authorization") == "Bearer TEST-HEADER"
    assert req.headers.get("X-Title") == "custom-app"
    assert req.headers.get("HTTP-Referer") == "https://example.test"
