"""Unit tests for CompatibilityLayer.

Tests cover KiloCode/Droid detection, tool translation, state management, and cleanup.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.compat import CompatibilityLayer
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CompatibilityResult,
    CompatibilityState,
    ProcessedMessage,
    ToolExecutionResult,
)
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.core.domain.chat import CanonicalChatRequest


class TestCompatibilityLayer:
    """Test CompatibilityLayer implementation."""

    @pytest.fixture
    def layer(self):
        """Create a CompatibilityLayer instance for testing."""
        return CompatibilityLayer()

    @pytest.fixture
    def mock_session_detector(self):
        """Create a mock SessionDetector."""
        detector = AsyncMock()
        detector.detect = AsyncMock(
            return_value=MagicMock(
                is_kilocode=True,
                detection_method="metadata",
                confidence=1.0,
            )
        )
        return detector

    @pytest.fixture
    def mock_droid_detector(self):
        """Create a mock DroidSessionDetector."""
        detector = MagicMock()
        detector.detect = MagicMock(
            return_value=MagicMock(
                is_droid=True,
                detection_method="tools",
                confidence=0.9,
            )
        )
        return detector

    @pytest.fixture
    def mock_kilo_translator(self):
        """Create a mock KiloToolTranslator."""
        translator = MagicMock()
        translator.translate_tool_invocation = AsyncMock(
            return_value=("read_file", {"path": "/tmp/test.txt"})
        )
        translator._xml_parser = MagicMock()
        translator._xml_parser.parse = MagicMock(return_value=None)
        return translator

    @pytest.fixture
    def mock_tool_execution_service(self):
        """Create a mock ToolExecutionService."""
        service = AsyncMock()
        service.execute_proxy_tool = AsyncMock(
            return_value=ToolExecutionResult(
                success=True, result="[read_file] Result: success", error=None
            )
        )
        service.execute_mcp_tool = AsyncMock(
            return_value=ToolExecutionResult(
                success=True, result="[mcp_tool] Result: success", error=None
            )
        )
        return service

    @pytest.fixture
    def sample_context(self):
        """Create a sample CodexRequestContext."""
        from src.core.domain.chat import ChatMessage

        request = CanonicalChatRequest(
            model="gpt-5.1-codex",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        return CodexRequestContext(
            request=request,
            processed_messages=[
                ProcessedMessage(
                    role="user",
                    content="Test message",
                    tool_calls=None,
                )
            ],
            effective_model="gpt-5.1-codex",
            capabilities=CodexClientCapabilities(),
            session_id="test-session-123",
            metadata={"agent": "kilocode"},
        )

    def test_layer_implements_interface(self, layer):
        """Verify layer implements ICompatibilityLayer interface."""
        assert isinstance(layer, ICompatibilityLayer)

    def test_create_state(self, layer):
        """Test creating a new compatibility state."""
        state = layer.create_state()

        assert isinstance(state, CompatibilityState)
        assert state.is_kilocode is False
        assert state.is_droid is False
        assert state.droid_tool_name_cache == {}
        assert state.droid_tool_args_buffer == {}
        assert state.pending_tool_calls == []

    @pytest.mark.asyncio
    async def test_apply_kilocode_detection(
        self, layer, mock_session_detector, mock_kilo_translator, sample_context
    ):
        """Test KiloCode detection and tool translation."""
        layer._session_detector = mock_session_detector
        layer._kilo_translator = mock_kilo_translator

        result = await layer.apply(sample_context)

        assert isinstance(result, CompatibilityResult)
        assert result.state.is_kilocode is True
        mock_session_detector.detect.assert_called_once()

    @pytest.mark.asyncio
    async def test_apply_droid_detection(
        self, layer, mock_droid_detector, sample_context
    ):
        """Test Droid detection."""
        # Set the detector directly
        layer._droid_detector = mock_droid_detector

        result = await layer.apply(sample_context)

        assert isinstance(result, CompatibilityResult)
        assert result.state.is_droid is True

    @pytest.mark.asyncio
    async def test_apply_no_detection(self, layer, sample_context):
        """Test apply when no compatibility clients are detected."""
        layer._session_detector = None

        result = await layer.apply(sample_context)

        assert isinstance(result, CompatibilityResult)
        assert result.state.is_kilocode is False
        assert result.state.is_droid is False
        assert result.codex_tools == []
        assert result.proxy_tools == []
        assert result.mcp_tools == []
        assert result.tool_results == []

    @pytest.mark.asyncio
    async def test_apply_tool_translation_and_execution(
        self,
        layer,
        mock_session_detector,
        mock_kilo_translator,
        mock_tool_execution_service,
        sample_context,
    ):
        """Test tool translation and execution for KiloCode."""
        layer._session_detector = mock_session_detector
        layer._kilo_translator = mock_kilo_translator
        layer._tool_execution_service = mock_tool_execution_service

        # Mock XML parser to return a parsed tool
        parsed_tool = MagicMock()
        parsed_tool.raw_xml = "<read_file path='/tmp/test.txt'/>"
        parsed_tool.canonical_name = "read_file"
        mock_kilo_translator._xml_parser.parse = MagicMock(return_value=parsed_tool)
        mock_kilo_translator.translate_tool_invocation = AsyncMock(
            return_value=("__proxy_read_file", {"path": "/tmp/test.txt"})
        )

        # Update message content to include XML
        sample_context.processed_messages[0].content = (
            "Please read this file: <read_file path='/tmp/test.txt'/>"
        )

        result = await layer.apply(sample_context)

        assert isinstance(result, CompatibilityResult)
        assert len(result.proxy_tools) > 0 or len(result.tool_results) > 0

    @pytest.mark.asyncio
    async def test_apply_xml_cleaning(
        self,
        layer,
        mock_session_detector,
        mock_kilo_translator,
        sample_context,
    ):
        """Test XML cleaning from messages."""
        layer._session_detector = mock_session_detector
        layer._kilo_translator = mock_kilo_translator

        # Set message content with XML
        sample_context.processed_messages[0].content = (
            "Please read this file: <read_file path='/tmp/test.txt'/>"
        )

        # Mock XML parser to return None (no tools found)
        mock_kilo_translator._xml_parser.parse = MagicMock(return_value=None)

        result = await layer.apply(sample_context)

        # Message content should remain unchanged if no tools were translated
        assert isinstance(result, CompatibilityResult)

    @pytest.mark.asyncio
    async def test_cleanup_state(self, layer):
        """Test state cleanup."""
        state = layer.create_state()
        state.is_kilocode = True
        state.is_droid = True
        state.droid_tool_name_cache["tool1"] = "translated1"
        state.droid_tool_args_buffer["tool1"] = "args1"
        state.pending_tool_calls.append(
            MagicMock(id="call1", name="tool1", command_text="cmd1")
        )

        await layer.cleanup_state(state)

        # State should be cleared
        assert state.droid_tool_name_cache == {}
        assert state.droid_tool_args_buffer == {}
        assert state.pending_tool_calls == []
        # Flags should be reset
        assert state.is_kilocode is False
        assert state.is_droid is False

    @pytest.mark.asyncio
    async def test_cleanup_state_multiple_calls(self, layer):
        """Test that cleanup can be called multiple times safely."""
        state = layer.create_state()
        state.is_kilocode = True

        await layer.cleanup_state(state)
        await layer.cleanup_state(state)  # Should not raise

        assert state.is_kilocode is False

    @pytest.mark.asyncio
    async def test_translate_stream_chunk_no_droid(self, layer):
        """Test stream chunk translation when Droid is not detected."""
        state = layer.create_state()
        state.is_droid = False

        chunk = MagicMock(raw={"choices": [{"delta": {"content": "test"}}]})
        result = await layer.translate_stream_chunk(chunk, state)

        assert result.raw == chunk.raw  # Should be unchanged

    @pytest.mark.asyncio
    async def test_translate_stream_chunk_droid(self, layer):
        """Test stream chunk translation for Droid client."""
        from src.connectors.openai_codex.contracts import ProviderStreamChunk

        state = layer.create_state()
        state.is_droid = True

        # Mock DroidToolTranslator
        mock_droid_translator = MagicMock()
        # Mock translate_codex_to_droid to return Droid format
        mock_droid_translator.translate_codex_to_droid = MagicMock(
            return_value=("Execute", {"command": "ls -la"})
        )
        layer._droid_translator = mock_droid_translator

        # Test chunk with tool_calls structure (as used in streaming)
        chunk_data = {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "function": {
                                    "name": "shell",
                                    "arguments": '{"command": "ls -la"}',
                                },
                            }
                        ]
                    }
                }
            ]
        }
        chunk = ProviderStreamChunk(raw=chunk_data)

        result = await layer.translate_stream_chunk(chunk, state)

        assert isinstance(result, ProviderStreamChunk)
        # The chunk should be mutated in place with translated name
        assert (
            result.raw["choices"][0]["delta"]["tool_calls"][0]["function"]["name"]
            == "Execute"
        )
        mock_droid_translator.translate_codex_to_droid.assert_called()
