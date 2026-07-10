"""Tests for OpenAI Codex connector reasoning effort resolution.

Validates the complete flow from URI parameters through to ReasoningSpec in Codex payload.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from httpx import Response
from src.connectors.contracts import ConnectorChatCompletionsRequest
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.model_utils import parse_model_with_params
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry
from src.core.services.translation_service import TranslationService
from tests.mocks.mock_http_client import MockHTTPClient


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    data = {"tokens": {"access_token": "chatgpt_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest_asyncio.fixture(name="openai_codex_backend")
async def openai_codex_backend_fixture(auth_dir: Path):
    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(
                openai_codex_path=str(auth_dir),
            )
            backend._auth_credentials = {"tokens": {"access_token": "chatgpt_token"}}
            try:
                yield backend
            finally:
                await backend.shutdown()


@pytest.fixture
def mock_app_config() -> AppConfig:
    """Fixture for a mock AppConfig with openai-codex backend configured."""
    backends = BackendSettings(
        openai_codex=BackendConfig(
            api_key="test-codex-key",
            api_url="https://api.openai.com/v1",
        ),
    )
    config = AppConfig(backends=backends)
    return config


@pytest.fixture
def mock_http_client() -> MockHTTPClient:
    """Fixture for a mock HTTPX client with streaming Codex response."""
    # Mock streaming SSE response for Codex API
    sse_content = b'event: response.created\ndata: {"id": "resp_test", "object": "response"}\n\nevent: response.completed\ndata: {"id": "resp_test", "object": "response", "status": "completed"}\n\n'
    response = Response(
        200,
        content=sse_content,
        headers={"Content-Type": "text/event-stream"},
    )
    return MockHTTPClient(response=response)


@pytest.fixture
def backend_factory(
    mock_http_client: MockHTTPClient, mock_app_config: AppConfig
) -> BackendFactory:
    """Fixture for a BackendFactory instance with OpenAI Codex registered."""
    registry = BackendRegistry()
    registry._factories.clear()
    registry.register_backend("openai_codex", OpenAICodexConnector)

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
        model="gpt-5.1-codex",
    )


class TestOpenAICodexResolveReasoningEffort:
    """Tests for _resolve_reasoning_effort method."""

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_from_uri_params_high(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that reasoning_effort is resolved from URI params with 'high' value."""
        uri_params = {"reasoning_effort": "high"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "high"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_from_uri_params_low(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that reasoning_effort is resolved from URI params with 'low' value."""
        uri_params = {"reasoning_effort": "low"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "low"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_from_uri_params_xhigh_downgrades_for_unsupported_model(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that 'xhigh' reasoning effort is downgraded to 'high' for unsupported models."""
        uri_params = {"reasoning_effort": "xhigh"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-4-codex",  # Not in XHIGH_SUPPORTED_MODELS
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-4-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "high"  # Should downgrade to high

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_uri_params_takes_precedence_over_request_attribute(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that URI params take precedence over request.reasoning_effort."""
        uri_params = {"reasoning_effort": "low"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
            reasoning_effort="high",  # This should be overridden by URI param
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "low"  # URI param should win

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_request_attribute_fallback_when_no_uri_params(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test fallback to request.reasoning_effort when URI params are empty."""
        uri_params: dict[str, str] = {}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
            reasoning_effort="high",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "high"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_uses_default_when_no_source_provides_value(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that default 'medium' is used when no reasoning_effort is provided."""
        uri_params: dict[str, str] = {}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "medium"  # Default value

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_invalid_value_falls_back_to_default(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """Test that invalid reasoning_effort values fall back to default."""
        uri_params = {"reasoning_effort": "invalid_value"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.1-codex",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "medium"  # Should fall back to default

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_max_supported_on_gpt56_sol(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """``max`` is accepted as-is for models that support it (gpt-5.6-sol)."""
        uri_params = {"reasoning_effort": "max"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.6-sol",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.6-sol",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "max"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_ultra_supported_on_gpt56_terra(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """``ultra`` is accepted as-is for models that support it (gpt-5.6-terra)."""
        uri_params = {"reasoning_effort": "ultra"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.6-terra",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.6-terra",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "ultra"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_ultra_downgrades_to_max_on_luna(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """``ultra`` downgrades to ``max`` on gpt-5.6-luna (supports max, not ultra)."""
        uri_params = {"reasoning_effort": "ultra"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.6-luna",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.6-luna",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "max"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_max_downgrades_to_xhigh_on_gpt55(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """``max`` downgrades to ``xhigh`` on models that top out at xhigh."""
        uri_params = {"reasoning_effort": "max"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.5",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.5",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "xhigh"

    @pytest.mark.asyncio
    async def test_resolve_reasoning_effort_ultra_downgrades_to_xhigh_on_xhigh_only_model(
        self,
        openai_codex_backend: OpenAICodexConnector,
    ) -> None:
        """``ultra`` downgrades to ``xhigh`` on models that top out at xhigh."""
        uri_params = {"reasoning_effort": "ultra"}
        request_data = ChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.5",
        )

        result = openai_codex_backend._resolve_reasoning_effort(
            model="gpt-5.5",
            uri_params=uri_params,
            request_data=request_data,
        )

        assert result == "xhigh"


class TestOpenAICodexURIReasoningEffortIntegration:
    """Integration tests for complete URI reasoning_effort flow to payload."""

    @pytest.mark.asyncio
    async def test_uri_reasoning_effort_stored_on_request_attribute(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Test that URI reasoning_effort is stored on request._codex_resolved_reasoning_effort."""
        backend = backend_factory.create_backend("openai_codex", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openai_codex_path=str(auth_dir := Path.cwd() / ".codex"),
        )

        # Create auth file for credential validation
        auth_dir.mkdir(exist_ok=True)
        (auth_dir / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "test_token"}}), encoding="utf-8"
        )

        # Parse model string with URI parameters
        parsed_model = parse_model_with_params(
            "openai-codex:gpt-5.1-codex?reasoning_effort=high"
        )

        # Verify URI params were extracted correctly
        assert parsed_model.uri_params.get("reasoning_effort") == "high"

        # Store reference to check the request after chat_completions is called
        captured_request = None

        async def capturing_call(*args, **kwargs):
            nonlocal captured_request
            captured_request = kwargs.get("request_data") or args[0]

            # Return a mock streaming response
            async def mock_stream():
                yield Response(200, content=b"event: response.created\ndata: {}\n\n")

            return mock_stream()

        with (
            patch.object(
                backend, "_call_codex_responses_api", side_effect=capturing_call
            ),
            patch.object(backend, "_is_codex_model", return_value=True),
            patch.object(backend, "_validate_runtime_credentials", return_value=True),
        ):
            backend._auth_credentials = {  # type: ignore[attr-defined]
                "tokens": {"access_token": "test"}
            }
            domain = CanonicalChatRequest.model_validate(sample_request.model_dump())
            connector_req = ConnectorChatCompletionsRequest(
                request=domain,
                processed_messages=list(domain.messages),
                effective_model="openai-codex:gpt-5.1-codex?reasoning_effort=high",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )
            await backend.chat_completions(connector_req)

        # Verify the request has the resolved reasoning effort
        assert captured_request is not None
        assert hasattr(captured_request, "_codex_resolved_reasoning_effort")
        assert captured_request._codex_resolved_reasoning_effort == "high"

    @pytest.mark.asyncio
    async def test_xhigh_from_request_when_effective_model_has_no_query_string(
        self,
        backend_factory: BackendFactory,
        sample_request: ChatRequest,
        mock_app_config: AppConfig,
        mock_http_client: MockHTTPClient,
    ) -> None:
        """Simulates resolver output: stripped model + URI params merged by applicator as request field."""
        backend = backend_factory.create_backend("openai_codex", mock_app_config)
        await backend.initialize(
            api_key="test-key",
            openai_codex_path=str(auth_dir := Path.cwd() / ".codex"),
        )

        auth_dir.mkdir(exist_ok=True)
        (auth_dir / "auth.json").write_text(
            json.dumps({"tokens": {"access_token": "test_token"}}), encoding="utf-8"
        )

        request_with_xhigh = sample_request.model_copy(
            update={"reasoning_effort": "xhigh"}
        )
        captured_request = None

        async def capturing_call(*args, **kwargs):
            nonlocal captured_request
            captured_request = kwargs.get("request_data") or args[0]

            async def mock_stream():
                yield Response(200, content=b"event: response.created\ndata: {}\n\n")

            return mock_stream()

        with (
            patch.object(
                backend, "_call_codex_responses_api", side_effect=capturing_call
            ),
            patch.object(backend, "_is_codex_model", return_value=True),
            patch.object(backend, "_validate_runtime_credentials", return_value=True),
        ):
            backend._auth_credentials = {  # type: ignore[attr-defined]
                "tokens": {"access_token": "test"}
            }
            domain = CanonicalChatRequest.model_validate(
                request_with_xhigh.model_dump()
            )
            connector_req = ConnectorChatCompletionsRequest(
                request=domain,
                processed_messages=list(domain.messages),
                effective_model="gpt-5.5",
                identity=None,
                cancellation_token=None,
                cancellation_coordinator=None,
                context=None,
                options={},
            )
            await backend.chat_completions(connector_req)

        assert captured_request is not None
        assert captured_request._codex_resolved_reasoning_effort == "xhigh"

    @pytest.mark.asyncio
    async def test_payload_builder_uses_resolved_reasoning_effort_from_request(
        self,
    ) -> None:
        """Test that PayloadBuilder uses _codex_resolved_reasoning_effort from request."""
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexConnectorSettings,
            CodexRequestContext,
        )
        from src.connectors.openai_codex.payload import PayloadBuilder

        # Create a mock connector
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"

        # Create mock services
        mock_translator = MagicMock()
        mock_translator.translate_messages.return_value = []

        mock_prompt_resolver = MagicMock()
        mock_prompt_resolver.resolve_system_prompt.return_value = None

        mock_tool_resolver = MagicMock()
        mock_tool_resolver.resolve_tool_schema.return_value = []

        settings = CodexConnectorSettings(
            default_capabilities=CodexClientCapabilities(),
            agent_overrides={},
            renderer={
                "default": "none",
                "fallback": "summary",
                "aliases": {},
                "modules": {},
            },
            prompt={
                "template": None,
                "prepend": [],
                "append": [],
                "deduplicate": True,
                "fallback_to_default": True,
            },
            tool_schema={"base_tools": None, "custom_tools": []},
            streaming={"max_retries": 2, "retry_backoff_seconds": (0.5, 1.5, 3.0)},
            compatibility_layer={
                "enabled": False,
                "detection": {"cache_ttl_seconds": 3600, "heuristic_threshold": 2},
                "translation": {
                    "max_tool_execution_timeout": 30,
                    "result_format": "kilo_standard",
                },
                "telemetry": {
                    "log_translations": True,
                    "log_detection": True,
                    "emit_metrics": True,
                },
            },
            websocket={"enabled": False},
        )

        builder = PayloadBuilder(
            connector=mock_connector,
            request_translator=mock_translator,
            prompt_resolver=mock_prompt_resolver,
            tool_schema_resolver=mock_tool_resolver,
            settings=settings,
            message_to_text_converter=lambda m: getattr(m, "content", ""),
        )

        # Create a request with _codex_resolved_reasoning_effort set
        from src.connectors.openai_codex.contracts import CanonicalChatRequest

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )
        # Set by connector using object.__setattr__ to bypass frozen check
        object.__setattr__(request, "_codex_resolved_reasoning_effort", "high")

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="gpt-5.1-codex",
            session_id="test-session-1",
        )

        payload = builder.build_payload(context)

        assert payload.reasoning is not None
        # Check attributes instead of isinstance for robustness under parallel execution
        assert hasattr(payload.reasoning, "effort")
        assert hasattr(payload.reasoning, "summary")
        assert payload.reasoning.effort == "high"
        assert payload.reasoning.summary == "auto"

    @pytest.mark.asyncio
    async def test_payload_builder_reasoning_effort_precedence_request_over_metadata(
        self,
    ) -> None:
        """Test that _codex_resolved_reasoning_effort takes precedence over metadata."""
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexConnectorSettings,
            CodexRequestContext,
        )
        from src.connectors.openai_codex.payload import PayloadBuilder

        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"

        mock_translator = MagicMock()
        mock_translator.translate_messages.return_value = []

        mock_prompt_resolver = MagicMock()
        mock_prompt_resolver.resolve_system_prompt.return_value = None

        mock_tool_resolver = MagicMock()
        mock_tool_resolver.resolve_tool_schema.return_value = []

        settings = CodexConnectorSettings(
            default_capabilities=CodexClientCapabilities(),
            agent_overrides={},
            renderer={
                "default": "none",
                "fallback": "summary",
                "aliases": {},
                "modules": {},
            },
            prompt={
                "template": None,
                "prepend": [],
                "append": [],
                "deduplicate": True,
                "fallback_to_default": True,
            },
            tool_schema={"base_tools": None, "custom_tools": []},
            streaming={"max_retries": 2, "retry_backoff_seconds": (0.5, 1.5, 3.0)},
            compatibility_layer={
                "enabled": False,
                "detection": {"cache_ttl_seconds": 3600, "heuristic_threshold": 2},
                "translation": {
                    "max_tool_execution_timeout": 30,
                    "result_format": "kilo_standard",
                },
                "telemetry": {
                    "log_translations": True,
                    "log_detection": True,
                    "emit_metrics": True,
                },
            },
            websocket={"enabled": False},
        )

        builder = PayloadBuilder(
            connector=mock_connector,
            request_translator=mock_translator,
            prompt_resolver=mock_prompt_resolver,
            tool_schema_resolver=mock_tool_resolver,
            settings=settings,
            message_to_text_converter=lambda m: getattr(m, "content", ""),
        )

        from src.connectors.openai_codex.contracts import CanonicalChatRequest

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="gpt-5.1-codex",
        )
        # Set both _codex_resolved_reasoning_effort and reasoning_effort using object.__setattr__
        object.__setattr__(request, "_codex_resolved_reasoning_effort", "low")
        object.__setattr__(
            request, "reasoning_effort", "high"
        )  # This should be ignored

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="gpt-5.1-codex",
            metadata={"reasoning_effort": "medium"},  # This should also be ignored
            session_id="test-session-2",
        )

        payload = builder.build_payload(context)

        assert payload.reasoning is not None
        assert (
            payload.reasoning.effort == "low"
        )  # _codex_resolved_reasoning_effort wins

    @pytest.mark.asyncio
    async def test_full_flow_uri_param_to_reasoning_spec(
        self,
    ) -> None:
        """Test complete flow: URI param -> connector resolution -> ReasoningSpec in payload."""
        from src.connectors._openai_codex_capabilities import CodexClientCapabilities
        from src.connectors.openai_codex.contracts import (
            CodexConnectorSettings,
            CodexRequestContext,
        )
        from src.connectors.openai_codex.payload import PayloadBuilder

        # Step 1: Parse model string with URI param (as would happen in router)
        parsed = parse_model_with_params(
            "openai-codex:gpt-5.1-codex?reasoning_effort=high"
        )
        assert parsed.uri_params["reasoning_effort"] == "high"

        # Step 2: Create request (simulating what router does)
        from src.connectors.openai_codex.contracts import CanonicalChatRequest

        request = CanonicalChatRequest(
            messages=[ChatMessage(role="user", content="Hello")],
            model="openai-codex:gpt-5.1-codex",
        )

        # Step 3: Simulate connector's _resolve_reasoning_effort (called during chat_completions)
        # In real flow: backend._resolve_reasoning_effort(model, uri_params, request)
        # Here we just simulate that the value is stored
        object.__setattr__(
            request,
            "_codex_resolved_reasoning_effort",
            parsed.uri_params["reasoning_effort"],
        )

        # Step 4: Build payload with the request (simulating _call_codex_responses_api)
        mock_connector = MagicMock()
        mock_connector._is_native_responses_payload.return_value = False
        mock_connector.DEFAULT_REASONING_EFFORT = "medium"

        mock_translator = MagicMock()
        mock_translator.translate_messages.return_value = []

        mock_prompt_resolver = MagicMock()
        mock_prompt_resolver.resolve_system_prompt.return_value = None

        mock_tool_resolver = MagicMock()
        mock_tool_resolver.resolve_tool_schema.return_value = []

        settings = CodexConnectorSettings(
            default_capabilities=CodexClientCapabilities(),
            agent_overrides={},
            renderer={
                "default": "none",
                "fallback": "summary",
                "aliases": {},
                "modules": {},
            },
            prompt={
                "template": None,
                "prepend": [],
                "append": [],
                "deduplicate": True,
                "fallback_to_default": True,
            },
            tool_schema={"base_tools": None, "custom_tools": []},
            streaming={"max_retries": 2, "retry_backoff_seconds": (0.5, 1.5, 3.0)},
            compatibility_layer={
                "enabled": False,
                "detection": {"cache_ttl_seconds": 3600, "heuristic_threshold": 2},
                "translation": {
                    "max_tool_execution_timeout": 30,
                    "result_format": "kilo_standard",
                },
                "telemetry": {
                    "log_translations": True,
                    "log_detection": True,
                    "emit_metrics": True,
                },
            },
            websocket={"enabled": False},
        )

        builder = PayloadBuilder(
            connector=mock_connector,
            request_translator=mock_translator,
            prompt_resolver=mock_prompt_resolver,
            tool_schema_resolver=mock_tool_resolver,
            settings=settings,
            message_to_text_converter=lambda m: getattr(m, "content", ""),
        )

        context = CodexRequestContext(
            request=request,
            processed_messages=[],
            capabilities=CodexClientCapabilities(),
            effective_model="gpt-5.1-codex",
            session_id="test-session-3",
        )

        payload = builder.build_payload(context)

        # Step 5: Verify ReasoningSpec is correctly populated
        assert payload.reasoning is not None
        # Check attributes instead of isinstance for robustness under parallel execution
        assert hasattr(payload.reasoning, "effort")
        assert hasattr(payload.reasoning, "summary")
        assert payload.reasoning.effort == "high"
        assert payload.reasoning.summary == "auto"
        assert "reasoning.encrypted_content" in payload.include
