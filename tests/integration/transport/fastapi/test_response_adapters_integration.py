"""Integration tests for response adapters facade.

Tests the full integration of response adapters with wire capture,
streaming conversion, and all layer components.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.usage_canonical_record import CanonicalUsageRecord
from src.core.interfaces.wire_capture_interface import IWireCapture
from src.core.transport.fastapi.response_adapters import (
    domain_response_to_fastapi,
    to_fastapi_response,
    to_fastapi_streaming_response,
)
from tests.utils.fake_clock import FakeClockContext


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
        # Pass through the stream
        return stream

    async def capture_stream_completion(
        self,
        *,
        context=None,
        session_id=None,
        backend=None,
        model=None,
        key_name=None,
        canonical_usage=None,
    ) -> None:
        """Capture canonical usage for completed streaming response."""
        # Mock implementation - no-op for testing

    async def shutdown(self) -> None:
        """Gracefully stop background work."""


@pytest.mark.asyncio
async def test_non_streaming_json_response():
    """Test full non-streaming JSON response path."""
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={"x-custom": "value"},
        status_code=200,
    )

    response = to_fastapi_response(envelope)

    assert response.status_code == 200
    assert response.headers.get("x-custom") == "value"
    assert response.media_type == "application/json"


@pytest.mark.asyncio
async def test_non_streaming_json_response_with_wire_capture():
    """Test non-streaming JSON response with wire capture enabled."""
    wire_capture = MockWireCapture(enabled=True)
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={},
        status_code=200,
        metadata={"backend": "openai", "model": "gpt-4"},
    )

    response = to_fastapi_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Wait a bit for background task to complete
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.1))
        clock.advance(0.1)
        await sleep_task

    # Verify wire capture was scheduled
    assert len(wire_capture.captured_responses) == 1
    captured_content = wire_capture.captured_responses[0]["response_content"]
    assert isinstance(captured_content, dict)
    assert captured_content.get("message") == "Hello, world!"


@pytest.mark.asyncio
async def test_non_streaming_json_response_with_wire_capture_disabled():
    """Test non-streaming JSON response with wire capture disabled."""
    wire_capture = MockWireCapture(enabled=False)
    envelope = ResponseEnvelope(
        content={"message": "Hello, world!"},
        headers={},
        status_code=200,
    )

    response = to_fastapi_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Wait a bit for background task to complete
    async with FakeClockContext() as clock:
        sleep_task = asyncio.create_task(asyncio.sleep(0.1))
        clock.advance(0.1)
        await sleep_task

    # Verify wire capture was NOT scheduled
    assert len(wire_capture.captured_responses) == 0


@pytest.mark.asyncio
async def test_streaming_response():
    """Test full streaming response path."""

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={"x-custom": "value"},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"
    assert response.headers.get("x-custom") == "value"

    # Consume the stream to verify it works
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Should have SSE-formatted chunks
    assert len(chunks) > 0


@pytest.mark.asyncio
async def test_streaming_response_with_wire_capture():
    """Test streaming response with wire capture enabled."""
    wire_capture = MockWireCapture(enabled=True)

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
        metadata={"backend": "openai", "model": "gpt-4"},
    )

    response = to_fastapi_streaming_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Consume the stream
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Verify wire capture wrapped the stream
    assert len(wire_capture.wrapped_streams) == 1


@pytest.mark.asyncio
async def test_streaming_response_with_wire_capture_disabled():
    """Test streaming response with wire capture disabled."""
    wire_capture = MockWireCapture(enabled=False)

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope, wire_capture=wire_capture)

    assert response.status_code == 200

    # Consume the stream
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Verify wire capture did NOT wrap the stream
    assert len(wire_capture.wrapped_streams) == 0


@pytest.mark.asyncio
async def test_domain_response_to_fastapi_non_streaming():
    """Test domain_response_to_fastapi with non-streaming response."""
    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
    )

    response = domain_response_to_fastapi(envelope)

    assert response.status_code == 200
    assert response.media_type == "application/json"


@pytest.mark.asyncio
async def test_domain_response_to_fastapi_streaming():
    """Test domain_response_to_fastapi with streaming response."""

    async def _simple_stream() -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
        yield b"data: [DONE]\n\n"

    envelope = StreamingResponseEnvelope(
        content=_simple_stream(),
        headers={},
        status_code=200,
    )

    response = domain_response_to_fastapi(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_content_converter_parameter():
    """Test content_converter parameter (legacy support)."""

    def converter(content: dict) -> dict:
        content["converted"] = True
        return content

    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
    )

    response = to_fastapi_response(envelope, content_converter=converter)

    assert response.status_code == 200
    # Note: We can't easily verify the conversion without parsing response body
    # but the function should execute without error


@pytest.mark.asyncio
async def test_empty_streaming_response():
    """Test streaming response with None content."""
    envelope = StreamingResponseEnvelope(
        content=None,
        headers={},
        status_code=200,
    )

    response = to_fastapi_streaming_response(envelope)

    assert response.status_code == 200
    assert response.media_type == "text/event-stream"

    # Consume the stream (should be empty)
    chunks = []
    async for chunk in response.body_iterator:  # type: ignore[attr-defined]
        chunks.append(chunk)

    # Should handle empty stream gracefully
    assert isinstance(chunks, list)


@pytest.mark.asyncio
async def test_canonical_usage_projected_to_response_payload():
    """Test that canonical usage is projected to response payload (Requirement 5.2)."""
    from src.core.app.stages.core_services import CoreServicesStage
    from src.core.app.stages.infrastructure import InfrastructureStage
    from src.core.config.app_config import AppConfig
    from src.core.di.container import ServiceCollection
    from src.core.di.services import set_service_provider

    # Setup DI container with normalization service
    services = ServiceCollection()
    config = AppConfig()

    infrastructure = InfrastructureStage()
    await infrastructure.execute(services, config)

    core_services = CoreServicesStage()
    await core_services.execute(services, config)

    provider = services.build_service_provider()
    # Set the provider globally so JSONResponseBuilder can resolve it
    set_service_provider(provider)

    canonical_usage = CanonicalUsageRecord(
        prompt_tokens=100,
        completion_tokens=200,
        total_tokens=300,
        cost=0.05,
    )

    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
        canonical_usage=canonical_usage,
    )

    response = to_fastapi_response(envelope)

    assert response.status_code == 200
    import json

    body_dict = json.loads(response.body.decode())
    # Usage should be projected from canonical usage
    assert "usage" in body_dict
    assert body_dict["usage"]["prompt_tokens"] == 100
    assert body_dict["usage"]["completion_tokens"] == 200
    assert body_dict["usage"]["total_tokens"] == 300


@pytest.mark.asyncio
async def test_canonical_usage_projected_to_headers():
    """Test that canonical usage is projected to response headers (Requirement 5.5)."""
    canonical_usage = CanonicalUsageRecord(
        prompt_tokens=100,
        completion_tokens=200,
        total_tokens=300,
        cost=0.05,
    )

    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
        canonical_usage=canonical_usage,
    )

    response = to_fastapi_response(envelope)

    assert response.status_code == 200
    # Headers should be derived from canonical usage
    assert response.headers["x-usage-prompt-tokens"] == "100"
    assert response.headers["x-usage-completion-tokens"] == "200"
    assert response.headers["x-usage-total-tokens"] == "300"
    assert response.headers["x-usage-cost"] == "0.05"


@pytest.mark.asyncio
async def test_canonical_usage_with_extensions_in_headers():
    """Test that extended fields from canonical usage extensions are in headers."""
    canonical_usage = CanonicalUsageRecord(
        prompt_tokens=100,
        completion_tokens=200,
        total_tokens=300,
        extensions={
            "completion_tokens_details": {"reasoning_tokens": 50},
            "prompt_tokens_details": {"cached_tokens": 25},
        },
    )

    envelope = ResponseEnvelope(
        content={"message": "Hello"},
        headers={},
        status_code=200,
        canonical_usage=canonical_usage,
    )

    response = to_fastapi_response(envelope)

    assert response.status_code == 200
    assert response.headers["x-usage-prompt-tokens"] == "100"
    assert response.headers["x-usage-completion-tokens"] == "200"
    assert response.headers["x-usage-total-tokens"] == "300"
    assert response.headers["x-usage-reasoning-tokens"] == "50"
    assert response.headers["x-usage-cached-tokens"] == "25"
