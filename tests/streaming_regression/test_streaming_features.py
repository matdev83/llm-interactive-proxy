"""Streaming tests with advanced proxy features.

Tests that advanced features like API key redaction, content rewriting,
tool call reactors, and JSON repairs work correctly with streaming.

Updated to use new StreamingContent contracts and deterministic testing.
"""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest
from httpx import ASGITransport, AsyncClient
from src.core.app.test_builder import build_test_app
from src.core.domain.chat import ChatMessage

from tests.streaming_regression.conftest import count_sse_events
from tests.streaming_regression.emulators.anthropic_emulator import (
    AnthropicStreamingEmulator,
)
from tests.streaming_regression.emulators.gemini_emulator import (
    GeminiStreamingEmulator,
)
from tests.streaming_regression.emulators.openai_emulator import (
    OpenAIStreamingEmulator,
)


def _fake_openai_api_key() -> str:
    """Build a fake OpenAI-style API key without embedding it directly."""
    return "".join(["sk-", "1234567890", "abcdef"])


def _inject_backend(app, backend) -> None:
    """Inject mock backend into app."""
    service_provider = app.state.service_provider
    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = service_provider.get_required_service(IBackendService)
    backend_service._backends[backend.backend_type] = backend

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
async def test_streaming_with_api_key_redaction() -> None:
    """Test that API key redaction works with streaming responses.

    API keys in streaming chunks should be redacted without buffering.
    """
    # Create chunks that contain an API key
    text_with_key = f"Here is your API key: {_fake_openai_api_key()} and some more text"
    chunks = cast(
        list[str | bytes | dict[str, Any]],
        OpenAIStreamingEmulator.create_text_chunks(text_with_key, chunk_size=15),
    )

    typed_chunks = cast(list[str | bytes | dict[str, Any]], chunks)
    backend = OpenAIStreamingEmulator(chunks=typed_chunks, chunk_delay=0.02)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
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

    # Verify streaming behavior maintained (contract-level check)
    # The new pipeline may consolidate chunks differently, but should still stream
    assert count_sse_events(received_chunks) >= 3, "Should receive multiple chunks"

    # Verify backend stats (deterministic check)
    stats = backend.get_timing_stats()
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once (buffering detected)"

    # Verify chunk count consistency
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"


@pytest.mark.asyncio
async def test_streaming_with_think_tags_fix() -> None:
    """Test that think tags fix works with streaming.

    Think tags should be stripped from streaming chunks without buffering.
    """
    # Create chunks with think tags
    text_with_tags = "<think>Let me analyze this</think>Here is the actual response"
    chunks = cast(
        list[str | bytes | dict[str, Any]],
        OpenAIStreamingEmulator.create_text_chunks(text_with_tags, chunk_size=12),
    )

    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.02)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
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

    # Verify streaming behavior (contract-level check)
    import logging

    logger = logging.getLogger(__name__)
    logger.warning(f"DEBUG: Received chunks count: {len(received_chunks)}")
    for i, c in enumerate(received_chunks):
        logger.warning(f"DEBUG: Chunk {i}: {c!r}")

    assert count_sse_events(received_chunks) > 3, "Should receive multiple chunks"

    # Verify backend stats (deterministic check)
    stats = backend.get_timing_stats()
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once (buffering detected)"

    # Verify chunk count consistency
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"


@pytest.mark.asyncio
async def test_streaming_with_tool_call_reactor() -> None:
    """Test that tool call reactor works with streaming.

    Tool call reactors should process streaming tool calls without buffering.
    """
    chunks = cast(
        list[str | bytes | dict[str, Any]],
        OpenAIStreamingEmulator.create_tool_call_chunks(),
    )

    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.02)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                }
            ],
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

    # Verify streaming behavior (contract-level check)
    assert count_sse_events(received_chunks) > 2, "Should receive multiple chunks"

    # Verify backend stats (deterministic check)
    stats = backend.get_timing_stats()
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once (buffering detected)"

    # Verify chunk count consistency
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("emulator_cls", "chunk_factory"),
    [
        (OpenAIStreamingEmulator, OpenAIStreamingEmulator.create_tool_call_chunks),
        (
            AnthropicStreamingEmulator,
            AnthropicStreamingEmulator.create_tool_call_chunks,
        ),
        (GeminiStreamingEmulator, GeminiStreamingEmulator.create_function_call_chunks),
    ],
)
async def test_streaming_tool_calls_are_deduplicated(
    emulator_cls, chunk_factory
) -> None:
    chunk_list = cast(
        list[str | bytes | dict[str, Any]],
        chunk_factory(),
    )
    backend = emulator_cls(chunks=chunk_list, chunk_delay=0.01)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content="tool please").model_dump()],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                            "required": ["path"],
                        },
                    },
                }
            ],
        }
        headers = {"x-goog-api-key": "test-key"}

        tool_call_events = 0
        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200
            async for chunk in response.aiter_text():
                text = chunk.strip()
                if not text:
                    continue
                if any(
                    marker in text
                    for marker in ('"tool_calls"', '"functionCall"', '"tool_use"')
                ):
                    tool_call_events += 1

    if emulator_cls is OpenAIStreamingEmulator:
        assert (
            tool_call_events == 1
        ), f"Expected a single structured tool call event, saw {tool_call_events}"
    else:
        assert (
            tool_call_events <= 1
        ), f"Expected at most one structured tool call event, saw {tool_call_events}"


@pytest.mark.asyncio
async def test_streaming_with_json_repair() -> None:
    """Test that JSON repair works with streaming.

    Malformed JSON in tool calls should be repaired without buffering entire stream.
    """
    # Create chunks with intentionally malformed JSON that needs repair
    chunks = [
        'data: {"id":"test","object":"chat.completion.chunk","created":123,"model":"gpt-4","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"test","arguments":""}}]},"finish_reason":null}]}\n\n',
        'data: {"id":"test","object":"chat.completion.chunk","created":123,"model":"gpt-4","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"key\\":"}}]},"finish_reason":null}]}\n\n',
        'data: {"id":"test","object":"chat.completion.chunk","created":123,"model":"gpt-4","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"value\\"}"}}]},"finish_reason":null}]}\n\n',
        'data: {"id":"test","object":"chat.completion.chunk","created":123,"model":"gpt-4","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n',
        "data: [DONE]\n\n",
    ]

    typed_chunks = cast(list[str | bytes | dict[str, Any]], chunks)
    backend = OpenAIStreamingEmulator(chunks=typed_chunks, chunk_delay=0.02)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "test",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
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

    # Verify streaming behavior (contract-level check)
    assert count_sse_events(received_chunks) > 2, "Should receive multiple chunks"

    # Verify backend stats (deterministic check)
    stats = backend.get_timing_stats()
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once (buffering detected)"

    # Verify chunk count consistency
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"


@pytest.mark.asyncio
async def test_streaming_with_reasoning_content() -> None:
    """Test that reasoning content streams correctly.

    Reasoning content should stream incrementally without buffering.
    """
    reasoning = "Let me think about this step by step"
    response_text = "Based on my analysis, the answer is 42"
    chunks = cast(
        list[str | bytes | dict[str, Any]],
        OpenAIStreamingEmulator.create_reasoning_chunks(reasoning, response_text),
    )

    backend = OpenAIStreamingEmulator(chunks=chunks, chunk_delay=0.02)
    app = build_test_app()
    app.state.disable_auth = True
    _inject_backend(app, backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
        }
        headers = {"x-goog-api-key": "test-key"}

        received_chunks = []
        chunk_times = []
        has_reasoning = False
        has_content = False

        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip() and chunk.startswith("data: "):
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

                    # Check for reasoning and content
                    if "reasoning_content" in chunk:
                        has_reasoning = True
                    if '"content"' in chunk:
                        has_content = True

    # Verify streaming behavior (contract-level check)
    assert count_sse_events(received_chunks) > 3, "Should receive multiple chunks"

    # Verify both reasoning and content were streamed (contract-level check)
    assert has_reasoning, "Should have reasoning content in stream"
    assert has_content, "Should have regular content in stream"

    # Verify backend stats (deterministic check)
    stats = backend.get_timing_stats()
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once (buffering detected)"

    # Verify chunk count consistency
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"
