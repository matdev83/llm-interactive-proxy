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


@patch(
    "src.connectors.zai_coding_plan.ZaiCodingPlanBackend._handle_non_streaming_response"
)
async def test_chat_completions_model_rewrite(
    mock_handle_response: MagicMock,
    backend: ZaiCodingPlanBackend,
    mock_translation_service: MagicMock,
):
    mock_translation_service.to_domain_request.return_value = ChatRequest(
        model="some-other-model",
        messages=[{"role": "user", "content": "hello"}],
        stream=False,
    )
    mock_handle_response.return_value = "response"

    processed_messages = [ChatMessage(role="user", content="hello")]
    await backend.chat_completions(
        ChatRequest(
            model="some-other-model",
            messages=processed_messages,
        ),
        processed_messages,
        "some-other-model",
    )

    mock_handle_response.assert_called_once()
    call_args = mock_handle_response.call_args[0]
    payload = call_args[1]
    assert payload["model"] == "claude-sonnet-4-20250514"
