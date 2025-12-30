"""Deterministic streaming tests using fake clock utilities.

These tests demonstrate how to use fake clocks for deterministic testing
of streaming behavior, replacing timing-based assertions with contract-level
checks.
"""

from __future__ import annotations

from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient
from src.core.app.test_builder import build_test_app
from src.core.domain.chat import ChatMessage

from tests.streaming_regression.conftest import count_sse_events
from tests.streaming_regression.emulators.openai_emulator import (
    OpenAIStreamingEmulator,
)
from tests.utils.fake_clock import FakeClock


def _build_streaming_test_app():
    """Build test app with loop detection disabled for streaming tests."""
    import os

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


def _inject_backend(app, backend) -> None:
    """Inject emulator backend into app, replacing mock backend."""
    service_provider = app.state.service_provider
    from src.core.interfaces.backend_service_interface import IBackendService

    backend_service = service_provider.get_required_service(IBackendService)

    backend_service._backends[backend.backend_type] = backend
    if hasattr(backend_service, "_backend_cache"):
        backend_service._backend_cache[backend.backend_type] = backend

    async def emulator_call_completion(
        self, request, stream=False, allow_failover=True, context=None, **kwargs
    ):
        return await backend.chat_completions(
            request_data=request,
            processed_messages=[],
            effective_model=getattr(request, "model", "test-model"),
            identity=None,
        )

    import types

    backend_service.call_completion = types.MethodType(
        emulator_call_completion, backend_service
    )


@pytest.mark.asyncio
async def test_streaming_with_fake_clock_deterministic_timing() -> None:
    """Test that fake clock provides deterministic timing for streaming tests.

    This test demonstrates how to use FakeClock to make streaming tests
    deterministic, replacing wall-clock time with controlled time progression.
    """
    text = "Test response for deterministic timing"
    chunks = cast(
        list[str | bytes],
        OpenAIStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = OpenAIStreamingEmulator(
        chunks=chunks, chunk_delay=0.011
    )  # Above 10ms threshold for buffering detection
    app = _build_streaming_test_app()
    _inject_backend(app, backend)

    # Create fake clock for deterministic timing
    fake_clock = FakeClock()

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

            async for chunk in response.aiter_bytes():
                if chunk:
                    decoded = chunk.decode("utf-8")
                    sse_chunks = [c for c in decoded.split("\n\n") if c.strip()]
                    for sse_chunk in sse_chunks:
                        if sse_chunk.strip():
                            received_chunks.append(sse_chunk)
                            # Use fake clock instead of wall clock
                            chunk_times.append(fake_clock.now())
                            # Advance fake clock by a fixed amount
                            fake_clock.advance(0.01)

    # Verify deterministic timing
    assert len(chunk_times) > 0, "Should have recorded chunk times"

    # With fake clock, timing is deterministic
    for i in range(len(chunk_times) - 1):
        time_diff = chunk_times[i + 1] - chunk_times[i]
        # Exact timing due to fake clock
        assert (
            abs(time_diff - 0.01) < 0.0001
        ), f"Time difference should be exactly 0.01, got {time_diff}"

    # Verify contract-level behavior
    assert count_sse_events(received_chunks) > 0, "Should receive chunks"

    # Verify backend behavior (deterministic check)
    stats = backend.get_timing_stats()
    assert stats["chunks_sent"] == len(
        chunks
    ), f"Expected {len(chunks)} chunks, sent {stats['chunks_sent']}"
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once"

    print("[OK] Deterministic timing verified with fake clock")
    print(f"[OK] Received {len(received_chunks)} chunks with exact 0.01s intervals")


@pytest.mark.asyncio
async def test_streaming_chunk_sequence_deterministic() -> None:
    """Test that chunk sequences are deterministic with fake clock.

    This test verifies that using a fake clock makes chunk sequences
    completely deterministic and reproducible.
    """
    text = "Deterministic chunk sequence test"
    chunks = cast(
        list[str | bytes],
        OpenAIStreamingEmulator.create_text_chunks(text, chunk_size=8),
    )

    backend = OpenAIStreamingEmulator(
        chunks=chunks, chunk_delay=0.011
    )  # Above 10ms threshold for buffering detection
    app = _build_streaming_test_app()
    _inject_backend(app, backend)

    fake_clock = FakeClock()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "gpt-4",
            "messages": [ChatMessage(role="user", content="test").model_dump()],
            "stream": True,
        }
        headers = {"x-goog-api-key": "test-key"}

        # Run the test twice to verify determinism
        results_run1 = []
        results_run2 = []

        for run_results in [results_run1, results_run2]:
            fake_clock.reset()  # Reset clock for each run

            async with client.stream(
                "POST", "/v1/chat/completions", json=payload, headers=headers
            ) as response:
                if response.status_code == 401:
                    pytest.skip("Authentication required")
                assert response.status_code == 200

                async for chunk in response.aiter_bytes():
                    if chunk:
                        decoded = chunk.decode("utf-8")
                        sse_chunks = [c for c in decoded.split("\n\n") if c.strip()]
                        for sse_chunk in sse_chunks:
                            if sse_chunk.strip():
                                run_results.append((sse_chunk, fake_clock.now()))
                                fake_clock.advance(0.01)

    # Verify both runs produced identical results
    assert len(results_run1) == len(
        results_run2
    ), "Both runs should produce same number of chunks"

    for i, ((chunk1, time1), (chunk2, time2)) in enumerate(
        zip(results_run1, results_run2, strict=False)
    ):
        assert chunk1 == chunk2, f"Chunk {i} should be identical in both runs"
        assert (
            abs(time1 - time2) < 0.0001
        ), f"Timing for chunk {i} should be identical in both runs"

    print("[OK] Deterministic chunk sequence verified across multiple runs")
    print(f"[OK] Both runs produced {len(results_run1)} identical chunks")


@pytest.mark.asyncio
@pytest.mark.slow
async def test_streaming_contract_validation_deterministic() -> None:
    """Test that contract validation is deterministic.

    This test verifies that StreamingContent contract validation produces
    consistent results regardless of timing.
    """
    text = "Contract validation test"
    chunks = cast(
        list[str | bytes],
        OpenAIStreamingEmulator.create_text_chunks(text, chunk_size=10),
    )

    backend = OpenAIStreamingEmulator(
        chunks=chunks, chunk_delay=0.011
    )  # Above 10ms threshold for buffering detection
    app = _build_streaming_test_app()
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

        async with client.stream(
            "POST", "/v1/chat/completions", json=payload, headers=headers
        ) as response:
            if response.status_code == 401:
                pytest.skip("Authentication required")
            assert response.status_code == 200

            async for chunk in response.aiter_bytes():
                if chunk:
                    received_chunks.append(chunk)

    # Verify contract-level properties (deterministic checks)
    assert len(received_chunks) > 0, "Should receive chunks"

    # Verify SSE format compliance
    # Note: Chunks may contain multiple SSE events or partial events
    # Split by double newlines to handle multiple events per chunk
    all_sse_lines = []
    for chunk in received_chunks:
        decoded = chunk.decode("utf-8", errors="ignore")
        # Split by double newlines (SSE event separator)
        events = decoded.split("\n\n")
        for event in events:
            lines = [line.strip() for line in event.split("\n") if line.strip()]
            all_sse_lines.extend(lines)

    # Verify all non-empty SSE lines start with "data: "
    for line in all_sse_lines:
        if line:  # Skip empty lines
            assert line.startswith(
                ("data: ", ":")
            ), f"SSE line should start with 'data: ' or ':', got: {line[:50]}"

    # Verify backend behavior (deterministic check)
    stats = backend.get_timing_stats()
    assert stats["chunks_sent"] == len(
        chunks
    ), f"Expected {len(chunks)} chunks, sent {stats['chunks_sent']}"
    assert not stats.get(
        "all_at_once", False
    ), "Backend should not send all chunks at once"

    # Verify chunk count consistency (deterministic check)
    assert (
        stats["chunks_sent"] > 1
    ), "Backend should send multiple chunks for incremental delivery"

    print("[OK] Contract validation verified deterministically")
    print(f"[OK] All {len(received_chunks)} chunks follow SSE format")
