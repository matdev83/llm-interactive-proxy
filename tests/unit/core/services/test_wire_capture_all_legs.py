"""
Integration tests to verify CBOR wire capture captures ALL FOUR communication legs.

These tests ensure that the wire capture service properly captures:
- CLIENT_TO_PROXY: Inbound requests from clients
- PROXY_TO_BACKEND: Outbound requests to LLM backends
- BACKEND_TO_PROXY: Inbound responses from backends
- PROXY_TO_CLIENT: Outbound responses to clients

If any leg is not captured, these tests should fail, providing early detection
of wire capture degradation.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import cbor2
import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.cbor_capture import CaptureDirection
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.request_processor_interface import IRequestProcessor
from src.core.services.cbor_wire_capture_service import CborWireCaptureService


def _read_cbor_entries(file_path: Path) -> list[dict[str, Any]]:
    """Helper to read all CBOR entries from a file."""
    entries = []
    with open(file_path, "rb") as f:
        while True:
            try:
                entries.append(cbor2.load(f))
            except cbor2.CBORDecodeEOF:
                break
    return entries


def _count_entries_by_direction(
    entries: list[dict[str, Any]],
) -> dict[CaptureDirection, int]:
    """Count entries by direction."""
    counts: dict[CaptureDirection, int] = {
        CaptureDirection.CLIENT_TO_PROXY: 0,
        CaptureDirection.PROXY_TO_BACKEND: 0,
        CaptureDirection.BACKEND_TO_PROXY: 0,
        CaptureDirection.PROXY_TO_CLIENT: 0,
    }
    for entry in entries:
        if isinstance(entry, dict) and "dir" in entry:
            direction = entry["dir"]
            if direction in [d.value for d in CaptureDirection]:
                counts[CaptureDirection(direction)] += 1
    return counts


@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig."""
    return AppConfig.from_env()


@pytest.fixture
async def capture_service(mock_config, temp_capture_dir):
    """Create a CborWireCaptureService for testing."""
    service = CborWireCaptureService(
        config=mock_config,
        capture_dir=temp_capture_dir,
        session_id="all-legs-test",
    )
    yield service
    await service.shutdown()


class TestAllFourLegsCapture:
    """Tests verifying all 4 communication legs are captured."""

    @pytest.mark.asyncio
    async def test_complete_non_streaming_cycle_captures_all_legs(
        self, capture_service: CborWireCaptureService
    ):
        """
        Test that a complete non-streaming request-response cycle captures all 4 legs.

        Expected flow:
        1. CLIENT_TO_PROXY: Client sends request
        2. PROXY_TO_BACKEND: Proxy forwards to backend
        3. BACKEND_TO_PROXY: Backend responds
        4. PROXY_TO_CLIENT: Proxy responds to client
        """
        session_id = "non-streaming-test"

        # Leg 1: Client -> Proxy (inbound request)
        await capture_service.capture_inbound_request(
            context=None,
            session_id=session_id,
            request_payload={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Hello"}],
            },
            raw_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}',
        )

        # Leg 2: Proxy -> Backend (outbound request)
        await capture_service.capture_outbound_request(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            request_payload=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "Hello"}]}',
        )

        # Leg 3: Backend -> Proxy (inbound response)
        await capture_service.capture_inbound_response(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            response_content={"choices": [{"message": {"content": "Hi there!"}}]},
        )

        # Leg 4: Proxy -> Client (outbound response)
        await capture_service.capture_outbound_response(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name=None,
            response_content=b'{"choices": [{"message": {"content": "Hi there!"}}]}',
        )

        # Force flush and read entries
        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # Assert ALL 4 legs have at least 1 entry
        assert (
            counts[CaptureDirection.CLIENT_TO_PROXY] >= 1
        ), "CLIENT_TO_PROXY leg not captured! Wire capture is missing inbound requests."
        assert (
            counts[CaptureDirection.PROXY_TO_BACKEND] >= 1
        ), "PROXY_TO_BACKEND leg not captured! Wire capture is missing outbound backend requests."
        assert (
            counts[CaptureDirection.BACKEND_TO_PROXY] >= 1
        ), "BACKEND_TO_PROXY leg not captured! Wire capture is missing backend responses."
        assert (
            counts[CaptureDirection.PROXY_TO_CLIENT] >= 1
        ), "PROXY_TO_CLIENT leg not captured! Wire capture is missing outbound client responses."

    @pytest.mark.asyncio
    async def test_complete_streaming_cycle_captures_all_legs(
        self, capture_service: CborWireCaptureService
    ):
        """
        Test that a complete streaming request-response cycle captures all 4 legs.

        For streaming:
        - CLIENT_TO_PROXY: Single request entry
        - PROXY_TO_BACKEND: Single request entry
        - BACKEND_TO_PROXY: Stream start + chunks + stream end
        - PROXY_TO_CLIENT: Stream start + chunks + stream end
        """
        session_id = "streaming-test"

        # Leg 1: Client -> Proxy (inbound request)
        await capture_service.capture_inbound_request(
            context=None,
            session_id=session_id,
            request_payload={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "Stream test"}],
                "stream": True,
            },
            raw_body=b'{"model": "gpt-4", "messages": [{"role": "user", "content": "Stream test"}], "stream": true}',
        )

        # Leg 2: Proxy -> Backend (outbound request)
        await capture_service.capture_outbound_request(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            request_payload=b'{"model": "gpt-4", "messages": [...], "stream": true}',
        )

        # Leg 3: Backend -> Proxy (streaming response)
        backend_chunks = [b"data: chunk1\n\n", b"data: chunk2\n\n", b"data: [DONE]\n\n"]

        async def mock_backend_stream():
            for chunk in backend_chunks:
                yield chunk

        wrapped_backend_stream = capture_service.wrap_inbound_stream(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            stream=mock_backend_stream(),
        )

        # Consume backend stream
        backend_received = []
        async for chunk in wrapped_backend_stream:
            backend_received.append(chunk)
        assert backend_received == backend_chunks

        # Leg 4: Proxy -> Client (streaming response)
        client_chunks = [
            b"data: processed1\n\n",
            b"data: processed2\n\n",
            b"data: [DONE]\n\n",
        ]

        async def mock_client_stream():
            for chunk in client_chunks:
                yield chunk

        wrapped_client_stream = capture_service.wrap_outbound_stream(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name=None,
            stream=mock_client_stream(),
        )

        # Consume client stream
        client_received = []
        async for chunk in wrapped_client_stream:
            client_received.append(chunk)
        assert client_received == client_chunks

        # Force flush and read entries
        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # Assert ALL 4 legs have entries
        assert (
            counts[CaptureDirection.CLIENT_TO_PROXY] >= 1
        ), "CLIENT_TO_PROXY leg not captured in streaming cycle!"
        assert (
            counts[CaptureDirection.PROXY_TO_BACKEND] >= 1
        ), "PROXY_TO_BACKEND leg not captured in streaming cycle!"
        # Streaming has start marker + chunks + end marker = at least 5 entries
        assert counts[CaptureDirection.BACKEND_TO_PROXY] >= 5, (
            f"BACKEND_TO_PROXY leg missing entries in streaming cycle! "
            f"Expected >= 5 (start + 3 chunks + end), got {counts[CaptureDirection.BACKEND_TO_PROXY]}"
        )
        assert counts[CaptureDirection.PROXY_TO_CLIENT] >= 5, (
            f"PROXY_TO_CLIENT leg missing entries in streaming cycle! "
            f"Expected >= 5 (start + 3 chunks + end), got {counts[CaptureDirection.PROXY_TO_CLIENT]}"
        )

    @pytest.mark.asyncio
    async def test_multiple_requests_all_legs_captured(
        self, capture_service: CborWireCaptureService
    ):
        """
        Test that multiple consecutive requests all have their 4 legs captured.
        """
        num_requests = 3

        for i in range(num_requests):
            session_id = f"multi-request-{i}"

            await capture_service.capture_inbound_request(
                context=None,
                session_id=session_id,
                request_payload={"model": "gpt-4", "prompt": f"Request {i}"},
            )
            await capture_service.capture_outbound_request(
                context=None,
                session_id=session_id,
                backend="openai",
                model="gpt-4",
                key_name="KEY",
                request_payload=f"backend request {i}".encode(),
            )
            await capture_service.capture_inbound_response(
                context=None,
                session_id=session_id,
                backend="openai",
                model="gpt-4",
                key_name="KEY",
                response_content=f"backend response {i}",
            )
            await capture_service.capture_outbound_response(
                context=None,
                session_id=session_id,
                backend="openai",
                model="gpt-4",
                key_name=None,
                response_content=f"client response {i}".encode(),
            )

        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # Each request should contribute 1 entry per leg
        assert (
            counts[CaptureDirection.CLIENT_TO_PROXY] == num_requests
        ), f"Expected {num_requests} CLIENT_TO_PROXY entries, got {counts[CaptureDirection.CLIENT_TO_PROXY]}"
        assert (
            counts[CaptureDirection.PROXY_TO_BACKEND] == num_requests
        ), f"Expected {num_requests} PROXY_TO_BACKEND entries, got {counts[CaptureDirection.PROXY_TO_BACKEND]}"
        assert (
            counts[CaptureDirection.BACKEND_TO_PROXY] == num_requests
        ), f"Expected {num_requests} BACKEND_TO_PROXY entries, got {counts[CaptureDirection.BACKEND_TO_PROXY]}"
        assert (
            counts[CaptureDirection.PROXY_TO_CLIENT] == num_requests
        ), f"Expected {num_requests} PROXY_TO_CLIENT entries, got {counts[CaptureDirection.PROXY_TO_CLIENT]}"


class TestControllerWireCaptureIntegration:
    """Tests verifying controllers properly integrate with wire capture for CLIENT_TO_PROXY."""

    @pytest.mark.asyncio
    async def test_anthropic_controller_captures_client_to_proxy(
        self, mock_config, temp_capture_dir
    ):
        """
        Test that AnthropicController properly captures CLIENT_TO_PROXY entries.

        This test verifies the fix for the wire_capture injection issue.
        """
        from src.core.app.controllers.anthropic_controller import AnthropicController

        # Create wire capture service
        wire_capture = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="anthropic-test",
        )

        # Create mock request processor
        mock_processor = MagicMock(spec=IRequestProcessor)
        mock_processor.process_request = AsyncMock(
            return_value=ResponseEnvelope(
                content={
                    "type": "message",
                    "content": [{"type": "text", "text": "Response"}],
                },
                status_code=200,
            )
        )

        # Create controller WITH wire_capture (this is the fix we're testing)
        controller = AnthropicController(mock_processor, wire_capture=wire_capture)

        # Verify wire capture is set
        assert controller._wire_capture is not None
        assert controller._wire_capture.enabled()

        await wire_capture.shutdown()

    @pytest.mark.asyncio
    async def test_chat_controller_captures_client_to_proxy(
        self, mock_config, temp_capture_dir
    ):
        """
        Test that ChatController properly captures CLIENT_TO_PROXY entries.
        """
        from src.core.app.controllers.chat_controller import ChatController

        # Create wire capture service
        wire_capture = CborWireCaptureService(
            config=mock_config,
            capture_dir=temp_capture_dir,
            session_id="chat-test",
        )

        # Create mock request processor
        mock_processor = MagicMock(spec=IRequestProcessor)
        mock_processor.process_request = AsyncMock(
            return_value=ResponseEnvelope(
                content={"choices": [{"message": {"content": "Hello"}}]},
                status_code=200,
            )
        )

        # Create controller with wire_capture
        controller = ChatController(mock_processor, wire_capture=wire_capture)

        # Verify wire capture is set
        assert controller._wire_capture is not None
        assert controller._wire_capture.enabled()

        await wire_capture.shutdown()


class TestLegCaptureFailureDetection:
    """Tests that verify capture failures are properly detected."""

    @pytest.mark.asyncio
    async def test_missing_client_to_proxy_fails(
        self, capture_service: CborWireCaptureService
    ):
        """Test that missing CLIENT_TO_PROXY leg is detected."""
        session_id = "missing-c2p-test"

        # Simulate only capturing 3 legs (missing CLIENT_TO_PROXY)
        await capture_service.capture_outbound_request(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="KEY",
            request_payload=b"request",
        )
        await capture_service.capture_inbound_response(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="KEY",
            response_content=b"response",
        )
        await capture_service.capture_outbound_response(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name=None,
            response_content=b"client response",
        )

        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # This should detect the missing leg
        assert (
            counts[CaptureDirection.CLIENT_TO_PROXY] == 0
        ), "This test expects CLIENT_TO_PROXY to be missing to verify detection"

    @pytest.mark.asyncio
    async def test_missing_proxy_to_client_fails(
        self, capture_service: CborWireCaptureService
    ):
        """Test that missing PROXY_TO_CLIENT leg is detected."""
        session_id = "missing-p2c-test"

        # Simulate only capturing 3 legs (missing PROXY_TO_CLIENT)
        await capture_service.capture_inbound_request(
            context=None,
            session_id=session_id,
            request_payload=b"request",
        )
        await capture_service.capture_outbound_request(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="KEY",
            request_payload=b"backend request",
        )
        await capture_service.capture_inbound_response(
            context=None,
            session_id=session_id,
            backend="openai",
            model="gpt-4",
            key_name="KEY",
            response_content=b"backend response",
        )

        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # This should detect the missing leg
        assert (
            counts[CaptureDirection.PROXY_TO_CLIENT] == 0
        ), "This test expects PROXY_TO_CLIENT to be missing to verify detection"


class TestLegCountValidation:
    """Tests that validate the exact count of entries per leg."""

    @pytest.mark.asyncio
    async def test_leg_count_matches_request_count(
        self, capture_service: CborWireCaptureService
    ):
        """
        Validate that each leg has exactly the expected number of entries.

        This is a critical test for detecting wire capture degradation.
        """
        expected_requests = 5

        for i in range(expected_requests):
            await capture_service.capture_inbound_request(
                context=None, session_id=f"req-{i}", request_payload=f"client-{i}"
            )
            await capture_service.capture_outbound_request(
                context=None,
                session_id=f"req-{i}",
                backend="be",
                model="m",
                key_name="k",
                request_payload=f"backend-{i}",
            )
            await capture_service.capture_inbound_response(
                context=None,
                session_id=f"req-{i}",
                backend="be",
                model="m",
                key_name="k",
                response_content=f"be-resp-{i}",
            )
            await capture_service.capture_outbound_response(
                context=None,
                session_id=f"req-{i}",
                backend="be",
                model="m",
                key_name=None,
                response_content=f"client-resp-{i}",
            )

        capture_service.force_flush_sync()
        file_path = capture_service.get_capture_file_path()
        entries = _read_cbor_entries(file_path)
        counts = _count_entries_by_direction(entries)

        # Strict validation - exact counts must match
        assert counts[CaptureDirection.CLIENT_TO_PROXY] == expected_requests, (
            f"CLIENT_TO_PROXY count mismatch: expected {expected_requests}, "
            f"got {counts[CaptureDirection.CLIENT_TO_PROXY]}. "
            "Wire capture may be degraded!"
        )
        assert counts[CaptureDirection.PROXY_TO_BACKEND] == expected_requests, (
            f"PROXY_TO_BACKEND count mismatch: expected {expected_requests}, "
            f"got {counts[CaptureDirection.PROXY_TO_BACKEND]}. "
            "Wire capture may be degraded!"
        )
        assert counts[CaptureDirection.BACKEND_TO_PROXY] == expected_requests, (
            f"BACKEND_TO_PROXY count mismatch: expected {expected_requests}, "
            f"got {counts[CaptureDirection.BACKEND_TO_PROXY]}. "
            "Wire capture may be degraded!"
        )
        assert counts[CaptureDirection.PROXY_TO_CLIENT] == expected_requests, (
            f"PROXY_TO_CLIENT count mismatch: expected {expected_requests}, "
            f"got {counts[CaptureDirection.PROXY_TO_CLIENT]}. "
            "Wire capture may be degraded!"
        )

        # Validate total entry count (header + 4 legs * requests)
        total_data_entries = sum(counts.values())
        assert total_data_entries == expected_requests * 4, (
            f"Total entry count mismatch: expected {expected_requests * 4}, "
            f"got {total_data_entries}"
        )
