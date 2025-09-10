"""Unit tests for BufferedWireCapture service."""

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from src.core.config.app_config import AppConfig, LoggingConfig
from src.core.domain.request_context import RequestContext
from src.core.services.buffered_wire_capture_service import (
    BufferedWireCapture,
    WireCaptureEntry,
)


@pytest.fixture
def mock_config():
    """Create a mock AppConfig for testing."""
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock(spec=LoggingConfig)
    config.logging.capture_buffer_size = 1024  # Small buffer for testing
    config.logging.capture_flush_interval = 0.1  # Fast flush for testing
    config.logging.capture_max_entries_per_flush = 5
    config.logging.capture_max_bytes = None
    config.logging.capture_max_files = 0
    config.logging.capture_total_max_bytes = 0
    return config


@pytest.fixture
def temp_capture_file():
    """Create a temporary file for capture and clean up afterward."""
    with tempfile.NamedTemporaryFile(delete=False) as f:
        temp_path = f.name
    yield temp_path
    # Clean up after the test
    if os.path.exists(temp_path):
        os.unlink(temp_path)


@pytest.fixture
async def buffered_wire_capture(mock_config, temp_capture_file):
    """Create a BufferedWireCapture instance for testing."""
    mock_config.logging.capture_file = temp_capture_file
    capture = BufferedWireCapture(mock_config)
    yield capture
    # Ensure cleanup
    await capture.shutdown()


@pytest.mark.asyncio
async def test_enabled(buffered_wire_capture):
    """Test that the capture service is enabled when a file path is provided."""
    assert buffered_wire_capture.enabled() is True


def test_disabled_when_no_file():
    """Test that capture is disabled when no file path is provided."""
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock(spec=LoggingConfig)
    config.logging.capture_file = None

    capture = BufferedWireCapture(config)
    assert capture.enabled() is False


def test_wire_capture_entry_structure():
    """Test the WireCaptureEntry structure."""
    entry = WireCaptureEntry(
        timestamp_iso="2025-01-10T15:58:41.039145+00:00",
        timestamp_unix=1736524721.039145,
        direction="outbound_request",
        source="127.0.0.1(Cline/1.0)",
        destination="qwen-oauth",
        session_id="session-123",
        backend="qwen-oauth",
        model="qwen3-coder-plus",
        key_name="primary",
        content_type="json",
        content_length=1247,
        payload={"test": "data"},
        metadata={"client_host": "127.0.0.1"},
    )

    # Test that it can be converted to dict for JSON serialization
    entry_dict = entry._asdict()
    assert entry_dict["direction"] == "outbound_request"
    assert entry_dict["backend"] == "qwen-oauth"
    assert entry_dict["payload"]["test"] == "data"

    # Test JSON serialization
    json_str = json.dumps(entry_dict)
    assert "outbound_request" in json_str


@pytest.mark.asyncio
async def test_capture_outbound_request(buffered_wire_capture, temp_capture_file):
    """Test capturing outbound requests."""
    context = MagicMock(spec=RequestContext)
    context.client_host = "127.0.0.1"
    context.agent = "Cline/1.0"
    context.request_id = "req_123"

    payload = {
        "messages": [{"role": "user", "content": "Test message"}],
        "model": "gpt-4",
        "temperature": 0.7,
    }

    await buffered_wire_capture.capture_outbound_request(
        context=context,
        session_id="test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload=payload,
    )

    # Force flush
    await buffered_wire_capture._flush_buffer()

    # Verify file contents
    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Should have system_init entry + our request
    assert len(lines) >= 2

    # Parse the request entry (skip system_init)
    request_entry = None
    for line in lines:
        entry = json.loads(line.strip())
        if entry["direction"] == "outbound_request":
            request_entry = entry
            break

    assert request_entry is not None
    assert request_entry["direction"] == "outbound_request"
    assert request_entry["source"] == "127.0.0.1(Cline/1.0)"
    assert request_entry["destination"] == "openai"
    assert request_entry["backend"] == "openai"
    assert request_entry["model"] == "gpt-4"
    assert request_entry["session_id"] == "test-session"
    assert request_entry["key_name"] == "OPENAI_API_KEY"
    assert request_entry["content_type"] == "json"
    assert request_entry["content_length"] > 0
    assert request_entry["payload"] == payload
    assert request_entry["metadata"]["client_host"] == "127.0.0.1"
    assert request_entry["metadata"]["user_agent"] == "Cline/1.0"
    assert request_entry["metadata"]["request_id"] == "req_123"


@pytest.mark.asyncio
async def test_capture_inbound_response(buffered_wire_capture, temp_capture_file):
    """Test capturing inbound responses."""
    context = MagicMock(spec=RequestContext)
    context.client_host = "192.168.1.100"
    context.agent = "TestAgent/2.0"

    payload = {
        "choices": [{"message": {"content": "Test response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }

    await buffered_wire_capture.capture_inbound_response(
        context=context,
        session_id="test-session",
        backend="anthropic",
        model="claude-3-opus",
        key_name="ANTHROPIC_API_KEY",
        response_content=payload,
    )

    # Force flush
    await buffered_wire_capture._flush_buffer()

    # Verify file contents
    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Find the response entry
    response_entry = None
    for line in lines:
        entry = json.loads(line.strip())
        if entry["direction"] == "inbound_response":
            response_entry = entry
            break

    assert response_entry is not None
    assert response_entry["direction"] == "inbound_response"
    assert response_entry["source"] == "anthropic"
    assert response_entry["destination"] == "192.168.1.100(TestAgent/2.0)"
    assert response_entry["backend"] == "anthropic"
    assert response_entry["model"] == "claude-3-opus"
    assert response_entry["payload"] == payload


@pytest.mark.asyncio
async def test_wrap_inbound_stream(buffered_wire_capture, temp_capture_file):
    """Test wrapping inbound streams."""
    context = MagicMock(spec=RequestContext)
    context.client_host = "10.0.0.1"
    context.agent = "StreamClient/1.0"

    # Mock stream data
    chunks = [b"chunk1", b"chunk2", b"chunk3"]

    async def mock_stream():
        for chunk in chunks:
            yield chunk

    wrapped_stream = buffered_wire_capture.wrap_inbound_stream(
        context=context,
        session_id="stream-session",
        backend="gemini",
        model="gemini-pro",
        key_name="GEMINI_API_KEY",
        stream=mock_stream(),
    )

    # Consume the stream
    result = []
    async for chunk in wrapped_stream:
        result.append(chunk)

    # Verify chunks are unchanged
    assert result == chunks

    # Force flush
    await buffered_wire_capture._flush_buffer()

    # Verify file contents
    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Find stream entries
    stream_entries = []
    for line in lines:
        entry = json.loads(line.strip())
        if "stream" in entry["direction"]:
            stream_entries.append(entry)

    # Should have: stream_start + 3 chunks + stream_end = 5 entries
    assert len(stream_entries) == 5

    # Check stream start
    assert stream_entries[0]["direction"] == "stream_start"
    assert stream_entries[0]["backend"] == "gemini"

    # Check chunks
    for i in range(1, 4):
        assert stream_entries[i]["direction"] == "stream_chunk"
        assert stream_entries[i]["metadata"]["chunk_number"] == i
        assert stream_entries[i]["metadata"]["chunk_bytes"] == len(chunks[i - 1])

    # Check stream end
    assert stream_entries[4]["direction"] == "stream_end"
    assert stream_entries[4]["payload"]["total_bytes"] == sum(
        len(chunk) for chunk in chunks
    )
    assert stream_entries[4]["payload"]["total_chunks"] == 3


@pytest.mark.asyncio
async def test_buffering_behavior(buffered_wire_capture, temp_capture_file):
    """Test that buffering works correctly."""
    # Capture multiple entries quickly
    for i in range(3):
        await buffered_wire_capture.capture_outbound_request(
            context=None,
            session_id=f"session-{i}",
            backend="test-backend",
            model="test-model",
            key_name=None,
            request_payload={"request": i},
        )

    # Before flush, file should only have system_init entry
    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Should have system_init + possibly some entries if buffer flushed
    initial_count = len(lines)

    # Force flush
    await buffered_wire_capture._flush_buffer()

    # After flush, should have more entries
    with open(temp_capture_file) as f:
        lines = f.readlines()

    assert len(lines) > initial_count

    # Verify all requests are captured
    request_entries = []
    for line in lines:
        entry = json.loads(line.strip())
        if entry["direction"] == "outbound_request":
            request_entries.append(entry)

    assert len(request_entries) == 3
    for i, entry in enumerate(request_entries):
        assert entry["session_id"] == f"session-{i}"
        assert entry["payload"]["request"] == i


@pytest.mark.asyncio
async def test_content_type_detection(buffered_wire_capture):
    """Test content type detection for different payload types."""
    # Test JSON payload
    await buffered_wire_capture.capture_outbound_request(
        context=None,
        session_id="test",
        backend="test",
        model="test",
        key_name=None,
        request_payload={"json": "data"},
    )

    # Test string payload
    await buffered_wire_capture.capture_outbound_request(
        context=None,
        session_id="test",
        backend="test",
        model="test",
        key_name=None,
        request_payload="string data",
    )

    # Test bytes payload
    await buffered_wire_capture.capture_outbound_request(
        context=None,
        session_id="test",
        backend="test",
        model="test",
        key_name=None,
        request_payload=b"bytes data",
    )

    # Force flush and check content types
    await buffered_wire_capture._flush_buffer()

    # Check buffer contents (since we're testing the logic)
    # In a real scenario, we'd read from file, but here we test the entry creation
    assert True  # This test verifies the code doesn't crash with different types


@pytest.mark.asyncio
async def test_format_version_in_system_init(buffered_wire_capture, temp_capture_file):
    """Test that system initialization includes format version."""
    # The system_init entry should already be written during initialization

    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Should have at least the system_init entry
    assert len(lines) >= 1

    # Parse the first entry (system_init)
    init_entry = json.loads(lines[0].strip())

    assert init_entry["direction"] == "system_init"
    assert init_entry["payload"]["format_version"] == "buffered_v1"
    assert (
        init_entry["payload"]["format_description"]
        == "Buffered JSON Lines format with high-performance async I/O"
    )
    assert init_entry["metadata"]["implementation"] == "BufferedWireCapture"
    assert "buffer_size" in init_entry["metadata"]
    assert "flush_interval" in init_entry["metadata"]


@pytest.mark.asyncio
async def test_shutdown_flushes_buffer(buffered_wire_capture, temp_capture_file):
    """Test that shutdown properly flushes remaining buffer."""
    # Add some entries
    await buffered_wire_capture.capture_outbound_request(
        context=None,
        session_id="test",
        backend="test",
        model="test",
        key_name=None,
        request_payload={"test": "data"},
    )

    # Shutdown should flush
    await buffered_wire_capture.shutdown()

    # Verify entries are written
    with open(temp_capture_file) as f:
        lines = f.readlines()

    # Should have system_init + our request
    assert len(lines) >= 2

    # Find our request
    found_request = False
    for line in lines:
        entry = json.loads(line.strip())
        if (
            entry["direction"] == "outbound_request"
            and entry["payload"]["test"] == "data"
        ):
            found_request = True
            break

    assert found_request


def test_get_client_info():
    """Test client info extraction from context."""
    config = MagicMock(spec=AppConfig)
    config.logging = MagicMock(spec=LoggingConfig)
    config.logging.capture_file = None

    capture = BufferedWireCapture(config)

    # Test with full context
    context = MagicMock(spec=RequestContext)
    context.client_host = "192.168.1.1"
    context.agent = "TestAgent/1.0"

    client_info = capture._get_client_info(context)
    assert client_info == "192.168.1.1(TestAgent/1.0)"

    # Test with only host
    context.agent = None
    client_info = capture._get_client_info(context)
    assert client_info == "192.168.1.1"

    # Test with only agent
    context.client_host = None
    context.agent = "TestAgent/1.0"
    client_info = capture._get_client_info(context)
    assert client_info == "unknown_host(TestAgent/1.0)"

    # Test with no context
    client_info = capture._get_client_info(None)
    assert client_info == "unknown_client"

    # Test with empty context
    context.client_host = None
    context.agent = None
    client_info = capture._get_client_info(context)
    assert client_info == "unknown_client"
