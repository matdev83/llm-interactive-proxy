"""Unit tests for EndOfSessionToolCallHandler.

Tests cover:
- Detection of completion tool names
- Session ID extraction
- Signal emission with correct type
- Fail-open behavior
- Non-interference with tool call flow
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.end_of_session_tool_call_handler import (
    EndOfSessionToolCallHandler,
)


@pytest.fixture
def mock_eos_service() -> MagicMock:
    """Create a mock EoS service."""
    mock = MagicMock(spec=IEndOfSessionService)
    mock.record_signal = AsyncMock()
    mock.has_ended = AsyncMock(return_value=False)  # Default to not ended
    return mock


@pytest.fixture
def default_config() -> EndOfSessionConfig:
    """Create default EoS configuration."""
    return EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
    )


@pytest.fixture
def handler(
    mock_eos_service: MagicMock, default_config: EndOfSessionConfig
) -> EndOfSessionToolCallHandler:
    """Create EndOfSessionToolCallHandler instance for testing."""
    return EndOfSessionToolCallHandler(
        end_of_session_service=mock_eos_service,
        config=default_config,
    )


@pytest.fixture
def completion_tool_context() -> ToolCallContext:
    """Create a tool call context for a completion tool."""
    return ToolCallContext(
        session_id="test-session-123",
        backend_name="openai",
        model_name="gpt-4",
        full_response={},
        tool_name="attempt_completion",
        tool_arguments={},
    )


@pytest.fixture
def non_completion_tool_context() -> ToolCallContext:
    """Create a tool call context for a non-completion tool."""
    return ToolCallContext(
        session_id="test-session-123",
        backend_name="openai",
        model_name="gpt-4",
        full_response={},
        tool_name="write_file",
        tool_arguments={},
    )


class TestConfigGating:
    """Test configuration gating behavior."""

    @pytest.mark.asyncio
    async def test_disabled_config_returns_false(
        self,
        mock_eos_service: MagicMock,
        completion_tool_context: ToolCallContext,
    ):
        """Test that disabled config prevents handling."""
        config = EndOfSessionConfig(enabled=False, detect_tool_completion=True)
        handler = EndOfSessionToolCallHandler(
            end_of_session_service=mock_eos_service, config=config
        )

        result = await handler.can_handle(completion_tool_context)

        assert result is False
        mock_eos_service.record_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detect_tool_completion_false_returns_false(
        self,
        mock_eos_service: MagicMock,
        completion_tool_context: ToolCallContext,
    ):
        """Test that detect_tool_completion=False prevents handling."""
        config = EndOfSessionConfig(
            enabled=True, detect_tool_completion=False, emit_events=True
        )
        handler = EndOfSessionToolCallHandler(
            end_of_session_service=mock_eos_service, config=config
        )

        result = await handler.can_handle(completion_tool_context)

        assert result is False


class TestCompletionToolDetection:
    """Test detection of completion tool calls."""

    @pytest.mark.asyncio
    async def test_detects_attempt_completion(
        self,
        handler: EndOfSessionToolCallHandler,
        completion_tool_context: ToolCallContext,
    ):
        """Test detection of attempt_completion tool."""
        result = await handler.can_handle(completion_tool_context)

        assert result is True

    @pytest.mark.asyncio
    async def test_detects_finish_tool(
        self,
        handler: EndOfSessionToolCallHandler,
    ):
        """Test detection of finish tool."""
        context = ToolCallContext(
            session_id="test-123",
            backend_name="openai",
            model_name="gpt-4",
            full_response={},
            tool_name="finish",
            tool_arguments={},
        )

        result = await handler.can_handle(context)

        assert result is True

    @pytest.mark.asyncio
    async def test_does_not_detect_non_completion_tool(
        self,
        handler: EndOfSessionToolCallHandler,
        non_completion_tool_context: ToolCallContext,
    ):
        """Test that non-completion tools are not detected."""
        result = await handler.can_handle(non_completion_tool_context)

        assert result is False


class TestSignalEmission:
    """Test EoS signal emission behavior."""

    @pytest.mark.asyncio
    async def test_emits_signal_with_correct_type(
        self,
        handler: EndOfSessionToolCallHandler,
        mock_eos_service: MagicMock,
        completion_tool_context: ToolCallContext,
    ):
        """Test that signal is emitted with correct type."""
        await handler.handle(completion_tool_context)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.TOOL_COMPLETION
        assert signal.termination_category == EndOfSessionTerminationCategory.NORMAL
        assert signal.session_id == completion_tool_context.session_id
        assert signal.backend == completion_tool_context.backend_name
        assert completion_tool_context.tool_name in signal.reason

    @pytest.mark.asyncio
    async def test_missing_session_id_skips_emission(
        self,
        handler: EndOfSessionToolCallHandler,
        mock_eos_service: MagicMock,
    ):
        """Test that missing session_id prevents emission."""
        context = ToolCallContext(
            session_id="",
            backend_name="openai",
            model_name="gpt-4",
            full_response={},
            tool_name="attempt_completion",
            tool_arguments={},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        mock_eos_service.record_signal.assert_not_awaited()


class TestNonInterference:
    """Test that handler does not interfere with tool call flow."""

    @pytest.mark.asyncio
    async def test_returns_non_swallowing_result(
        self,
        handler: EndOfSessionToolCallHandler,
        mock_eos_service: MagicMock,
        completion_tool_context: ToolCallContext,
    ):
        """Test that handler returns non-swallowing result."""
        result = await handler.handle(completion_tool_context)

        assert result.should_swallow is False
        assert result.replacement_response is None


class TestFailOpen:
    """Test fail-open error handling."""

    @pytest.mark.asyncio
    async def test_service_error_logged_but_not_raised(
        self,
        handler: EndOfSessionToolCallHandler,
        mock_eos_service: MagicMock,
        completion_tool_context: ToolCallContext,
    ):
        """Test that service errors are logged but not raised."""
        mock_eos_service.record_signal.side_effect = Exception("Service error")

        # Should not raise
        result = await handler.handle(completion_tool_context)

        assert result.should_swallow is False
        mock_eos_service.record_signal.assert_awaited_once()


class TestHandlerProperties:
    """Test handler properties."""

    def test_name_property(self, handler: EndOfSessionToolCallHandler):
        """Test that name property returns correct value."""
        assert handler.name == "end_of_session_tool_call_handler"

    def test_priority_property(self, handler: EndOfSessionToolCallHandler):
        """Test that priority property returns correct value."""
        assert handler.priority == 85
