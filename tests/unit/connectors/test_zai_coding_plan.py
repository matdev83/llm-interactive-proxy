import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from httpx import AsyncClient
from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.translation_service import TranslationService


@pytest.fixture
def mock_client():
    return AsyncMock(spec=AsyncClient)


@pytest.fixture
def mock_config():
    return MagicMock(spec=AppConfig)


@pytest.fixture
def mock_translation_service():
    return MagicMock(spec=TranslationService)


@pytest.fixture
async def backend(mock_client, mock_config, mock_translation_service):
    with patch.dict(os.environ, {"ZAI_API_KEY": "test-key"}):
        backend = ZaiCodingPlanBackend(
            client=mock_client,
            config=mock_config,
            translation_service=mock_translation_service,
        )
        await backend.initialize(api_key="test-key")
        return backend


async def test_backend_initialization(backend: ZaiCodingPlanBackend):
    assert backend.backend_type == "zai-coding-plan"
    assert backend.anthropic_api_base_url == "https://api.z.ai/api/anthropic/v1"
    assert backend.api_key == "test-key"


async def test_get_available_models(backend: ZaiCodingPlanBackend):
    models = await backend.get_available_models_async()
    assert models == ["claude-sonnet-4-20250514"]


async def test_list_models(backend: ZaiCodingPlanBackend):
    models = await backend.list_models()
    assert len(models) == 1
    assert models[0]["id"] == "claude-sonnet-4-20250514"


async def test_chat_completions_model_rewrite(
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    # Mock the HTTP client response
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "test",
        "model": "claude-sonnet-4-20250514",
    }
    mock_response.headers = {"content-type": "application/json"}
    mock_response.status_code = 200

    backend.client.post = AsyncMock(return_value=mock_response)

    mock_translation_service.to_domain_request.return_value = ChatRequest(
        model="some-other-model",
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )

    processed_messages = [ChatMessage(role="user", content="hello")]
    result = await backend.chat_completions(
        ChatRequest(
            model="some-other-model",
            messages=processed_messages,
        ),
        processed_messages,
        "some-other-model",
    )

    # Verify the client was called with the correct payload
    backend.client.post.assert_called_once()
    call_args = backend.client.post.call_args
    payload = call_args[1]["json"]
    assert payload["model"] == "claude-sonnet-4-20250514"

    # Verify the response model is rewritten back to original
    assert result.content["model"] == "some-other-model"
