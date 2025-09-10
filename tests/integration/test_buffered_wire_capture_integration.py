"""Integration tests for BufferedWireCapture service."""

import asyncio
import json
import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.services.buffered_wire_capture_service import BufferedWireCapture


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
def mock_app_config(temp_capture_file):
    """Create a mock AppConfig with buffered wire capture enabled."""
    config = AppConfig.from_env()
    config.logging.capture_file = temp_capture_file
    config.logging.capture_buffer_size = 1024  # Small buffer for testing
    config.logging.capture_flush_interval = 0.1  # Fast flush for testing
    config.logging.capture_max_entries_per_flush = 5
    return config


@pytest.fixture
def test_app(mock_app_config):
    """Create a test application with buffered wire capture enabled."""
    builder = ApplicationBuilder().add_default_stages()
    app = builder.build_compat(mock_app_config)

    # Return both the app and the capture file path for inspection
    return app, mock_app_config.logging.capture_file


@pytest.fixture
def client(test_app):
    """Create a test client."""
    app, _ = test_app
    return TestClient(app)


def test_buffered_wire_capture_integration(client, test_app):
    """Test that buffered wire capture works through the application's DI system."""
    app, capture_file = test_app

    # Get the wire capture service from DI to verify it's configured
    wire_capture = app.state.service_provider.get_service(IWireCapture)
    assert isinstance(wire_capture, BufferedWireCapture)
    assert wire_capture.enabled() is True

    # Verify the capture file exists and has system_init entry
    assert os.path.exists(capture_file)

    with open(capture_file) as f:
        lines = f.readlines()

    # Should have at least the system_init entry
    assert len(lines) >= 1

    # Parse the system_init entry
    init_entry = json.loads(lines[0].strip())
    assert init_entry["direction"] == "system_init"
    assert init_entry["payload"]["format_version"] == "buffered_v1"
    assert init_entry["metadata"]["implementation"] == "BufferedWireCapture"


@pytest.mark.asyncio
async def test_buffered_wire_capture_end_to_end(test_app):
    """Test end-to-end wire capture functionality."""
    app, capture_file = test_app

    # Get the wire capture service
    wire_capture = app.state.service_provider.get_service(IWireCapture)

    # Simulate a complete request/response cycle
    request_payload = {
        "messages": [{"role": "user", "content": "Test message"}],
        "model": "gpt-4",
        "temperature": 0.7,
        "stream": False,
    }

    response_payload = {
        "choices": [{"message": {"role": "assistant", "content": "Test response"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    # Capture outbound request
    await wire_capture.capture_outbound_request(
        context=None,
        session_id="integration-test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        request_payload=request_payload,
    )

    # Simulate some processing time
    await asyncio.sleep(0.05)

    # Capture inbound response
    await wire_capture.capture_inbound_response(
        context=None,
        session_id="integration-test-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        response_content=response_payload,
    )

    # Force flush to ensure data is written
    await wire_capture._flush_buffer()

    # Verify the capture file contains our entries
    with open(capture_file) as f:
        lines = f.readlines()

    # Should have system_init + request + response = at least 3 entries
    assert len(lines) >= 3

    # Parse and verify entries
    entries = [json.loads(line.strip()) for line in lines]

    # Find our request and response entries
    request_entry = None
    response_entry = None

    for entry in entries:
        if (
            entry["direction"] == "outbound_request"
            and entry["session_id"] == "integration-test-session"
        ):
            request_entry = entry
        elif (
            entry["direction"] == "inbound_response"
            and entry["session_id"] == "integration-test-session"
        ):
            response_entry = entry

    # Verify request entry
    assert request_entry is not None
    assert request_entry["backend"] == "openai"
    assert request_entry["model"] == "gpt-4"
    assert request_entry["key_name"] == "OPENAI_API_KEY"
    assert request_entry["content_type"] == "json"
    assert request_entry["payload"] == request_payload

    # Verify response entry
    assert response_entry is not None
    assert response_entry["backend"] == "openai"
    assert response_entry["model"] == "gpt-4"
    assert response_entry["payload"] == response_payload

    # Verify timestamps are reasonable
    assert request_entry["timestamp_unix"] <= response_entry["timestamp_unix"]


@pytest.mark.asyncio
async def test_buffered_wire_capture_streaming(test_app):
    """Test buffered wire capture with streaming responses."""
    app, capture_file = test_app

    # Get the wire capture service
    wire_capture = app.state.service_provider.get_service(IWireCapture)

    # Mock streaming data
    chunks = [
        b'{"choices":[{"delta":{"content":"Hello"}}]}',
        b'{"choices":[{"delta":{"content":" world"}}]}',
        b'{"choices":[{"delta":{"content":"!"}}]}',
    ]

    async def mock_stream():
        for chunk in chunks:
            yield chunk

    # Wrap the stream
    wrapped_stream = wire_capture.wrap_inbound_stream(
        context=None,
        session_id="streaming-test-session",
        backend="anthropic",
        model="claude-3-opus",
        key_name="ANTHROPIC_API_KEY",
        stream=mock_stream(),
    )

    # Consume the stream
    result = []
    async for chunk in wrapped_stream:
        result.append(chunk)

    # Verify chunks are unchanged
    assert result == chunks

    # Force flush
    await wire_capture._flush_buffer()

    # Verify capture file contains streaming entries
    with open(capture_file) as f:
        lines = f.readlines()

    # Parse entries
    entries = [json.loads(line.strip()) for line in lines]

    # Find streaming entries
    stream_entries = [
        e
        for e in entries
        if "stream" in e["direction"] and e["session_id"] == "streaming-test-session"
    ]

    # Should have: stream_start + 3 chunks + stream_end = 5 entries
    assert len(stream_entries) == 5

    # Verify stream start
    start_entry = stream_entries[0]
    assert start_entry["direction"] == "stream_start"
    assert start_entry["backend"] == "anthropic"
    assert start_entry["model"] == "claude-3-opus"

    # Verify chunks
    for i in range(1, 4):
        chunk_entry = stream_entries[i]
        assert chunk_entry["direction"] == "stream_chunk"
        assert chunk_entry["metadata"]["chunk_number"] == i
        assert chunk_entry["metadata"]["chunk_bytes"] == len(chunks[i - 1])
        assert chunk_entry["payload"] == chunks[i - 1].decode("utf-8")

    # Verify stream end
    end_entry = stream_entries[4]
    assert end_entry["direction"] == "stream_end"
    assert end_entry["payload"]["total_bytes"] == sum(len(chunk) for chunk in chunks)
    assert end_entry["payload"]["total_chunks"] == 3


@pytest.mark.asyncio
async def test_buffered_wire_capture_performance(test_app):
    """Test that buffered wire capture can handle high throughput."""
    app, capture_file = test_app

    # Get the wire capture service
    wire_capture = app.state.service_provider.get_service(IWireCapture)

    # Capture many entries quickly
    num_entries = 50
    start_time = asyncio.get_event_loop().time()

    for i in range(num_entries):
        await wire_capture.capture_outbound_request(
            context=None,
            session_id=f"perf-session-{i % 10}",  # 10 different sessions
            backend="test-backend",
            model="test-model",
            key_name="TEST_KEY",
            request_payload={"request_id": i, "data": f"test data {i}"},
        )

    end_time = asyncio.get_event_loop().time()
    capture_time = end_time - start_time
    if capture_time <= 0:
        capture_time = 1e-9  # avoid division by zero on very fast systems

    # Should be able to capture at least 100 entries per second
    entries_per_second = num_entries / capture_time
    assert (
        entries_per_second > 100
    ), f"Performance too slow: {entries_per_second:.1f} entries/sec"

    # Force flush
    await wire_capture._flush_buffer()

    # Verify all entries were captured
    with open(capture_file) as f:
        lines = f.readlines()

    # Parse entries
    entries = [json.loads(line.strip()) for line in lines]

    # Count request entries
    request_entries = [e for e in entries if e["direction"] == "outbound_request"]
    assert len(request_entries) == num_entries

    # Verify entries have correct data
    for i, entry in enumerate(request_entries):
        assert entry["payload"]["request_id"] == i
        assert entry["payload"]["data"] == f"test data {i}"


def test_buffered_wire_capture_configuration_validation(temp_capture_file):
    """Test that configuration validation works with buffered wire capture."""
    # Test with valid configuration
    config = AppConfig.from_env()
    config.logging.capture_file = temp_capture_file
    config.logging.capture_buffer_size = 8192
    config.logging.capture_flush_interval = 2.0
    config.logging.capture_max_entries_per_flush = 200

    capture = BufferedWireCapture(config)
    assert capture.enabled() is True

    # Clean up
    if hasattr(capture, "_flush_task") and capture._flush_task:
        capture._flush_task.cancel()


@pytest.mark.asyncio
async def test_buffered_wire_capture_shutdown_cleanup(test_app):
    """Test that wire capture properly cleans up on shutdown."""
    app, capture_file = test_app

    # Get the wire capture service
    wire_capture = app.state.service_provider.get_service(IWireCapture)

    # Add some data to buffer
    await wire_capture.capture_outbound_request(
        context=None,
        session_id="shutdown-test",
        backend="test",
        model="test",
        key_name=None,
        request_payload={"test": "shutdown"},
    )

    # Shutdown should flush remaining data
    await wire_capture.shutdown()

    # Verify data was flushed
    with open(capture_file) as f:
        lines = f.readlines()

    # Find our test entry
    found_test_entry = False
    for line in lines:
        entry = json.loads(line.strip())
        if (
            entry["direction"] == "outbound_request"
            and entry["session_id"] == "shutdown-test"
            and entry["payload"]["test"] == "shutdown"
        ):
            found_test_entry = True
            break

    assert found_test_entry, "Shutdown did not flush buffered data"
