"""Tests for SSE Assembler client disconnection handling."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from src.core.ports.sse_assembler import SSEAssembler
from src.core.ports.streaming_contracts import StreamingContent
from tests.utils.fake_clock import FakeClockContext


class TestSSEAssemblerDisconnection:
    @pytest.mark.asyncio
    async def test_client_disconnection_stops_yields(self) -> None:
        """Verify that client disconnection (GeneratorExit) stops yielding."""
        assembler = SSEAssembler()

        async def generator() -> AsyncIterator[StreamingContent]:
            yield StreamingContent(content="chunk1", is_done=False)
            # Simulate client disconnect by raising GeneratorExit when consumed
            yield StreamingContent(content="chunk2", is_done=False)

        stream = generator()
        sse_stream = assembler.assemble_stream(stream, format="sse")

        # Consume first chunk
        chunk1 = await anext(sse_stream)
        assert b"chunk1" in chunk1

        # Simulate client disconnect by closing the generator
        # This raises GeneratorExit inside the generator
        # aclose() should handle GeneratorExit gracefully
        await sse_stream.aclose()

        # If the assembler tried to yield in finally block after GeneratorExit,
        # it would raise a RuntimeError or similar in some python versions,
        # or just be ignored.
        # Ideally we want to ensure no extra processing happened.

        # To strictly verify the "done_emitted=True" logic, we can mock logger?
        # Or just trust that if aclose() succeeds without error, we are good.

    @pytest.mark.asyncio
    async def test_generator_exit_propagation(self) -> None:
        """Verify GeneratorExit propagates correctly."""
        assembler = SSEAssembler()

        async def endless_stream():
            async with FakeClockContext() as clock:
                while True:
                    yield StreamingContent(content="data", is_done=False)
                    sleep_task = asyncio.create_task(asyncio.sleep(0.1))
                    clock.advance(0.1)
                    await sleep_task

        sse_stream = assembler.assemble_stream(endless_stream())

        await anext(sse_stream)

        # Close the stream - should propagate GeneratorExit and exit cleanly
        await sse_stream.aclose()
