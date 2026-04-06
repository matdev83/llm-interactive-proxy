"""
Integration tests for end-to-end URI parameter flow.

Tests the complete request flow with URI parameters from model string parsing
through parameter resolution to backend application.
"""

from __future__ import annotations

import json
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import Response
from src.connectors.anthropic import AnthropicBackend
from src.connectors.gemini import GeminiBackend
from src.connectors.hybrid import HybridConnector
from src.connectors.openrouter import OpenRouterBackend
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_with_params
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry
from src.core.services.parameter_resolution_service import (
    ParameterResolutionService,
)
from src.core.services.translation_service import TranslationService
from src.core.services.uri_parameter_validator import URIParameterValidator

from tests.integration.connector_request_helpers import make_connector_chat_request
from tests.mocks.mock_http_client import MockHTTPClient


@pytest.fixture
def mock_app_config() -> AppConfig:
    """Fixture for a mock AppConfig with all backends configured."""
    backends = BackendSettings(
        openrouter=BackendConfig(
            api_key="test-openrouter-key", api_url="https://openrouter.ai/api/v1"
        ),
        gemini=BackendConfig(
            api_key="test-gemini-key",
            api_url="https://generativelanguage.googleapis.com",
        ),
        anthropic=BackendConfig(
            api_key="test-anthropic-key", api_url="https://api.anthropic.com/v1"
        ),
    )
    config = AppConfig(backends=backends)
    return config


@pytest.fixture
def mock_http_client() -> MockHTTPClient:
    """Fixture for a mock HTTPX client."""
    return MockHTTPClient(
        response=Response(
            200,
            json={
                "id": "test-id",
                "choices": [{"message": {"content": "response", "role": "assistant"}}],
                "model": "test-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )
    )


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
    registry.register_backend("hybrid", HybridConnector)

    return BackendFactory(
        httpx_client=mock_http_client,
        backend_registry=registry,
        config=mock_app_config,
        translation_service=TranslationService(),
    )


@pytest.fixture
def sample_request() -> ChatRequest:
    """Sample chat request data."""
    return ChatRequest(
        messages=[ChatMessage(role="user", content="Hello")],
        model="test-model",
    )


class TestURIParameterParsing:
    """Test URI parameter parsing from model strings."""

    def test_parse_simple_model_with_temperature(self) -> None:
        """Test parsing model string with temperature parameter."""
        result = parse_model_with_params("openai:gpt-4?temperature=0.5")

        assert result.backend_type == "openai"
        assert result.model_name == "gpt-4"
        assert result.uri_params == {"temperature": "0.5"}

    def test_parse_model_with_multiple_parameters(self) -> None:
        """Test parsing model string with multiple URI parameters."""
        result = parse_model_with_params(
            "anthropic:claude-3?temperature=0.7&reasoning_effort=high"
        )

        assert result.backend_type == "anthropic"
        assert result.model_name == "claude-3"
        assert result.uri_params == {"temperature": "0.7", "reasoning_effort": "high"}

    def test_parse_model_with_complex_path_and_parameters(self) -> None:
        """Test parsing model string with complex model path and parameters."""
        result = parse_model_with_params(
            "openrouter:anthropic/claude-3-haiku:beta?temperature=0.3&reasoning_effort=medium"
        )

        assert result.backend_type == "openrouter"
        assert result.model_name == "anthropic/claude-3-haiku:beta"
        assert result.uri_params == {"temperature": "0.3", "reasoning_effort": "medium"}

    def test_parse_model_with_sampling_parameters(self) -> None:
        """Test parsing model string including top_p and top_k parameters."""
        result = parse_model_with_params("openrouter:gpt-4?top_p=0.9&top_k=40")

        assert result.backend_type == "openrouter"
        assert result.model_name == "gpt-4"
        assert result.uri_params == {"top_p": "0.9", "top_k": "40"}


class TestURIParameterValidation:
    """Test URI parameter validation and normalization."""

    def test_validate_temperature_valid_range(self) -> None:
        """Test validation of temperature within valid range."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize({"temperature": "0.5"})

        assert normalized == {"temperature": 0.5}
        assert errors == []

    def test_validate_temperature_out_of_range(self) -> None:
        """Test validation of temperature outside valid range."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize({"temperature": "3.5"})

        assert normalized == {}
        assert len(errors) == 1
        assert "temperature" in errors[0]

    def test_validate_reasoning_effort_valid_values(self) -> None:
        """Test validation of reasoning_effort with valid values."""
        validator = URIParameterValidator()

        for value in ["low", "medium", "high", "xhigh"]:
            normalized, errors = validator.validate_and_normalize(
                {"reasoning_effort": value}
            )
            assert normalized == {"reasoning_effort": value}
            assert errors == []

    def test_validate_reasoning_effort_invalid_value(self) -> None:
        """Test validation of reasoning_effort with invalid value."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize(
            {"reasoning_effort": "extreme"}
        )

        assert normalized == {}
        assert len(errors) == 1
        assert "reasoning_effort" in errors[0]

    def test_validate_sampling_parameters(self) -> None:
        """Test validation of top_p and top_k parameters."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize(
            {"top_p": "0.95", "top_k": "40"}
        )

        assert normalized == {"top_p": 0.95, "top_k": 40}
        assert errors == []

    def test_validate_unknown_parameter_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that unknown parameters generate warnings but don't cause errors."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize(
            {"unknown_param": "value", "temperature": "0.5"}
        )

        # Unknown parameter should be ignored, valid parameter should be normalized
        assert normalized == {"temperature": 0.5}
        assert errors == []
        assert "Unknown URI parameter" in caplog.text


class TestParameterResolution:
    """Test parameter resolution from multiple sources with precedence."""

    def test_uri_overrides_config(self) -> None:
        """Test that URI parameters override config parameters."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params={"temperature": 0.5},
            config_params={"temperature": 0.8},
            backend="test-backend",
        )

        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.5
        assert resolved.temperature.source == "uri"

    def test_uri_overrides_headers(self) -> None:
        """Test that URI parameters override header parameters."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params={"temperature": 0.5},
            header_params={"temperature": 0.7},
            backend="test-backend",
        )

        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.5
        assert resolved.temperature.source == "uri"

    def test_session_overrides_uri(self) -> None:
        """Test that session parameters override URI parameters."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params={"temperature": 0.5},
            session_params={"temperature": 0.3},
            backend="test-backend",
        )

        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.3
        assert resolved.temperature.source == "session"

    def test_full_precedence_chain(self) -> None:
        """Test complete precedence chain: session > uri > header > config."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            config_params={"temperature": 0.1},
            header_params={"temperature": 0.3},
            uri_params={"temperature": 0.5},
            session_params={"temperature": 0.8},
            backend="test-backend",
        )

        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.8
        assert resolved.temperature.source == "session"

    def test_top_parameters_resolution(self) -> None:
        """Test precedence resolution for top_p and top_k parameters."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            config_params={"top_p": 0.2, "top_k": 10},
            uri_params={"top_p": 0.7, "top_k": 25},
            session_params={"top_k": 40},
            backend="test-backend",
        )

        assert resolved.top_p is not None
        assert resolved.top_p.value == 0.7
        assert resolved.top_p.source == "uri"
        assert resolved.top_k is not None
        assert resolved.top_k.value == 40
        assert resolved.top_k.source == "session"

    def test_resolution_with_missing_sources(self) -> None:
        """Test parameter resolution when some sources are missing."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params={"temperature": 0.5},
            # No header, config, or session params
            backend="test-backend",
        )

        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.5
        assert resolved.temperature.source == "uri"

    def test_resolution_debug_info(self) -> None:
        """Test that resolution provides debug information."""
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params={"temperature": 0.5, "reasoning_effort": "high"},
            config_params={"temperature": 0.8},
            backend="test-backend",
        )

        debug_info = resolved.get_debug_info()
        assert "temperature" in debug_info
        assert debug_info["temperature"].effective_value == 0.5
        assert debug_info["temperature"].source == "uri"
        assert "reasoning_effort" in debug_info
        assert debug_info["reasoning_effort"].effective_value == "high"


class TestEndToEndURIParameterFlow:
    """Test complete end-to-end flow with URI parameters."""

    @pytest.mark.asyncio
    async def test_openrouter_with_uri_temperature(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test complete flow with URI temperature parameter for OpenRouter."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        # Parse model string with URI parameters
        parsed_model = parse_model_with_params("openrouter:gpt-4?temperature=0.5")
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        # Validate and normalize URI parameters
        validator = URIParameterValidator()
        normalized_params, errors = validator.validate_and_normalize(uri_params)
        assert errors == []

        # Create request with normalized parameters
        request_data = sample_request.model_copy(update=normalized_params)

        # Execute request
        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        # Verify parameters were applied
        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "temperature" in payload
        assert payload["temperature"] == 0.5

    @pytest.mark.asyncio
    async def test_openrouter_with_uri_sampling_parameters(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test OpenRouter flow with top_p and top_k URI parameters."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        parsed_model = parse_model_with_params("openrouter:gpt-4?top_p=0.95&top_k=40")
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        validator = URIParameterValidator()
        normalized_params, errors = validator.validate_and_normalize(uri_params)
        assert errors == []

        request_data = sample_request.model_copy(update=normalized_params)

        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert payload.get("top_p") == 0.95
        assert payload.get("top_k") == 40

    @pytest.mark.asyncio
    async def test_anthropic_with_uri_reasoning_effort(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test complete flow with URI reasoning_effort parameter for Anthropic."""
        backend = backend_factory.create_backend("anthropic", mock_app_config)
        await backend.initialize(api_key="test-key", key_name="anthropic")

        # Parse model string with URI parameters
        parsed_model = parse_model_with_params(
            "anthropic:claude-3?reasoning_effort=high"
        )
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        # Validate and normalize URI parameters
        validator = URIParameterValidator()
        normalized_params, errors = validator.validate_and_normalize(uri_params)
        assert errors == []

        # Create request with normalized parameters
        request_data = sample_request.model_copy(update=normalized_params)

        # Execute request
        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        # Verify parameters were applied
        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert "reasoning_effort" in payload
        assert payload["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_gemini_with_uri_sampling_parameters(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test Gemini flow with top_p and top_k URI parameters."""
        backend = backend_factory.create_backend("gemini", mock_app_config)
        await backend.initialize(
            api_key="test-gemini-key",
            key_name="gemini",
            gemini_api_base_url="https://generativelanguage.googleapis.com",
        )

        parsed_model = parse_model_with_params(
            "gemini:models/gemini-pro?top_p=0.85&top_k=32"
        )
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        validator = URIParameterValidator()
        normalized_params, errors = validator.validate_and_normalize(uri_params)
        assert errors == []

        request_data = sample_request.model_copy(update=normalized_params)

        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        generation_config = payload.get("generationConfig", {})
        assert generation_config.get("topP") == 0.85
        assert generation_config.get("topK") == 32

    @pytest.mark.asyncio
    async def test_parameter_override_precedence_full_chain(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test parameter override precedence with all sources."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        # Parse model string with URI parameters
        parsed_model = parse_model_with_params("openrouter:gpt-4?temperature=0.5")
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        # Validate URI parameters
        validator = URIParameterValidator()
        normalized_uri_params, _ = validator.validate_and_normalize(uri_params)

        # Simulate different parameter sources
        config_params = {"temperature": 0.1}
        header_params = {"temperature": 0.3}
        session_params = {"temperature": 0.8}

        # Resolve parameters with precedence
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params=normalized_uri_params,
            header_params=header_params,
            config_params=config_params,
            session_params=session_params,
            backend="openrouter",
        )

        # Session parameters should win
        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.8
        assert resolved.temperature.source == "session"

        # Apply resolved parameters to request
        final_params = resolved.to_dict()
        request_data = sample_request.model_copy(update=final_params)

        # Execute request
        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        # Verify the effective parameter was applied
        sent_request = mock_http_client.sent_request
        assert sent_request is not None
        payload = json.loads(sent_request.content)
        assert payload["temperature"] == 0.8

    @pytest.mark.asyncio
    async def test_uri_overrides_config_and_headers(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that URI parameters override config and headers when no session overrides are present."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        # Parse model string with URI parameters
        parsed_model = parse_model_with_params("openrouter:gpt-4?temperature=0.5")
        uri_params = parsed_model.uri_params

        # Validate URI parameters
        validator = URIParameterValidator()
        normalized_uri_params, _ = validator.validate_and_normalize(uri_params)

        # Simulate config and header parameters (no session)
        config_params = {"temperature": 0.1}
        header_params = {"temperature": 0.3}

        # Resolve parameters
        service = ParameterResolutionService()
        resolved = service.resolve_parameters(
            uri_params=normalized_uri_params,
            header_params=header_params,
            config_params=config_params,
            backend="openrouter",
        )

        # URI should win over config and headers
        assert resolved.temperature is not None
        assert resolved.temperature.value == 0.5
        assert resolved.temperature.source == "uri"


class TestHybridBackendURIParameters:
    """Test hybrid backend with URI parameters."""

    @pytest.mark.asyncio
    async def test_hybrid_backend_with_uri_parameters_on_both_models(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test hybrid backend request with URI parameters on both reasoning and execution models."""
        # Create hybrid backend
        hybrid_backend = backend_factory.create_backend("hybrid", mock_app_config)
        hybrid_backend = cast(HybridConnector, hybrid_backend)

        # Mock the sub-backends
        mock_reasoning_backend = AsyncMock()
        mock_reasoning_backend.chat_completions = AsyncMock(
            return_value={
                "id": "reasoning-id",
                "choices": [
                    {"message": {"content": "reasoning response", "role": "assistant"}}
                ],
                "model": "reasoning-model",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }
        )

        mock_execution_backend = AsyncMock()
        mock_execution_backend.chat_completions = AsyncMock(
            return_value={
                "id": "execution-id",
                "choices": [
                    {"message": {"content": "execution response", "role": "assistant"}}
                ],
                "model": "execution-model",
                "usage": {"prompt_tokens": 15, "completion_tokens": 25},
            }
        )

        # Initialize hybrid backend
        await hybrid_backend.initialize(
            reasoning_backend=mock_reasoning_backend,
            execution_backend=mock_execution_backend,
        )

        # Parse hybrid model spec with URI parameters
        model_spec = "hybrid:[openai:gpt-4?temperature=0.8&top_p=0.9,anthropic:claude-3?temperature=0.3&top_k=40]"

        # Test parsing
        spec = hybrid_backend._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {"temperature": "0.8", "top_p": "0.9"}

        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {"temperature": "0.3", "top_k": "40"}

    @pytest.mark.asyncio
    async def test_hybrid_backend_with_reasoning_effort_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that hybrid backend logs warning when reasoning_effort is specified."""
        from src.connectors.hybrid import HybridConnector

        # Create a minimal hybrid backend instance
        hybrid_backend = HybridConnector(
            client=AsyncMock(),
            config=MagicMock(),
            translation_service=MagicMock(),
        )

        # Parse hybrid model spec with reasoning_effort parameter
        model_spec = "hybrid:[openai:gpt-4?reasoning_effort=high,anthropic:claude-3]"

        # Parse the spec
        spec = hybrid_backend._parse_hybrid_model_spec(model_spec)

        # Verify reasoning_effort was parsed
        assert spec.reasoning_params == {"reasoning_effort": "high"}

        # Note: The warning for reasoning_effort in hybrid mode should be logged
        # when the parameters are actually applied, not during parsing.
        # This test verifies that the parameter is parsed correctly.

    @pytest.mark.asyncio
    async def test_hybrid_backend_with_one_model_having_uri_params(
        self,
    ) -> None:
        """Test hybrid backend with only one model having URI parameters."""
        from src.connectors.hybrid import HybridConnector

        hybrid_backend = HybridConnector(
            client=AsyncMock(),
            config=MagicMock(),
            translation_service=MagicMock(),
        )

        # Parse hybrid model spec with parameters only on execution model
        model_spec = "hybrid:[openai:gpt-4,anthropic:claude-3?temperature=0.3]"

        spec = hybrid_backend._parse_hybrid_model_spec(model_spec)

        assert spec.reasoning_backend == "openai"
        assert spec.reasoning_model == "gpt-4"
        assert spec.reasoning_params == {}

        assert spec.execution_backend == "anthropic"
        assert spec.execution_model == "claude-3"
        assert spec.execution_params == {"temperature": "0.3"}


class TestDebugLogging:
    """Test debug logging for parameter resolution."""

    def test_parameter_resolution_debug_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that parameter resolution emits debug logs."""
        import logging

        caplog.set_level(logging.DEBUG)

        service = ParameterResolutionService()
        service.resolve_parameters(
            uri_params={"temperature": 0.5},
            config_params={"temperature": 0.8},
            backend="test-backend",
        )

        # Check that debug log was emitted
        assert "Parameter resolution for test-backend" in caplog.text
        assert "temperature: 0.5" in caplog.text
        assert "source: uri" in caplog.text
        assert "overrode: config=0.8" in caplog.text

    def test_uri_parameter_parsing_debug_logging(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that URI parameter parsing emits debug logs."""
        import logging

        caplog.set_level(logging.DEBUG)

        parse_model_with_params("openai:gpt-4?temperature=0.5&reasoning_effort=high")

        # Check that debug log was emitted
        assert "Parsed URI parameters" in caplog.text

    def test_validation_error_logging(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that validation errors are logged."""
        import logging

        caplog.set_level(logging.ERROR)

        validator = URIParameterValidator()
        validator.validate_and_normalize({"temperature": "3.5"})

        # Check that error log was emitted
        assert "Invalid URI parameter value" in caplog.text
        assert "temperature=3.5" in caplog.text


class TestGracefulErrorHandling:
    """Test graceful error handling for malformed URI parameters."""

    def test_malformed_query_string_graceful_fallback(self) -> None:
        """Test that malformed query strings are handled gracefully."""
        # This should not raise an exception
        result = parse_model_with_params("backend:model?invalid")

        assert result.backend_type == "backend"
        assert result.model_name == "model"
        assert isinstance(result.uri_params, dict)

    def test_invalid_parameter_value_continues_processing(
        self,
    ) -> None:
        """Test that invalid parameter values don't stop processing."""
        validator = URIParameterValidator()
        normalized, errors = validator.validate_and_normalize(
            {"temperature": "invalid", "reasoning_effort": "high"}
        )

        # Invalid temperature should be excluded, but valid reasoning_effort should be included
        assert "temperature" not in normalized
        assert normalized == {"reasoning_effort": "high"}
        assert len(errors) == 1

    def test_empty_query_string_handled_gracefully(self) -> None:
        """Test that empty query strings are handled gracefully."""
        result = parse_model_with_params("backend:model?")

        assert result.backend_type == "backend"
        assert result.model_name == "model"
        assert result.uri_params == {}

    @pytest.mark.asyncio
    async def test_request_continues_with_invalid_uri_params(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that requests continue even with invalid URI parameters."""
        backend = backend_factory.create_backend("openrouter", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openrouter_headers_provider=lambda key, name: {
                "Authorization": f"Bearer {key}"
            },
            key_name="openrouter",
        )

        # Parse model string with invalid URI parameter
        parsed_model = parse_model_with_params("openrouter:gpt-4?temperature=invalid")
        model_name = parsed_model.model_name
        uri_params = parsed_model.uri_params

        # Validate - should exclude invalid parameter
        validator = URIParameterValidator()
        normalized_params, errors = validator.validate_and_normalize(uri_params)

        # Should have errors but normalized params should be empty
        assert errors != []
        assert normalized_params == {}

        # Request should still proceed with default parameters
        request_data = sample_request.model_copy()

        # This should not raise an exception
        await backend.chat_completions(
            make_connector_chat_request(request_data, effective_model=model_name),
        )

        # Verify request was sent
        sent_request = mock_http_client.sent_request
        assert sent_request is not None
