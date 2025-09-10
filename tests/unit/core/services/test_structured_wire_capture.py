import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.request_context import RequestContext
from src.core.services.structured_wire_capture_service import StructuredWireCapture


@pytest.fixture
def mock_config():
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock()
    config.logging.capture_max_bytes = None
    config.logging.capture_truncate_bytes = None
    config.logging.capture_max_files = 0
    config.logging.capture_rotate_interval_seconds = 0
    config.logging.capture_total_max_bytes = 0
    return config


@pytest.fixture
def temp_capture_file():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = f.name
    yield temp_path
    # Clean up after the test
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
def structured_wire_capture(mock_config, temp_capture_file):
    # Clear the file before each test
    open(temp_capture_file, "w").close()
    mock_config.logging.capture_file = temp_capture_file
    return StructuredWireCapture(mock_config)


def test_enabled(structured_wire_capture):
    """Test that the capture service is enabled when a file path is provided."""
    assert structured_wire_capture.enabled() is True

    # Test when file path is None
    structured_wire_capture._file_path = None
    assert structured_wire_capture.enabled() is False


@pytest.mark.asyncio
async def test_capture_outbound_request(structured_wire_capture):
    """Test capturing an outbound request."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
        session_id="test-session",
        agent="test-agent",
    )

    request_payload = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, world!"},
        ]
    }

    await structured_wire_capture.capture_outbound_request(
        context=context,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload=request_payload,
    )

    # Read the file and check the content
    with open(structured_wire_capture._file_path) as f:
        content = f.read()
        entry = json.loads(content)

        # Check structure
        assert "timestamp" in entry
        assert "iso" in entry["timestamp"]
        assert "human_readable" in entry["timestamp"]

        # Check communication
        assert entry["communication"]["flow"] == "frontend_to_backend"
        assert entry["communication"]["direction"] == "request"
        assert entry["communication"]["source"] == "127.0.0.1"
        assert entry["communication"]["destination"] == "openai"

        # Check metadata
        assert entry["metadata"]["session_id"] == "test-session"
        assert entry["metadata"]["agent"] == "test-agent"
        assert entry["metadata"]["backend"] == "openai"
        assert entry["metadata"]["model"] == "gpt-4"
        assert entry["metadata"]["key_name"] == "OPENAI_API_KEY"
        assert isinstance(entry["metadata"]["byte_count"], int)
        assert entry["metadata"]["byte_count"] > 0

        # Check payload
        assert entry["payload"] == request_payload

        # Check system prompt extraction
        assert entry["metadata"]["system_prompt"] == "You are a helpful assistant."


@pytest.mark.asyncio
async def test_capture_inbound_response(structured_wire_capture):
    """Test capturing an inbound response."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
        session_id="test-session",
        agent="test-agent",
    )

    response_content = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello there, how can I help you today?",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
    }

    await structured_wire_capture.capture_inbound_response(
        context=context,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content=response_content,
    )

    # Read the file and check for the response entry
    with open(structured_wire_capture._file_path) as f:
        lines = f.readlines()
        assert len(lines) == 1  # One entry for this test

        entry = json.loads(lines[0])

        # Check communication flow
        assert entry["communication"]["flow"] == "backend_to_frontend"
        assert entry["communication"]["direction"] == "response"
        assert entry["communication"]["source"] == "openai"
        assert entry["communication"]["destination"] == "127.0.0.1"

        # Check payload
        assert entry["payload"] == response_content


class MockStream:
    """Mock for async stream iterator."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.chunks):
            raise StopAsyncIteration
        chunk = self.chunks[self.index]
        self.index += 1
        return chunk


@pytest.mark.asyncio
async def test_wrap_inbound_stream(structured_wire_capture):
    """Test wrapping an inbound stream."""
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
        session_id="test-session",
        agent="test-agent",
    )

    # Create mock stream
    chunks = [
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\\n',
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":" there"},"finish_reason":null}]}\\n',
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","created":1677652288,"model":"gpt-4","choices":[{"index":0,"delta":{"content":"!"},"finish_reason":"stop"}]}\\n',
    ]

    mock_stream = MockStream(chunks)

    wrapped_stream = structured_wire_capture.wrap_inbound_stream(
        context=context,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        stream=mock_stream,
    )

    # Consume the stream
    result_chunks = []
    async for chunk in wrapped_stream:
        result_chunks.append(chunk)

    # Verify the returned chunks are unchanged
    assert result_chunks == chunks

    # Check the file for stream-related entries
    with open(structured_wire_capture._file_path) as f:
        lines = f.readlines()

        # We should have stream entries
        # 1. Stream start entry
        # 2. Stream chunk entries (3)
        # 3. Stream end entry
        assert len(lines) == 5

        # Check stream start entry
        stream_start = json.loads(lines[0])
        assert stream_start["communication"]["direction"] == "response_stream_start"

        # Check stream chunks
        for i in range(3):
            chunk_entry = json.loads(lines[1 + i])
            assert chunk_entry["communication"]["direction"] == "response_stream_chunk"
            assert chunk_entry["metadata"]["byte_count"] == len(chunks[i])

        # Check stream end entry
        stream_end = json.loads(lines[4])
        assert stream_end["communication"]["direction"] == "response_stream_end"
        total_bytes = sum(len(chunk) for chunk in chunks)
        assert stream_end["metadata"]["byte_count"] == total_bytes


def test_extract_system_prompt(structured_wire_capture):
    """Test system prompt extraction from different formats."""
    # OpenAI format
    openai_payload = {
        "messages": [
            {"role": "system", "content": "You are an OpenAI assistant."},
            {"role": "user", "content": "Hello"},
        ]
    }
    assert (
        structured_wire_capture._extract_system_prompt(openai_payload)
        == "You are an OpenAI assistant."
    )

    # Anthropic format
    anthropic_payload = {
        "system": "You are an Anthropic assistant.",
        "messages": [{"role": "user", "content": "Hello"}],
    }
    assert (
        structured_wire_capture._extract_system_prompt(anthropic_payload)
        == "You are an Anthropic assistant."
    )

    # Gemini format
    gemini_payload = {
        "contents": [
            {"role": "system", "parts": [{"text": "You are a Gemini assistant."}]},
            {"role": "user", "parts": [{"text": "Hello"}]},
        ]
    }
    assert (
        structured_wire_capture._extract_system_prompt(gemini_payload)
        == "You are a Gemini assistant."
    )

    # No system prompt
    no_system_payload = {"messages": [{"role": "user", "content": "Hello"}]}
    assert structured_wire_capture._extract_system_prompt(no_system_payload) is None
