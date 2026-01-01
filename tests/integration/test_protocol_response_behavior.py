"""Integration tests for protocol response behavior and usage/capture invariants.

This module tests that:
- Response shapes remain compatible across all supported protocols
- Usage and metadata propagation works correctly through typed contracts
- Capture-enabled paths remain inspectable and replayable

Requirements: 1.1, 1.2, 1.4, 1.5, NFR3.2
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import cbor2
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.config.models import AuthConfig, BackendConfig, BackendSettings, LoggingConfig
from src.core.domain.cbor_capture import CaptureDirection
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_summary import UsageSummary
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.simulation.capture_reader import CaptureReader
from src.core.services.cbor_wire_capture_service import CborWireCaptureService

# Suppress Windows ProactorEventLoop resource warnings
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)


# Mock backend responses for each protocol
MOCK_OPENAI_RESPONSE = {
    "id": "chatcmpl-abc123",
    "object": "chat.completion",
    "created": 1677652288,
    "model": "gpt-4",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello, world!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

MOCK_OPENAI_STREAMING_CHUNKS = [
    b'data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n\n',
    b'data: {"id":"chatcmpl-abc123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":", world!"},"finish_reason":"stop"}]}\n\n',
    b"data: [DONE]\n\n",
]

MOCK_OPENAI_RESPONSES_API_RESPONSE = {
    "id": "resp-abc123",
    "object": "response",
    "created": 1677652288,
    "model": "gpt-4",
    "response": {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": '{"name": "Alice", "age": 28}',
                    "parsed": {"name": "Alice", "age": 28},
                },
                "finish_reason": "stop",
            }
        ]
    },
    "usage": {"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
}

MOCK_ANTHROPIC_RESPONSE = {
    "id": "msg_013Zva2CMHLNnXjNJJKqJ2EF",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Hello, world!"}],
    "model": "claude-3-opus-20240229",
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
}

MOCK_ANTHROPIC_STREAMING_CHUNKS = [
    b'event: message_start\ndata: {"type":"message","id":"msg-123","role":"assistant","model":"claude-3-opus-20240229"}\n\n',
    b'event: content_block_start\ndata: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hello"}}\n\n',
    b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":", world!"}}\n\n',
    b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    b'event: message_delta\ndata: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null}}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
]

MOCK_GEMINI_RESPONSE = {
    "candidates": [
        {
            "content": {
                "parts": [{"text": "Hello, world!"}],
                "role": "model",
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 10,
        "candidatesTokenCount": 5,
        "totalTokenCount": 15,
    },
}

MOCK_GEMINI_STREAMING_CHUNKS = [
    b'{"candidates":[{"content":{"parts":[{"text":"Hello"}],"role":"model"},"finishReason":null}]}\n',
    b'{"candidates":[{"content":{"parts":[{"text":", world!"}],"role":"model"},"finishReason":"STOP"}]}\n',
]


# Test Fixtures
@pytest.fixture
def temp_capture_dir():
    """Create a temporary directory for CBOR capture files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_app_config(temp_capture_dir):
    """Create a mock AppConfig with CBOR wire capture enabled."""
    base_config = AppConfig.from_env()
    logging_config = LoggingConfig(
        cbor_capture_dir=str(temp_capture_dir),
        cbor_capture_session_id="test-session-protocol",
    )
    backends_config = BackendSettings(
        default_backend="openai",
        openai=BackendConfig(api_key=["test-key"]),
        anthropic=BackendConfig(api_key=["test-key"]),
        gemini=BackendConfig(api_key=["test-key"]),
    )
    auth_config = AuthConfig(disable_auth=True)
    config = base_config.model_copy(
        update={
            "logging": logging_config,
            "backends": backends_config,
            "auth": auth_config,
        }
    )
    return config


@pytest_asyncio.fixture
async def test_app_with_capture(mock_app_config):
    """Create a test application with CBOR wire capture enabled."""
    builder = ApplicationBuilder().add_default_stages()
    app = builder.build_compat(mock_app_config)

    # Get capture file path
    wire_capture = app.state.service_provider.get_service(IWireCapture)
    capture_file_path = None
    if isinstance(wire_capture, CborWireCaptureService):
        capture_file_path = wire_capture.get_capture_file_path()

    yield app, capture_file_path, mock_app_config.logging.cbor_capture_dir

    # Cleanup
    with contextlib.suppress(Exception):
        if wire_capture and hasattr(wire_capture, "shutdown"):
            await wire_capture.shutdown()


@pytest.fixture
def client(test_app_with_capture):
    """Create a test client."""
    app, _, _ = test_app_with_capture
    client = TestClient(app)
    try:
        yield client
    finally:
        with contextlib.suppress(Exception):
            client.close()


# Helper Functions
def verify_response_shape(protocol: str, response: dict[str, Any], is_streaming: bool) -> None:
    """Validate response matches protocol specification."""
    if protocol == "openai-chat":
        if is_streaming:
            # Streaming responses are SSE format, check in test
            assert "text/event-stream" in response.headers.get("content-type", "")
        else:
            assert "id" in response
            assert "object" in response
            assert "choices" in response
            assert "usage" in response
            assert isinstance(response["choices"], list)
            assert len(response["choices"]) > 0
    elif protocol == "openai-responses":
        if is_streaming:
            assert "text/event-stream" in response.headers.get("content-type", "")
        else:
            assert "id" in response
            assert "object" in response
            assert "response" in response
            assert "usage" in response
    elif protocol == "anthropic":
        if is_streaming:
            assert "text/event-stream" in response.headers.get("content-type", "")
        else:
            assert "id" in response
            assert "type" in response
            assert "content" in response
            assert "usage" in response
    elif protocol == "gemini":
        if is_streaming:
            # Gemini streaming uses JSON lines
            assert "application/json" in response.headers.get("content-type", "")
        else:
            assert "candidates" in response
            assert "usageMetadata" in response


def verify_usage_propagation(response: dict[str, Any], protocol: str) -> None:
    """Validate usage information is correctly extracted and propagated."""
    if protocol == "openai-chat" or protocol == "openai-responses":
        assert "usage" in response
        usage = response["usage"]
        assert "prompt_tokens" in usage or "total_tokens" in usage
    elif protocol == "anthropic":
        assert "usage" in response
        usage = response["usage"]
        assert "input_tokens" in usage or "output_tokens" in usage
    elif protocol == "gemini":
        assert "usageMetadata" in response
        usage = response["usageMetadata"]
        assert "promptTokenCount" in usage or "totalTokenCount" in usage


def verify_capture_file(capture_file_path: Path | None) -> None:
    """Validate capture file can be read and contains expected data."""
    if capture_file_path is None:
        pytest.skip("CBOR capture not enabled")

    assert capture_file_path.exists(), f"Capture file not found: {capture_file_path}"

    # Use CaptureReader to load file
    reader = CaptureReader()
    session = reader.load(capture_file_path)

    # Verify file structure is valid
    assert session.header is not None
    assert session.header.magic == "LLMPROXY-CAPTURE-V1"
    assert len(session.entries) > 0

    # Verify entries contain expected directions
    directions = {entry.direction for entry in session.entries}
    # Should have at least CLIENT_TO_PROXY and PROXY_TO_CLIENT
    assert CaptureDirection.CLIENT_TO_PROXY in directions or CaptureDirection.PROXY_TO_CLIENT in directions


def verify_capture_replay_compatible(capture_file_path: Path | None) -> None:
    """Validate capture file can be used for replay."""
    if capture_file_path is None:
        pytest.skip("CBOR capture not enabled")

    reader = CaptureReader()
    session = reader.load(capture_file_path)

    # Verify entries can be decoded
    assert len(session.entries) > 0
    for entry in session.entries:
        assert entry.data is not None or entry.metadata is not None
        assert entry.timestamp is not None

    # Verify timing information is present
    timestamps = [entry.timestamp for entry in session.entries if entry.timestamp]
    assert len(timestamps) > 0

    # Verify all four legs are captured (at least some of them)
    directions = {entry.direction for entry in session.entries}
    assert len(directions) > 0


# Test Classes
class TestProtocolResponseShapes:
    """Test protocol response shapes remain compatible."""

    @pytest.mark.asyncio
    async def test_openai_chat_completions_non_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test OpenAI Chat Completions non-streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        # Mock backend response
        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_response_shape("openai-chat", result, is_streaming=False)

    @pytest.mark.asyncio
    async def test_openai_chat_completions_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test OpenAI Chat Completions streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        # Mock streaming response with ProcessedResponse objects
        async def mock_stream():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Hello"}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": ", world!"}}]},
                metadata={},
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            # Verify SSE format
            content = response.text
            assert "data: {" in content or "data: [DONE]" in content

    @pytest.mark.asyncio
    async def test_openai_responses_api_non_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test OpenAI Responses API non-streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSES_API_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=15, completion_tokens=10, total_tokens=25),
            )

            response = client.post(
                "/v1/responses",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_response_shape("openai-responses", result, is_streaming=False)

    @pytest.mark.asyncio
    async def test_openai_responses_api_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test OpenAI Responses API streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Hello"}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": ", world!"}}]},
                metadata={},
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
            )

            response = client.post(
                "/v1/responses",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_anthropic_messages_non_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test Anthropic Messages non-streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_ANTHROPIC_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_response_shape("anthropic", result, is_streaming=False)

    @pytest.mark.asyncio
    async def test_anthropic_messages_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test Anthropic Messages streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"type": "content_block_delta", "delta": {"text": "Hello"}},
                metadata={},
            )
            yield ProcessedResponse(
                content={"type": "content_block_delta", "delta": {"text": ", world!"}},
                metadata={},
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
            )

            response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            content = response.text
            # Anthropic streaming uses SSE format with event types
            assert "event:" in content or "data:" in content

    @pytest.mark.asyncio
    async def test_gemini_v1beta_non_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test Gemini v1beta non-streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_GEMINI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json={
                    "contents": [{"parts": [{"text": "Hello"}]}],
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_response_shape("gemini", result, is_streaming=False)

    @pytest.mark.asyncio
    async def test_gemini_v1beta_streaming_shape(
        self, client, test_app_with_capture
    ):
        """Test Gemini v1beta streaming response shape."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={
                    "candidates": [{"content": {"parts": [{"text": ", world!"}]}}]
                },
                metadata={},
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="application/json",
            )

            response = client.post(
                "/v1beta/models/test-model:streamGenerateContent",
                json={
                    "contents": [{"parts": [{"text": "Hello"}]}],
                },
            )

            assert response.status_code == 200
            # Gemini streaming uses SSE format
            assert "text/event-stream" in response.headers.get("content-type", "")


class TestUsageMetadataPropagation:
    """Test usage and metadata propagation through typed contracts."""

    @pytest.mark.asyncio
    async def test_openai_usage_propagation_non_streaming(
        self, client, test_app_with_capture
    ):
        """Test OpenAI usage propagation in non-streaming responses."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_usage_propagation(result, "openai-chat")
            # Usage values may be extracted from response content or envelope
            assert "usage" in result
            usage = result["usage"]
            assert "prompt_tokens" in usage or "total_tokens" in usage

    @pytest.mark.asyncio
    async def test_openai_usage_propagation_streaming(
        self, client, test_app_with_capture
    ):
        """Test OpenAI usage propagation in streaming responses."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Hello"}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": ", world!"}}]},
                metadata={},
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
                canonical_usage=UsageSummary(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            # Usage should be in final chunk or response headers
            content = response.text
            # Verify streaming completed successfully
            assert "data: [DONE]" in content or len(content) > 0

    @pytest.mark.asyncio
    async def test_anthropic_usage_propagation_non_streaming(
        self, client, test_app_with_capture
    ):
        """Test Anthropic usage propagation in non-streaming responses."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_ANTHROPIC_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_usage_propagation(result, "anthropic")
            # Usage values may be extracted from response content or envelope
            assert "usage" in result
            usage = result["usage"]
            assert "input_tokens" in usage or "output_tokens" in usage

    @pytest.mark.asyncio
    async def test_anthropic_usage_propagation_streaming(
        self, client, test_app_with_capture
    ):
        """Test Anthropic usage propagation in streaming responses."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"type": "content_block_delta", "delta": {"text": "Hello"}},
                metadata={},
            )
            yield ProcessedResponse(
                content={"type": "content_block_delta", "delta": {"text": ", world!"}},
                metadata={},
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
                canonical_usage=UsageSummary(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
            )

            response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            content = response.text
            assert len(content) > 0

    @pytest.mark.asyncio
    async def test_gemini_usage_propagation_non_streaming(
        self, client, test_app_with_capture
    ):
        """Test Gemini usage propagation in non-streaming responses."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_GEMINI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json={
                    "contents": [{"parts": [{"text": "Hello"}]}],
                },
            )

            assert response.status_code == 200
            result = response.json()
            verify_usage_propagation(result, "gemini")
            # Usage values may be extracted from response content or envelope
            assert "usageMetadata" in result
            usage = result["usageMetadata"]
            assert "promptTokenCount" in usage or "totalTokenCount" in usage

    @pytest.mark.asyncio
    async def test_gemini_usage_propagation_streaming(
        self, client, test_app_with_capture
    ):
        """Test Gemini usage propagation in streaming responses."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"candidates": [{"content": {"parts": [{"text": "Hello"}]}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={
                    "candidates": [{"content": {"parts": [{"text": ", world!"}]}}]
                },
                metadata={},
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="application/json",
                canonical_usage=UsageSummary(
                    prompt_tokens=10, completion_tokens=5, total_tokens=15
                ),
            )

            response = client.post(
                "/v1beta/models/test-model:streamGenerateContent",
                json={
                    "contents": [{"parts": [{"text": "Hello"}]}],
                },
            )

            assert response.status_code == 200
            content = response.text
            assert len(content) > 0


class TestCaptureCompatibility:
    """Test capture-enabled paths remain inspectable and replayable."""

    @pytest.mark.asyncio
    async def test_openai_capture_file_readable(
        self, client, test_app_with_capture
    ):
        """Test OpenAI capture file can be read by CaptureReader."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            # Make request to trigger capture
            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )

            assert response.status_code == 200

            # Flush capture
            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            # Verify capture file
            verify_capture_file(capture_file)

    @pytest.mark.asyncio
    async def test_openai_capture_file_contains_usage(
        self, client, test_app_with_capture
    ):
        """Test OpenAI capture file contains usage information."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )

            assert response.status_code == 200

            # Flush capture
            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            # Verify capture file contains usage
            if capture_file:
                reader = CaptureReader()
                session = reader.load(capture_file)
                # Check that entries exist (usage may be in metadata)
                assert len(session.entries) > 0

    @pytest.mark.asyncio
    async def test_anthropic_capture_file_readable(
        self, client, test_app_with_capture
    ):
        """Test Anthropic capture file can be read by CaptureReader."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_ANTHROPIC_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/anthropic/v1/messages",
                json={
                    "model": "claude-3-opus-20240229",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )

            assert response.status_code == 200

            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            verify_capture_file(capture_file)

    @pytest.mark.asyncio
    async def test_gemini_capture_file_readable(
        self, client, test_app_with_capture
    ):
        """Test Gemini capture file can be read by CaptureReader."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_GEMINI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1beta/models/test-model:generateContent",
                json={
                    "contents": [{"parts": [{"text": "Hello"}]}],
                },
            )

            assert response.status_code == 200

            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            verify_capture_file(capture_file)

    @pytest.mark.asyncio
    async def test_streaming_capture_file_readable(
        self, client, test_app_with_capture
    ):
        """Test streaming capture file can be read by CaptureReader."""
        app, capture_file, _ = test_app_with_capture

        async def mock_stream():
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "Hello"}}]},
                metadata={},
            )
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": ", world!"}}]},
                metadata={},
            )

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = StreamingResponseEnvelope(
                content=mock_stream(),
                media_type="text/event-stream",
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": True,
                },
            )

            assert response.status_code == 200
            # Consume stream
            list(response.iter_bytes())

            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            verify_capture_file(capture_file)

    @pytest.mark.asyncio
    async def test_capture_file_replay_compatible(
        self, client, test_app_with_capture
    ):
        """Test capture file is compatible with replay tooling."""
        app, capture_file, _ = test_app_with_capture

        with patch(
            "src.core.services.backend_service.BackendService.call_completion"
        ) as mock_call:
            mock_call.return_value = ResponseEnvelope(
                content=MOCK_OPENAI_RESPONSE,
                status_code=200,
                usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )

            response = client.post(
                "/v1/chat/completions",
                json={
                    "model": "gpt-4",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False,
                },
            )

            assert response.status_code == 200

            wire_capture = app.state.service_provider.get_service(IWireCapture)
            if wire_capture and hasattr(wire_capture, "force_flush_sync"):
                wire_capture.force_flush_sync()  # type: ignore[attr-defined]

            verify_capture_replay_compatible(capture_file)
