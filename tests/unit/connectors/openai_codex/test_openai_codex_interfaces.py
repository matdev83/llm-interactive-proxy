"""Tests for OpenAI Codex connector service interfaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from src.connectors.openai_codex.contracts import (
    CodexConnectorSettings,
    CodexPayload,
    CodexRequestContext,
    CompatibilityResult,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolArguments,
    ToolExecutionResult,
)
from src.connectors.openai_codex.interfaces import (
    ICompatibilityLayer,
    ICredentialManager,
    IPayloadBuilder,
    IPromptResolver,
    IRequestTranslator,
    IResponseExecutor,
    ISettingsLoader,
    IToolExecutionService,
    IToolSchemaResolver,
)
from src.core.config.app_config import AppConfig
from src.core.domain.responses import ResponseEnvelope


class TestISettingsLoader:
    """Tests for ISettingsLoader interface."""

    def test_interface_has_load_method(self):
        """Test that ISettingsLoader defines load method."""
        assert hasattr(ISettingsLoader, "load")
        assert callable(ISettingsLoader.load)

    def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_loader = Mock(spec=ISettingsLoader)
        config = Mock(spec=AppConfig)
        settings = Mock(spec=CodexConnectorSettings)
        mock_loader.load.return_value = settings

        result = mock_loader.load(config)
        assert result == settings
        mock_loader.load.assert_called_once_with(config)


class TestICredentialManager:
    """Tests for ICredentialManager interface."""

    def test_interface_has_required_methods(self):
        """Test that ICredentialManager defines all required methods."""
        assert hasattr(ICredentialManager, "initialize")
        assert hasattr(ICredentialManager, "refresh_access_token")
        assert hasattr(ICredentialManager, "get_access_token")
        assert hasattr(ICredentialManager, "shutdown")
        assert hasattr(ICredentialManager, "is_watcher_running")

    @pytest.mark.asyncio
    async def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_manager = Mock(spec=ICredentialManager)
        mock_manager.initialize.return_value = None
        mock_manager.refresh_access_token.return_value = True
        mock_manager.get_access_token.return_value = "token123"
        mock_manager.shutdown.return_value = None
        mock_manager.is_watcher_running.return_value = False

        await mock_manager.initialize(Path("/path/to/auth.json"))
        assert await mock_manager.refresh_access_token() is True
        assert mock_manager.get_access_token() == "token123"
        assert mock_manager.is_watcher_running() is False


class TestIPayloadBuilder:
    """Tests for IPayloadBuilder interface."""

    def test_interface_has_build_payload_method(self):
        """Test that IPayloadBuilder defines build_payload method."""
        assert hasattr(IPayloadBuilder, "build_payload")
        assert callable(IPayloadBuilder.build_payload)

    def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_builder = Mock(spec=IPayloadBuilder)
        context = Mock(spec=CodexRequestContext)
        payload = Mock(spec=CodexPayload)
        mock_builder.build_payload.return_value = payload

        result = mock_builder.build_payload(context)
        assert result == payload
        mock_builder.build_payload.assert_called_once_with(context)


class TestIRequestTranslator:
    """Tests for IRequestTranslator interface."""

    def test_interface_has_translate_methods(self):
        """Test that IRequestTranslator defines translate methods."""
        assert hasattr(IRequestTranslator, "translate_messages")
        assert hasattr(IRequestTranslator, "translate_tool_calls")

    def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_translator = Mock(spec=IRequestTranslator)
        messages = [Mock(spec=ProcessedMessage)]
        mock_translator.translate_messages.return_value = []

        result = mock_translator.translate_messages(messages)
        assert result == []
        mock_translator.translate_messages.assert_called_once_with(messages)


class TestIPromptResolver:
    """Tests for IPromptResolver interface."""

    def test_interface_has_resolve_methods(self):
        """Test that IPromptResolver defines resolve methods."""
        assert hasattr(IPromptResolver, "resolve_system_prompt")
        assert hasattr(IPromptResolver, "resolve_instructions")

    def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_resolver = Mock(spec=IPromptResolver)
        settings = Mock(spec=CodexConnectorSettings)
        capabilities = Mock()
        mock_resolver.resolve_system_prompt.return_value = "System prompt"
        mock_resolver.resolve_instructions.return_value = "Instructions"

        result = mock_resolver.resolve_system_prompt(settings, capabilities)
        assert result == "System prompt"
        mock_resolver.resolve_system_prompt.assert_called_once_with(
            settings, capabilities
        )


class TestIToolSchemaResolver:
    """Tests for IToolSchemaResolver interface."""

    def test_interface_exists(self):
        """Test that IToolSchemaResolver interface exists."""
        assert IToolSchemaResolver is not None


class TestIResponseExecutor:
    """Tests for IResponseExecutor interface."""

    def test_interface_has_execute_method(self):
        """Test that IResponseExecutor defines execute method."""
        assert hasattr(IResponseExecutor, "execute")
        assert callable(IResponseExecutor.execute)

    @pytest.mark.asyncio
    async def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_executor = Mock(spec=IResponseExecutor)
        payload = Mock(spec=CodexPayload)
        context = Mock(spec=CodexRequestContext)
        response = Mock(spec=ResponseEnvelope)
        mock_executor.execute.return_value = response

        result = await mock_executor.execute(payload, context)
        assert result == response
        mock_executor.execute.assert_called_once_with(payload, context)


class TestICompatibilityLayer:
    """Tests for ICompatibilityLayer interface."""

    def test_interface_has_required_methods(self):
        """Test that ICompatibilityLayer defines all required methods."""
        assert hasattr(ICompatibilityLayer, "apply")
        assert hasattr(ICompatibilityLayer, "translate_stream_chunk")
        assert hasattr(ICompatibilityLayer, "cleanup_state")
        assert hasattr(ICompatibilityLayer, "create_state")

    @pytest.mark.asyncio
    async def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_layer = Mock(spec=ICompatibilityLayer)
        context = Mock(spec=CodexRequestContext)
        result = Mock(spec=CompatibilityResult)
        mock_layer.apply.return_value = result

        state = Mock(spec=CompatibilityState)
        mock_layer.create_state.return_value = state

        chunk = Mock(spec=ProviderStreamChunk)
        mock_layer.translate_stream_chunk.return_value = chunk

        apply_result = await mock_layer.apply(context)
        assert apply_result == result

        created_state = mock_layer.create_state()
        assert created_state == state

        translated_chunk = await mock_layer.translate_stream_chunk(chunk, state)
        assert translated_chunk == chunk

        await mock_layer.cleanup_state(state)
        mock_layer.cleanup_state.assert_called_once_with(state)


class TestIToolExecutionService:
    """Tests for IToolExecutionService interface."""

    def test_interface_has_execute_methods(self):
        """Test that IToolExecutionService defines execute methods."""
        assert hasattr(IToolExecutionService, "execute_proxy_tool")
        assert hasattr(IToolExecutionService, "execute_mcp_tool")

    @pytest.mark.asyncio
    async def test_mock_implementation(self):
        """Test that a mock implementation can be created."""
        mock_service = Mock(spec=IToolExecutionService)
        tool_result = Mock(spec=ToolExecutionResult)
        mock_service.execute_proxy_tool.return_value = tool_result
        mock_service.execute_mcp_tool.return_value = tool_result

        args = Mock(spec=ToolArguments)
        proxy_result = await mock_service.execute_proxy_tool("tool_name", args)
        assert proxy_result == tool_result

        mcp_result = await mock_service.execute_mcp_tool("tool_name", args)
        assert mcp_result == tool_result
