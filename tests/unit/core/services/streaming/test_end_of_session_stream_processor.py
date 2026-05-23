"""Unit tests for EndOfSessionStreamProcessor.

Tests cover:
- Detection of all completion marker types
- Session ID extraction from metadata
- Missing session_id handling (log and skip)
- Signal type mapping correctness
- Pass-through behavior (content unchanged)
- Fail-open on service errors
- Non-streaming response detection (via single-chunk wrapper)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.domain.events.end_of_session_events import (
    EndOfSessionSignalType,
    EndOfSessionTerminationCategory,
)
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.interfaces.end_of_session_service_interface import IEndOfSessionService
from src.core.services.streaming.end_of_session_stream_processor import (
    EndOfSessionStreamProcessor,
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
def processor(
    mock_eos_service: MagicMock, default_config: EndOfSessionConfig
) -> EndOfSessionStreamProcessor:
    """Create EndOfSessionStreamProcessor instance for testing."""
    return EndOfSessionStreamProcessor(
        end_of_session_service=mock_eos_service,
        config=default_config,
    )


class TestConfigGating:
    """Test configuration gating behavior."""

    @pytest.mark.asyncio
    async def test_disabled_config_skips_processing(
        self,
        mock_eos_service: MagicMock,
    ):
        """Test that disabled config prevents processing."""
        config = EndOfSessionConfig(enabled=False, detect_stream_signals=True)
        processor = EndOfSessionStreamProcessor(
            end_of_session_service=mock_eos_service, config=config
        )

        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        result = await processor.process(content)

        assert result == content
        mock_eos_service.record_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_detect_stream_signals_false_skips_processing(
        self,
        mock_eos_service: MagicMock,
    ):
        """Test that detect_stream_signals=False prevents processing."""
        config = EndOfSessionConfig(
            enabled=True, detect_stream_signals=False, emit_events=True
        )
        processor = EndOfSessionStreamProcessor(
            end_of_session_service=mock_eos_service, config=config
        )

        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        result = await processor.process(content)

        assert result == content
        mock_eos_service.record_signal.assert_not_awaited()


class TestSessionIdExtraction:
    """Test session ID extraction from metadata."""

    @pytest.mark.asyncio
    async def test_extracts_session_id_from_metadata(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that session_id is extracted from metadata."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.session_id == "test-123"

    @pytest.mark.asyncio
    async def test_extracts_id_as_fallback(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that 'id' field is used as fallback for session_id."""
        content = StreamingContent(
            content="test",
            metadata={"id": "test-456"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.session_id == "test-456"

    @pytest.mark.asyncio
    async def test_missing_session_id_skips_emission(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that missing session_id prevents emission."""
        content = StreamingContent(
            content="test",
            metadata={},
            is_done=True,
        )

        result = await processor.process(content)

        assert result == content
        mock_eos_service.record_signal.assert_not_awaited()


class TestCompletionMarkerDetection:
    """Test detection of various completion markers."""

    @pytest.mark.asyncio
    async def test_detects_is_done_flag(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test detection of is_done=True flag."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL
        assert signal.termination_category == EndOfSessionTerminationCategory.NORMAL

    @pytest.mark.asyncio
    async def test_detects_done_sentinel_in_content(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test detection of [DONE] sentinel in content."""
        content = StreamingContent(
            content="[DONE]",
            metadata={"session_id": "test-123"},
            is_done=False,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL
        assert "[DONE]" in signal.reason

    @pytest.mark.asyncio
    async def test_detects_finish_reason(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test detection of finish_reason in metadata."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "stop"},
            is_done=False,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.FINISH_REASON
        assert "stop" in signal.reason

    @pytest.mark.asyncio
    async def test_detects_message_stop(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test detection of message_stop in metadata."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "message_stop": True},
            is_done=False,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.RESPONSE_COMPLETED

    @pytest.mark.asyncio
    async def test_detects_response_completed(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test detection of response.completed in metadata."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "response.completed": True},
            is_done=False,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.RESPONSE_COMPLETED


class TestPassThroughBehavior:
    """Test that processor preserves content unchanged."""

    @pytest.mark.asyncio
    async def test_content_unchanged(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that content is returned unchanged."""
        content = StreamingContent(
            content="test content",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        result = await processor.process(content)

        assert result is content
        assert result.content == "test content"
        assert result.metadata == content.metadata
        assert result.is_done == content.is_done

    @pytest.mark.asyncio
    async def test_no_completion_marker_returns_unchanged(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that content without completion markers is returned unchanged."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=False,
        )

        result = await processor.process(content)

        assert result is content
        mock_eos_service.record_signal.assert_not_awaited()


class TestFailOpen:
    """Test fail-open error handling."""

    @pytest.mark.asyncio
    async def test_service_error_logged_but_not_raised(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that service errors are logged but not raised."""
        mock_eos_service.record_signal.side_effect = Exception("Service error")
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        # Should not raise
        result = await processor.process(content)

        assert result == content
        mock_eos_service.record_signal.assert_awaited_once()


class TestMetadataExtraction:
    """Test extraction of metadata fields."""

    @pytest.mark.asyncio
    async def test_extracts_protocol_and_backend(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that protocol and backend are extracted from metadata."""
        content = StreamingContent(
            content="test",
            metadata={
                "session_id": "test-123",
                "protocol": "openai",
                "backend_name": "openai",
                "request_id": "req-456",
            },
            is_done=True,
        )

        await processor.process(content)

        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.protocol == "openai"
        assert signal.backend == "openai"
        assert signal.request_id == "req-456"


class TestToolCallsSkipping:
    """Test that tool_calls finish_reason does not trigger EoS emission."""

    @pytest.mark.asyncio
    async def test_is_done_with_tool_calls_finish_reason_skips_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that is_done=True with finish_reason=tool_calls does NOT emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "tool_calls"},
            is_done=True,
        )

        result = await processor.process(content)

        assert result is content
        mock_eos_service.record_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finish_reason_tool_calls_in_metadata_skips_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that finish_reason=tool_calls in metadata does NOT emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "tool_calls"},
            is_done=False,
        )

        result = await processor.process(content)

        assert result is content
        mock_eos_service.record_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_finish_reason_tool_calls_in_content_dict_skips_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that finish_reason=tool_calls in content dict does NOT emit EoS."""
        content = StreamingContent(
            content={"finish_reason": "tool_calls", "choices": []},
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        result = await processor.process(content)

        assert result is content
        mock_eos_service.record_signal.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_is_done_with_stop_finish_reason_emits_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that is_done=True with finish_reason=stop DOES emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "stop"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL

    @pytest.mark.asyncio
    async def test_is_done_with_length_finish_reason_emits_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that is_done=True with finish_reason=length DOES emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "length"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL

    @pytest.mark.asyncio
    async def test_is_done_with_error_finish_reason_emits_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that is_done=True with finish_reason=error DOES emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123", "finish_reason": "error"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL

    @pytest.mark.asyncio
    async def test_is_done_without_finish_reason_emits_eos(
        self,
        processor: EndOfSessionStreamProcessor,
        mock_eos_service: MagicMock,
    ):
        """Test that is_done=True without finish_reason DOES emit EoS."""
        content = StreamingContent(
            content="test",
            metadata={"session_id": "test-123"},
            is_done=True,
        )

        await processor.process(content)

        mock_eos_service.record_signal.assert_awaited_once()
        signal = mock_eos_service.record_signal.call_args[0][0]
        assert signal.signal_type == EndOfSessionSignalType.DONE_SENTINEL
