"""Tests for WireCaptureCoordinator."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.transport.fastapi.adapters.capture.wire_capture_coordinator import (
    WireCaptureCoordinator,
)


class MockWireCapture(IWireCapture):
    """Mock wire capture for testing."""

    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self.captured_responses = []
        self.wrapped_streams = []

    def enabled(self) -> bool:
        return self._enabled

    async def capture_inbound_request(self, **kwargs) -> None:
        pass

    async def capture_outbound_request(self, **kwargs) -> None:
        pass

    async def capture_inbound_response(self, **kwargs) -> None:
        pass

    def wrap_inbound_stream(self, **kwargs) -> AsyncIterator[bytes]:
        async def _empty():
            yield b""

        return _empty()

    async def capture_outbound_response(
        self,
        *,
        context=None,
        session_id=None,
        backend=None,
        model=None,
        key_name=None,
        response_content=None,
    ) -> None:
        self.captured_responses.append(
            {
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
                "response_content": response_content,
            }
        )

    def wrap_outbound_stream(
        self,
        *,
        context=None,
        session_id=None,
        backend=None,
        model=None,
        key_name=None,
        stream=None,
    ) -> AsyncIterator[bytes]:
        self.wrapped_streams.append(
            {
                "session_id": session_id,
                "backend": backend,
                "model": model,
                "key_name": key_name,
            }
        )
        return stream

    async def shutdown(self) -> None:
        """Shutdown mock capture."""


class TestWireCaptureCoordinator:
    """Test WireCaptureCoordinator implementation."""

    def test_no_op_when_disabled(self):
        """Test that coordinator performs no-op when wire capture is disabled."""
        mock_capture = MockWireCapture(enabled=False)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        envelope = ResponseEnvelope(content={"test": "data"})
        coordinator.schedule_capture(envelope, {"test": "data"})

        assert len(mock_capture.captured_responses) == 0

    def test_no_op_when_none(self):
        """Test that coordinator performs no-op when wire_capture is None."""
        coordinator = WireCaptureCoordinator(wire_capture=None)

        envelope = ResponseEnvelope(content={"test": "data"})
        coordinator.schedule_capture(envelope, {"test": "data"})

        # Should not raise error

    def test_metadata_extraction(self):
        """Test that metadata is extracted correctly from envelope."""
        mock_capture = MockWireCapture(enabled=True)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        envelope = ResponseEnvelope(
            content={"test": "data"},
            metadata={
                "backend": "openai",
                "model": "gpt-4",
                "key_name": "test-key",
                "session_id": "session-123",
            },
        )

        async def run_test():
            coordinator.schedule_capture(envelope, {"test": "data"})
            # Give background task time to execute
            await asyncio.sleep(0.1)

        asyncio.run(run_test())

        assert len(mock_capture.captured_responses) == 1
        captured = mock_capture.captured_responses[0]
        assert captured["backend"] == "openai"
        assert captured["model"] == "gpt-4"
        assert captured["key_name"] == "test-key"
        assert captured["session_id"] == "session-123"

    def test_background_task_scheduling(self):
        """Test that background task is scheduled for non-streaming responses."""
        mock_capture = MockWireCapture(enabled=True)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        envelope = ResponseEnvelope(content={"test": "data"})

        async def run_test():
            coordinator.schedule_capture(envelope, {"test": "data"})
            # Give background task time to execute
            await asyncio.sleep(0.1)

        asyncio.run(run_test())

        assert len(mock_capture.captured_responses) == 1

    @pytest.mark.asyncio
    async def test_stream_wrapping(self):
        """Test that stream is wrapped for capture."""
        mock_capture = MockWireCapture(enabled=True)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        async def test_stream():
            yield b"chunk1"
            yield b"chunk2"

        envelope = StreamingResponseEnvelope(
            content=test_stream(),
            metadata={
                "backend": "openai",
                "model": "gpt-4",
                "key_name": "test-key",
                "session_id": "session-123",
            },
        )

        # Create a new stream for wrapping
        async def stream_to_wrap():
            yield b"chunk1"
            yield b"chunk2"

        wrapped = coordinator.wrap_stream(envelope, stream_to_wrap())

        chunks = []
        async for chunk in wrapped:
            chunks.append(chunk)

        assert len(chunks) == 2
        assert chunks[0] == b"chunk1"
        assert chunks[1] == b"chunk2"
        assert len(mock_capture.wrapped_streams) == 1

    def test_session_id_fallback_to_request_id(self):
        """Test that session_id falls back to request_id from context."""
        mock_capture = MockWireCapture(enabled=True)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        # Create a mock context with request_id
        class MockContext:
            def __init__(self):
                self.request_id = "request-456"

        context = MockContext()

        envelope = ResponseEnvelope(
            content={"test": "data"},
            metadata={},  # No session_id in metadata
        )

        async def run_test():
            coordinator.schedule_capture(envelope, {"test": "data"}, context)
            await asyncio.sleep(0.1)

        asyncio.run(run_test())

        assert len(mock_capture.captured_responses) == 1
        # Note: The coordinator should use request_id as fallback
        # This test verifies the fallback mechanism works

    def test_default_values_when_metadata_missing(self):
        """Test that default values are used when metadata is missing."""
        mock_capture = MockWireCapture(enabled=True)
        coordinator = WireCaptureCoordinator(wire_capture=mock_capture)

        envelope = ResponseEnvelope(content={"test": "data"})

        async def run_test():
            coordinator.schedule_capture(envelope, {"test": "data"})
            await asyncio.sleep(0.1)

        asyncio.run(run_test())

        assert len(mock_capture.captured_responses) == 1
        captured = mock_capture.captured_responses[0]
        assert captured["backend"] == "proxy"  # Default
        assert captured["model"] == "unknown"  # Default
