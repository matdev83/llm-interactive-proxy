# import json # F401: Removed
from typing import Dict, List  # Removed Any, Callable, Union

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pytest_httpx import HTTPXMock

# from starlette.responses import StreamingResponse # F401: Removed
import src.models as models
from src.connectors.openrouter import OpenRouterBackend

# Default OpenRouter settings for tests
TEST_OPENROUTER_API_BASE_URL = (
    "https://openrouter.ai/api/v1"  # Real one for realistic requests
)


def mock_get_openrouter_headers(key_name: str, api_key: str) -> Dict[str, str]:
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
def sample_chat_request_data() -> models.ChatCompletionRequest:
    """Return a minimal chat request without optional fields set."""
    return models.ChatCompletionRequest(
        model="test-model",
        messages=[models.ChatMessage(role="user", content="Hello")],
    )


@pytest.fixture
def sample_processed_messages() -> List[models.ChatMessage]:
    return [models.ChatMessage(role="user", content="Hello")]


@pytest.mark.asyncio
@pytest.mark.usefixtures("openrouter_backend")
@pytest.mark.httpx_mock()
async def test_chat_completions_http_error_non_streaming(
    openrouter_backend: OpenRouterBackend,
    httpx_mock: HTTPXMock,
    sample_chat_request_data: models.ChatCompletionRequest,
    sample_processed_messages: List[models.ChatMessage],
):
    sample_chat_request_data.stream = False
    error_payload = {
        "error": {"message": "Insufficient credits", "type": "billing_error"}
    }

    httpx_mock.add_response(
        url=f"{TEST_OPENROUTER_API_BASE_URL}/chat/completions",
        method="POST",
        json=error_payload,
        status_code=402,  # Payment Required
    )

    with pytest.raises(HTTPException) as exc_info:
        await openrouter_backend.chat_completions(
            request_data=sample_chat_request_data,
            processed_messages=sample_processed_messages,
            effective_model="test-model",
            openrouter_api_base_url=TEST_OPENROUTER_API_BASE_URL,
            openrouter_headers_provider=mock_get_openrouter_headers,
            key_name="OPENROUTER_API_KEY_1",
            api_key="FAKE_KEY",
        )

    assert exc_info.value.status_code == 402
    assert exc_info.value.detail == error_payload
