"""Integration tests for structured wire capture."""

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
    """Create a mock AppConfig with capture enabled."""
    config = AppConfig.from_env()
    config.logging.capture_file = temp_capture_file
    return config


@pytest.fixture
def test_app(mock_app_config):
    """Create a test application with wire capture enabled."""
    builder = ApplicationBuilder().add_default_stages()
    app = builder.build_compat(mock_app_config)

    # Return both the app and the capture file path for inspection
    return app, mock_app_config.logging.capture_file


@pytest.fixture
def client(test_app):
    """Create a test client for the application."""
    app, _ = test_app
    return TestClient(app)


def test_wire_capture_integration(client, test_app):
    """Test that wire capture works through the application's middleware stack (buffered format)."""
    app, capture_file = test_app

    # Get the wire capture service from DI to verify it's configured
    wire_capture = app.state.service_provider.get_service(IWireCapture)
    assert isinstance(wire_capture, BufferedWireCapture)
    assert wire_capture.enabled() is True

    # Mock backend response
    mock_response = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677652288,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Hello! How can I help you today?",
                },
                "finish_reason": "stop",
            }
        ],
    }

    # Since we can't easily make real backend calls in tests,
    # we'll use the capture service directly to simulate calls
    async def simulate_request_and_response():
        context = {
            "headers": {"user-agent": "test-client"},
            "cookies": {},
            "state": None,
            "app_state": None,
            "client_host": "127.0.0.1",
            "session_id": "test-integration-session",
            "agent": "test-agent",
        }

        request_payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Hello, world!"},
            ],
            "model": "gpt-4",
        }

        # Simulate request
        await wire_capture.capture_outbound_request(
            context=context,
            session_id="test-integration-session",
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            request_payload=request_payload,
        )

        # Simulate response
        await wire_capture.capture_inbound_response(
            context=context,
            session_id="test-integration-session",
            backend="openai",
            model="gpt-4",
            key_name="OPENAI_API_KEY",
            response_content=mock_response,
        )

    # Run the simulation
    asyncio.run(simulate_request_and_response())

    # Force flush to ensure data is written
    wire_capture = app.state.service_provider.get_service(IWireCapture)
    asyncio.run(wire_capture._flush_buffer())  # type: ignore[attr-defined]

    # Read and validate the capture file (buffered JSON lines format)
    with open(capture_file) as f:
        lines = f.readlines()

    # Should have at least 3 entries: system_init + request + response
    assert len(lines) >= 3

    # Parse entries and find our request/response for the session
    entries = [json.loads(line) for line in lines]
    req = next(
        (
            e
            for e in entries
            if e.get("direction") == "outbound_request"
            and e.get("session_id") == "test-integration-session"
        ),
        None,
    )
    resp = next(
        (
            e
            for e in entries
            if e.get("direction") == "inbound_response"
            and e.get("session_id") == "test-integration-session"
        ),
        None,
    )
    assert req is not None and resp is not None
    assert req["backend"] == "openai" and req["model"] == "gpt-4"
    assert "You are a helpful assistant." in json.dumps(
        req["payload"]
    )  # system prompt present
    assert "Hello! How can I help you today?" in json.dumps(
        resp["payload"]
    )  # response present


@pytest.mark.asyncio
async def test_streaming_response_integration(test_app):
    """Test streaming response capture (buffered format)."""
    app, capture_file = test_app

    # Get the wire capture service from DI
    wire_capture = app.state.service_provider.get_service(IWireCapture)

    # Mock stream chunks
    chunks = [
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":"Hello"}}]}\n',
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":" there"}}]}\n',
        b'{"id":"chatcmpl-123","object":"chat.completion.chunk","choices":[{"delta":{"content":"!"}}]}\n',
    ]

    # Create mock stream
    async def mock_stream():
        for chunk in chunks:
            yield chunk

    context = {
        "headers": {"user-agent": "test-client"},
        "cookies": {},
        "state": None,
        "app_state": None,
        "client_host": "127.0.0.1",
        "session_id": "test-stream-session",
        "agent": "test-agent",
    }

    # Wrap the stream
    wrapped_stream = wire_capture.wrap_inbound_stream(
        context=context,
        session_id="test-stream-session",
        backend="openai",
        model="gpt-4",
        key_name="OPENAI_API_KEY",
        stream=mock_stream(),
    )

    # Consume the stream
    result = []
    async for chunk in wrapped_stream:
        result.append(chunk)

    # Verify chunks unchanged
    assert result == chunks

    # Force flush to ensure data is written
    await wire_capture._flush_buffer()  # type: ignore[attr-defined]

    # Read the capture file to verify entries (buffered JSON lines)
    with open(capture_file) as f:
        lines = f.readlines()

    entries = [json.loads(line) for line in lines]
    stream_entries = [
        e
        for e in entries
        if e.get("session_id") == "test-stream-session"
        and "stream" in e.get("direction", "")
    ]

    # Expect stream_start + 3 chunks + stream_end
    assert len(stream_entries) == 5
    assert stream_entries[0]["direction"] == "stream_start"
    for i in range(1, 4):
        chunk_entry = stream_entries[i]
        assert chunk_entry["direction"] == "stream_chunk"
        assert chunk_entry["metadata"]["chunk_number"] == i
        assert chunk_entry["metadata"]["chunk_bytes"] > 0
    assert stream_entries[4]["direction"] == "stream_end"
    assert stream_entries[4]["payload"]["total_chunks"] == 3
    assert stream_entries[4]["payload"]["total_bytes"] == sum(len(c) for c in chunks)
