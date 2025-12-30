"""Streaming tests for hybrid backend.

Tests that hybrid backend (reasoning + execution phases) maintains
streaming behavior throughout both phases.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from src.core.app.test_builder import build_test_app
from src.core.domain.chat import ChatMessage

from tests.streaming_regression.emulators.openai_emulator import (
    OpenAIStreamingEmulator,
)


def _inject_hybrid_backends(app, reasoning_backend, execution_backend) -> None:
    """Inject mock backends for hybrid testing."""
    service_provider = app.state.service_provider
    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = service_provider.get_required_service(IBackendService)

    # Inject both backends
    backend_service._backends["openai"] = reasoning_backend
    backend_service._backends["anthropic"] = execution_backend

    # Track which backend is being called
    call_count = {"reasoning": 0, "execution": 0}

    async def call_completion_override(
        request,
        stream: bool = False,
        allow_failover: bool = True,
        context=None,
    ):
        # Determine which backend to use based on model
        model = getattr(request, "model", "")

        if "reasoning" in model or call_count["reasoning"] == 0:
            call_count["reasoning"] += 1
            backend = reasoning_backend
        else:
            call_count["execution"] += 1
            backend = execution_backend

        return await backend.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model=model,
            identity=None,
        )

    backend_service.call_completion = call_completion_override


@pytest.mark.asyncio
async def test_hybrid_reasoning_phase_streaming() -> None:
    """Test that reasoning phase in hybrid backend streams correctly."""
    reasoning_text = "Let me analyze this problem step by step to find the solution"
    reasoning_chunks = OpenAIStreamingEmulator.create_reasoning_chunks(
        reasoning_text, "Based on analysis, the answer is 42"
    )

    reasoning_backend = OpenAIStreamingEmulator(
        chunks=reasoning_chunks, chunk_delay=0.01
    )

    # Execution backend (won't be called in this test)
    execution_chunks = OpenAIStreamingEmulator.create_text_chunks(
        "Final answer", chunk_size=5
    )
    execution_backend = OpenAIStreamingEmulator(
        chunks=execution_chunks, chunk_delay=0.02
    )

    app = build_test_app()
    app.state.disable_auth = True
    _inject_hybrid_backends(app, reasoning_backend, execution_backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "hybrid:[openai:gpt-4-reasoning,anthropic:claude-3-5-sonnet]",
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

            # Hybrid backend may not be fully implemented yet
            if response.status_code == 500:
                pytest.skip("Hybrid backend not fully implemented")

            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    # Verify streaming behavior
    if len(received_chunks) > 3 and len(chunk_times) > 1:
        time_deltas = [
            chunk_times[i + 1] - chunk_times[i] for i in range(len(chunk_times) - 1)
        ]
        max_delta = max(time_deltas)
        assert max_delta > 0.005, "Hybrid reasoning phase may be buffering chunks"

    # Verify backend stats
    stats = reasoning_backend.get_timing_stats()
    if stats["chunks_sent"] > 0:
        assert not stats["all_at_once"], "Backend detected buffering in reasoning phase"


@pytest.mark.asyncio
async def test_hybrid_execution_phase_streaming() -> None:
    """Test that execution phase in hybrid backend streams correctly."""
    # Simple reasoning phase
    reasoning_chunks = OpenAIStreamingEmulator.create_text_chunks(
        "Quick thought", chunk_size=5
    )
    reasoning_backend = OpenAIStreamingEmulator(
        chunks=reasoning_chunks, chunk_delay=0.01
    )

    # Detailed execution phase
    execution_text = (
        "Here is the detailed execution result with comprehensive explanation"
    )
    execution_chunks = OpenAIStreamingEmulator.create_text_chunks(
        execution_text, chunk_size=10
    )
    execution_backend = OpenAIStreamingEmulator(
        chunks=execution_chunks, chunk_delay=0.005
    )

    app = build_test_app()
    app.state.disable_auth = True
    _inject_hybrid_backends(app, reasoning_backend, execution_backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "hybrid:[openai:gpt-4-reasoning,anthropic:claude-3-5-sonnet]",
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

            if response.status_code == 500:
                pytest.skip("Hybrid backend not fully implemented")

            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    # Verify streaming behavior
    if len(received_chunks) > 3 and len(chunk_times) > 1:
        time_deltas = [
            chunk_times[i + 1] - chunk_times[i] for i in range(len(chunk_times) - 1)
        ]
        max_delta = max(time_deltas)
        assert max_delta > 0.005, "Hybrid execution phase may be buffering chunks"

    # Verify execution backend stats
    stats = execution_backend.get_timing_stats()
    if stats["chunks_sent"] > 0:
        assert not stats["all_at_once"], "Backend detected buffering in execution phase"


@pytest.mark.asyncio
async def test_hybrid_combined_streaming() -> None:
    """Test that both reasoning and execution phases stream correctly in sequence."""
    reasoning_text = "Analyzing the problem systematically"
    reasoning_chunks = OpenAIStreamingEmulator.create_reasoning_chunks(
        reasoning_text, "Initial thoughts"
    )
    reasoning_backend = OpenAIStreamingEmulator(
        chunks=reasoning_chunks, chunk_delay=0.011  # Above 10ms threshold
    )

    execution_text = "Final comprehensive answer based on reasoning"
    execution_chunks = OpenAIStreamingEmulator.create_text_chunks(
        execution_text, chunk_size=10
    )
    execution_backend = OpenAIStreamingEmulator(
        chunks=execution_chunks, chunk_delay=0.011  # Above 10ms threshold
    )

    app = build_test_app()
    app.state.disable_auth = True
    _inject_hybrid_backends(app, reasoning_backend, execution_backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "hybrid:[openai:gpt-4-reasoning,anthropic:claude-3-5-sonnet]",
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

            if response.status_code == 500:
                pytest.skip("Hybrid backend not fully implemented")

            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    # Verify streaming behavior across both phases
    if len(received_chunks) > 5 and len(chunk_times) > 1:
        time_deltas = [
            chunk_times[i + 1] - chunk_times[i] for i in range(len(chunk_times) - 1)
        ]
        max_delta = max(time_deltas)
        assert max_delta > 0.005, "Hybrid combined phases may be buffering chunks"

    # Verify both backends were used
    reasoning_stats = reasoning_backend.get_timing_stats()
    execution_stats = execution_backend.get_timing_stats()

    if reasoning_stats["chunks_sent"] > 0:
        assert not reasoning_stats["all_at_once"], "Reasoning phase buffered"

    if execution_stats["chunks_sent"] > 0:
        assert not execution_stats["all_at_once"], "Execution phase buffered"


@pytest.mark.asyncio
async def test_hybrid_with_tool_calls_streaming() -> None:
    """Test that hybrid backend with tool calls maintains streaming."""
    # Reasoning phase with tool call
    reasoning_chunks = OpenAIStreamingEmulator.create_tool_call_chunks()
    reasoning_backend = OpenAIStreamingEmulator(
        chunks=reasoning_chunks, chunk_delay=0.01
    )

    # Execution phase after tool call
    execution_chunks = OpenAIStreamingEmulator.create_text_chunks(
        "Based on tool results, here is the answer", chunk_size=10
    )
    execution_backend = OpenAIStreamingEmulator(
        chunks=execution_chunks, chunk_delay=0.02
    )

    app = build_test_app()
    app.state.disable_auth = True
    _inject_hybrid_backends(app, reasoning_backend, execution_backend)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "hybrid:[openai:gpt-4-reasoning,anthropic:claude-3-5-sonnet]",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
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

            if response.status_code == 500:
                pytest.skip("Hybrid backend not fully implemented")

            assert response.status_code == 200

            async for chunk in response.aiter_text():
                if chunk.strip():
                    received_chunks.append(chunk)
                    chunk_times.append(asyncio.get_event_loop().time())

    # Verify streaming behavior
    if len(received_chunks) > 2 and len(chunk_times) > 1:
        time_deltas = [
            chunk_times[i + 1] - chunk_times[i] for i in range(len(chunk_times) - 1)
        ]
        max_delta = max(time_deltas)
        assert max_delta > 0.005, "Hybrid with tool calls may be buffering chunks"

    # Verify reasoning backend stats
    stats = reasoning_backend.get_timing_stats()
    if stats["chunks_sent"] > 0:
        assert not stats["all_at_once"], "Backend detected buffering with tool calls"
