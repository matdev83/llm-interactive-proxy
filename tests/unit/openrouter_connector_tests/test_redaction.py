import json
import pytest
import httpx
import pytest_asyncio
from pytest_httpx import HTTPXMock

import src.models as models
from src.connectors.openrouter import OpenRouterBackend
from src.security import APIKeyRedactor

TEST_OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"

def mock_get_openrouter_headers(key_name: str, api_key: str):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:test",
        "X-Title": "TestProxy",
    }

@pytest_asyncio.fixture(name="openrouter_backend")
async def openrouter_backend_fixture():
    async with httpx.AsyncClient() as client:
        yield OpenRouterBackend(client=client)

@pytest.fixture
def sample_request() -> models.ChatCompletionRequest:
    """Return a minimal chat request without optional fields set."""
    return models.ChatCompletionRequest(
        model="m",
        messages=[models.ChatMessage(role="user", content="leak SECRET")],
    )

@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_prompt_redaction(openrouter_backend: OpenRouterBackend, httpx_mock: HTTPXMock, sample_request: models.ChatCompletionRequest):
    httpx_mock.add_response(status_code=200, json={"choices": [{"message": {"content": "ok"}}]})
    redactor = APIKeyRedactor(["SECRET"])
    await openrouter_backend.chat_completions(
        request_data=sample_request,
        processed_messages=sample_request.messages,
        effective_model="model",
        openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
        openrouter_headers_provider=mock_get_openrouter_headers,
        key_name="OPENROUTER_API_KEY_1",
        api_key="FAKE",
        prompt_redactor=redactor,
    )
    request = httpx_mock.get_request()
    assert request is not None # Add assertion to ensure request is not None
    payload = json.loads(request.content)
    assert payload["messages"][0]["content"] == "leak (API_KEY_HAS_BEEN_REDACTED)"
