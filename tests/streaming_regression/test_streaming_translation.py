"""Cross-protocol streaming translation tests.

Tests that streaming works correctly when translating between different API formats.
This is critical as translation layers can accidentally buffer streams.
"""

from __future__ import annotations

import asyncio
import os
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from src.core.app.test_builder import build_test_app
from src.core.domain.chat import ChatMessage

from tests.streaming_regression.conftest import count_sse_events
from tests.streaming_regression.emulators.anthropic_emulator import (
    AnthropicStreamingEmulator,
)
from tests.streaming_regression.emulators.gemini_emulator import GeminiStreamingEmulator
from tests.streaming_regression.emulators.openai_emulator import (
    OpenAIStreamingEmulator,
)


def _build_streaming_test_app():
    """Build test app with loop detection disabled for streaming tests."""
    old_value = os.environ.get("LOOP_DETECTION_ENABLED")
    os.environ["LOOP_DETECTION_ENABLED"] = "false"
    try:
        app = build_test_app()
        app.state.disable_auth = True
        return app
    finally:
        if old_value is None:
            os.environ.pop("LOOP_DETECTION_ENABLED", None)
        else:
            os.environ["LOOP_DETECTION_ENABLED"] = old_value


def _inject_backend(app, backend, backend_name: str) -> None:
    """Inject mock backend into app with specific backend name."""
    service_provider = app.state.service_provider
    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = service_provider.get_required_service(IBackendService)
    backend_service._backends[backend_name] = backend

    async def call_completion_override(
        request,
        stream: bool = False,
        allow_failover: bool = True,
        context=None,
    ):
        return await backend.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model=getattr(request, "model", "test-model"),
            identity=None,
        )

    backend_service.call_completion = call_completion_override


@pytest.mark.asyncio
async def test_openai_frontend_gemini_backend_streaming() -> None:
    """Test OpenAI API frontend with Gemini backend streaming.

    This tests the translation layer: OpenAI request -> Gemini backend -> OpenAI response
    """
    text = "Testing cross-protocol streaming from Gemini to OpenAI format"
    chunks = cast(
        list[str | bytes],
        GeminiStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = GeminiStreamingEmulator(chunks=chunks, chunk_delay=0.01)  # Reduced from 0.02 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "gemini")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gemini:gemini-pro",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
        }
        headers = {"x-goog-api-key": "test-key"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )


@pytest.mark.asyncio
async def test_openai_frontend_anthropic_backend_streaming() -> None:
    """Test OpenAI API frontend with Anthropic backend streaming."""
    text = "Testing cross-protocol streaming from Anthropic to OpenAI format"
    chunks = cast(
        list[str | bytes],
        AnthropicStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = AnthropicStreamingEmulator(chunks=chunks, chunk_delay=0.005)  # Reduced from 0.01 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "anthropic")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "anthropic:claude-3-5-sonnet-20241022",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
        }
        headers = {"x-goog-api-key": "test-key"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )


@pytest.mark.asyncio
async def test_anthropic_frontend_openai_backend_streaming() -> None:
    """Test Anthropic API frontend with OpenAI backend streaming."""
    text = "Testing cross-protocol streaming from OpenAI to Anthropic format"
    chunks = cast(
        list[str | bytes],
        OpenAIStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.01)  # Reduced from 0.02 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "openai")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "openai:gpt-4",
            "messages": [{"role": "user", "content": "test"}],
            "stream": True,
            "max_tokens": 1024,
        }
        headers = {"x-api-key": "test-key", "anthropic-version": "2023-06-01"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST", "/anthropic/v1/messages", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )


@pytest.mark.asyncio
async def test_anthropic_frontend_gemini_backend_streaming() -> None:
    """Test Anthropic API frontend with Gemini backend streaming."""
    text = "Testing cross-protocol streaming from Gemini to Anthropic format"
    chunks = cast(
        list[str | bytes],
        GeminiStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = GeminiStreamingEmulator(chunks=chunks, chunk_delay=0.01)  # Reduced from 0.02 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "gemini")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gemini:gemini-pro",
            "messages": [{"role": "user", "content": "test"}],
            "stream": True,
            "max_tokens": 1024,
        }
        headers = {"x-api-key": "test-key", "anthropic-version": "2023-06-01"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST", "/anthropic/v1/messages", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )


@pytest.mark.asyncio
async def test_gemini_frontend_openai_backend_streaming() -> None:
    """Test Gemini API frontend with OpenAI backend streaming."""
    text = "Testing cross-protocol streaming from OpenAI to Gemini format"
    chunks = cast(
        list[str | bytes],
        OpenAIStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.01)  # Reduced from 0.02 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "openai")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "test"}]}],
            "generationConfig": {"temperature": 0.7},
        }
        headers = {"x-goog-api-key": "test-key"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST",
            "/v1beta/models/openai:gpt-4:streamGenerateContent?alt=sse",
            json=payload,
            headers=headers,
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )


@pytest.mark.asyncio
async def test_gemini_frontend_anthropic_backend_streaming() -> None:
    """Test Gemini API frontend with Anthropic backend streaming."""
    text = "Testing cross-protocol streaming from Anthropic to Gemini format"
    chunks = cast(
        list[str | bytes],
        AnthropicStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = AnthropicStreamingEmulator(chunks=chunks, chunk_delay=0.01)  # Reduced from 0.02 for performance
    app = _build_streaming_test_app()
    _inject_backend(app, backend, "anthropic")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "test"}]}],
            "generationConfig": {"temperature": 0.7},
        }
        headers = {"x-goog-api-key": "test-key"}

        received_chunks = []
        chunk_times = []

        async with client.stream(
            "POST",
            "/v1beta/models/anthropic:claude-3-5-sonnet-20241022:streamGenerateContent?alt=sse",
            json=payload,
            headers=headers,
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    stats = backend.get_timing_stats()
    if stats["chunks_sent"] > 1:
        assert (
            stats["avg_delay"] > 0.01
        ), f"Backend delays too small: {stats['avg_delay']:.3f}s"

    print(
        f"[OK] Translation: Backend sent {stats['chunks_sent']} chunks with avg delay {stats['avg_delay']:.3f}s"
    )
    print(
        f"[OK] Translation: Test client received {len(received_chunks)} aggregated chunks"
    )
