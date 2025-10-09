from __future__ import annotations

import json

import pytest
from httpx import Response
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry

from tests.mocks.mock_http_client import MockHTTPClient


@pytest.fixture
def mock_app_config() -> AppConfig:
    """Fixture for a mock AppConfig."""
    config = AppConfig()
    config.backends = BackendSettings(
        openrouter=BackendConfig(
            api_key=["test-openrouter-key"], api_url="https://openrouter.ai/api/v1"
        ),
        gemini=BackendConfig(
            api_key=["test-gemini-key"],
            api_url="https://generativelanguage.googleapis.com",
        ),
        anthropic=BackendConfig(
            api_key=["test-anthropic-key"], api_url="https://api.anthropic.com/v1"
        ),
    )
    return config


from src.core.services.translation_service import TranslationService


@pytest.fixture
def backend_factory(
    mock_http_client: MockHTTPClient, mock_app_config: AppConfig
) -> BackendFactory:
    """Fixture for a BackendFactory instance."""
    registry = BackendRegistry()
    registry._factories.clear()

    registry.register_backend("openrouter", OpenRouterBackend)
    registry.register_backend("gemini", GeminiBackend)
    registry.register_backend("anthropic", AnthropicBackend)

    return BackendFactory(
        httpx_client=mock_http_client,
        backend_registry=registry,
        config=mock_app_config,
        translation_service=TranslationService(),
    )


@pytest.fixture
def mock_http_client() -> MockHTTPClient:
    """Fixture for a mock HTTPX client."""
    return MockHTTPClient(
        response=Response(200, json={"choices": [{"message": {"content": "response"}}]})
    )


@pytest.fixture
def sample_request_data() -> ChatRequest:
    """Sample chat request data."""
    return ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="test-model",
    )


class TestCustomModelParameters:
    """
    Tests to ensure custom model parameters (top_k, reasoning_effort)
    are correctly handled and passed to backend connectors.
    """

    @pytest.mark.asyncio
    async def test_openrouter_top_k_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that top_k is included in the payload for OpenRouter."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        request_data = sample_request_data.model_copy(update={"top_k": 50})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "top_k" in payload
        assert payload["top_k"] == 50

    @pytest.mark.asyncio
    async def test_gemini_top_k_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that top_k is included in generationConfig for Gemini."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            key_name="gemini",
        )
        request_data = sample_request_data.model_copy(update={"top_k": 40})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "generationConfig" in payload
        assert "topK" in payload["generationConfig"]
        assert payload["generationConfig"]["topK"] == 40

    @pytest.mark.asyncio
    async def test_anthropic_top_k_parameter_ignored(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that top_k is NOT included in the payload for Anthropic."""
        backend = backend_factory.create_backend("anthropic", mock_app_config)
        await backend.initialize(api_key="test-key", key_name="anthropic")
        request_data = sample_request_data.model_copy(update={"top_k": 30})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "top_k" not in payload

    @pytest.mark.asyncio
    async def test_openrouter_reasoning_effort_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that reasoning_effort is included in the payload for OpenRouter."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )
        request_data = sample_request_data.model_copy(
            update={"reasoning_effort": "high"}
        )

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "reasoning_effort" in payload
        assert payload["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_gemini_reasoning_effort_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that reasoning_effort is included in thinkingConfig for Gemini."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            key_name="gemini",
        )
        request_data = sample_request_data.model_copy(
            update={"reasoning_effort": "high"}
        )

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "generationConfig" in payload
        assert "thinkingConfig" in payload["generationConfig"]
        thinking_config = payload["generationConfig"]["thinkingConfig"]
        assert "thinkingBudget" in thinking_config
        assert thinking_config["thinkingBudget"] == -1
        assert thinking_config.get("includeThoughts") is True

    @pytest.mark.asyncio
    async def test_anthropic_reasoning_effort_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that reasoning_effort is included in the Anthropic payload."""
        backend = backend_factory.create_backend("anthropic", mock_app_config)
        await backend.initialize(api_key="test-key", key_name="anthropic")
        request_data = sample_request_data.model_copy(
            update={"reasoning_effort": "high"}
        )

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "reasoning_effort" in payload
        assert payload["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_openrouter_seed_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that seed is included in the payload for OpenRouter."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        request_data = sample_request_data.model_copy(update={"seed": 12345})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "seed" in payload
        assert payload["seed"] == 12345

    @pytest.mark.asyncio
    async def test_openrouter_top_p_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that top_p is included in the payload for OpenRouter."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        request_data = sample_request_data.model_copy(update={"top_p": 0.5})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "top_p" in payload
        assert payload["top_p"] == 0.5

    @pytest.mark.asyncio
    async def test_gemini_top_p_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that top_p is included in generationConfig for Gemini."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            key_name="gemini",
        )
        request_data = sample_request_data.model_copy(update={"top_p": 0.6})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "generationConfig" in payload
        assert "topP" in payload["generationConfig"]
        assert payload["generationConfig"]["topP"] == 0.6

    @pytest.mark.asyncio
    async def test_gemini_stop_sequences_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that stop is included in generationConfig for Gemini."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            key_name="gemini",
        )
        request_data = sample_request_data.model_copy(
            update={"stop": ["stop1", "stop2"]}
        )

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "generationConfig" in payload
        assert "stopSequences" in payload["generationConfig"]
        assert payload["generationConfig"]["stopSequences"] == ["stop1", "stop2"]

    @pytest.mark.asyncio
    async def test_anthropic_user_parameter(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that user is included in the metadata for Anthropic."""
        backend = backend_factory.create_backend("anthropic", mock_app_config)
        await backend.initialize(api_key="test-key", key_name="anthropic")
        request_data = sample_request_data.model_copy(update={"user": "test-user"})

        await backend.chat_completions(
            request_data=request_data,
            processed_messages=request_data.messages,
            effective_model=request_data.model,
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "metadata" in payload
        assert "user_id" in payload["metadata"]
        assert payload["metadata"]["user_id"] == "test-user"

    @pytest.mark.asyncio
    async def test_unsupported_parameter_does_not_cause_error(
        self,
        backend_factory: BackendFactory,
        sample_request_data: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that an unsupported parameter does not cause an error."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
            key_name="gemini",
        )
        request_data = sample_request_data.model_copy(
            update={"unsupported_param": "test"}
        )

        try:
            await backend.chat_completions(
                request_data=request_data,
                processed_messages=request_data.messages,
                effective_model=request_data.model,
            )
        except Exception as e:
            pytest.fail(f"Unsupported parameter caused an exception: {e}")
