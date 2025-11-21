from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

import pytest
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.core.interfaces.loop_detector_interface import (
    ILoopDetector,
    LoopDetectionResult,
)
from src.core.ports.streaming import StreamingContent
from src.core.services.json_repair_service import JsonRepairService
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.loop_detection.event import LoopDetectionEvent


@pytest.mark.asyncio
async def test_content_accumulation_isolates_parallel_streams() -> None:
    normalizer = StreamNormalizer([ContentAccumulationProcessor()])

    async def run_stream(chunks: list[str]) -> str:
        async def stream() -> AsyncGenerator[str, None]:
            for chunk in chunks:
                await asyncio.sleep(0)
                yield chunk
            await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        collected: list[str] = []
        async for item in normalizer.process_stream(stream(), output_format="objects"):
            if item.content:
                collected.append(item.content)
        return "".join(collected)

    left, right = await asyncio.gather(
        run_stream(["alpha ", "beta"]),
        run_stream(["gamma ", "delta"]),
    )

    assert left == "alpha beta"
    assert right == "gamma delta"


@pytest.mark.asyncio
async def test_tool_call_repair_isolates_parallel_streams() -> None:
    repair_processor = ToolCallRepairProcessor(ToolCallRepairService())
    normalizer = StreamNormalizer([repair_processor])

    async def run_stream(name: str) -> dict[str, object]:
        async def stream() -> AsyncGenerator[str, None]:
            await asyncio.sleep(0)
            yield f'TOOL CALL: {name} {{"arg": 1}}'
            await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        tool_calls: list[dict[str, object]] = []
        async for item in normalizer.process_stream(stream(), output_format="objects"):
            # Check for tool calls in metadata, not content
            item_tool_calls = item.metadata.get("tool_calls")
            if isinstance(item_tool_calls, list):
                tool_calls.extend(item_tool_calls)
        assert tool_calls, "Expected repaired tool call"
        return tool_calls[-1]

    first, second = await asyncio.gather(run_stream("first"), run_stream("second"))

    assert first["function"]["name"] == "first"
    assert second["function"]["name"] == "second"


@pytest.mark.asyncio
async def test_json_repair_isolates_parallel_streams() -> None:
    json_processor = JsonRepairProcessor(
        JsonRepairService(), buffer_cap_bytes=4096, strict_mode=False
    )
    normalizer = StreamNormalizer([json_processor])

    async def run_stream(prefix: str, value: int) -> list[dict[str, object]]:
        async def stream() -> AsyncGenerator[object, None]:
            await asyncio.sleep(0)
            yield prefix
            await asyncio.sleep(0)
            yield f"{{'value': {value},}}"
            await asyncio.sleep(0)
            yield b"data: [DONE]\n\n"

        parsed_chunks: list[dict[str, object]] = []
        async for item in normalizer.process_stream(stream(), output_format="objects"):
            content = item.content or ""
            brace_idx = content.find("{")
            if brace_idx != -1:
                try:
                    parsed = json.loads(content[brace_idx:])
                except json.JSONDecodeError:
                    continue
                parsed_chunks.append(parsed)
        return parsed_chunks

    first_results, second_results = await asyncio.gather(
        run_stream("first stream ", 1), run_stream("second stream ", 2)
    )

    assert any(chunk.get("value") == 1 for chunk in first_results)
    assert any(chunk.get("value") == 2 for chunk in second_results)
    assert all(chunk.get("value") != 2 for chunk in first_results)
    assert all(chunk.get("value") != 1 for chunk in second_results)


class _DummyLoopDetector(ILoopDetector):
    def __init__(self) -> None:
        self.chunks: list[str] = []

    def is_enabled(self) -> bool:
        return True

    def process_chunk(self, chunk: str):
        self.chunks.append(chunk)
        return None

    def reset(self) -> None:
        self.chunks.clear()

    def get_loop_history(self):
        return []

    def get_current_state(self):
        return {"chunks": list(self.chunks)}

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        self.chunks.append(content)
        return LoopDetectionResult(has_loop=False)


class _TriggeringLoopDetector(ILoopDetector):
    """Detector that fires a loop event on the first chunk."""

    def __init__(self) -> None:
        self.triggered = False

    def is_enabled(self) -> bool:
        return True

    def process_chunk(self, chunk: str):
        if self.triggered:
            return None
        self.triggered = True
        return LoopDetectionEvent(
            pattern="loop",
            pattern_length=len("loop"),
            repetition_count=2,
            total_length=len(chunk),
            confidence=1.0,
            buffer_content=chunk,
            timestamp=0.0,
        )

    def reset(self) -> None:
        self.triggered = False

    def get_loop_history(self):
        return []

    def get_current_state(self):
        return {"triggered": self.triggered}

    async def check_for_loops(self, content: str) -> LoopDetectionResult:
        return LoopDetectionResult(has_loop=False)


@pytest.mark.asyncio
async def test_loop_detection_isolates_sessions() -> None:
    processor = LoopDetectionProcessor(loop_detector_factory=_DummyLoopDetector)

    async def run_session(session_id: str, finish: bool = False) -> None:
        for chunk in ("alpha", "beta"):
            content = StreamingContent(
                content=f"{session_id}:{chunk}", metadata={"session_id": session_id}
            )
            await processor.process(content)
        if finish:
            await processor.process(
                StreamingContent(
                    content="", is_done=True, metadata={"session_id": session_id}
                )
            )

    await asyncio.gather(
        run_session("session-1"),
        run_session("session-2"),
    )

    assert set(processor._session_detectors.keys()) == {"session-1", "session-2"}
    for session_id, detector in processor._session_detectors.items():
        assert all(chunk.startswith(f"{session_id}:") for chunk in detector.chunks)

    await asyncio.gather(
        run_session("session-1", finish=True),
        run_session("session-2", finish=True),
    )
    assert processor._session_detectors == {}


@pytest.mark.asyncio
async def test_loop_detection_assigns_stream_id_when_missing() -> None:
    processor = LoopDetectionProcessor(loop_detector_factory=_DummyLoopDetector)
    content = StreamingContent(content="hello")
    assert "stream_id" not in content.metadata
    await processor.process(content)
    assert "stream_id" in content.metadata


@pytest.mark.asyncio
async def test_loop_detection_cancellation_does_not_leak_text() -> None:
    processor = LoopDetectionProcessor(loop_detector_factory=_TriggeringLoopDetector)

    # First chunk triggers loop detection
    cancellation = await processor.process(
        StreamingContent(content="repeating", metadata={"session_id": "s1"})
    )
    assert cancellation.is_cancellation
    assert cancellation.is_done
    assert cancellation.content == ""
    assert cancellation.metadata.get("loop_detected") is True

    # Subsequent chunk for same session should also be cancelled quietly
    follow_up = await processor.process(
        StreamingContent(content="repeating-again", metadata={"session_id": "s1"})
    )
    assert follow_up.is_cancellation
    assert follow_up.is_done
