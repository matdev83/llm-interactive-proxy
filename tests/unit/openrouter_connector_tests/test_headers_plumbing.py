import httpx
import pytest
import pytest_asyncio
import src.models as models
from pytest_httpx import HTTPXMock
from src.connectors.openrouter import OpenRouterBackend


def mock_headers_provider(key_name: str, api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        backend = OpenRouterBackend(client=client)
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
    request_data = models.ChatCompletionRequest(
        model="openai/gpt-3.5-turbo",
        messages=[models.ChatMessage(role="user", content="Hello")],
        temperature=None,
        top_p=None,
        n=None,
        stream=False,
        stop=None,
        max_tokens=None,
        presence_penalty=None,
        frequency_penalty=None,
        logit_bias=None,
        user=None,
        tool_choice=None,
        reasoning_effort=None,
        reasoning=None,
        thinking_budget=None,
        generation_config=None,
        extra_params=None,
    )

    httpx_mock.add_response(json={"id": "ok"}, status_code=200)

    # Act
    await openrouter_backend.chat_completions(
        request_data=request_data,
        processed_messages=[models.ChatMessage(role="user", content="Hello")],
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
