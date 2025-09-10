from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from src.core.domain.streaming_response_processor import (
    LoopDetectionProcessor,
    StreamingContent,
)
from src.core.interfaces.loop_detector_interface import ILoopDetector
from src.core.services.streaming.json_repair_processor import JsonRepairProcessor
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService
from src.loop_detection.event import LoopDetectionEvent


class SimpleLoopDetector(ILoopDetector):
    """A minimal loop detector that flags a loop when a trigger substring appears."""

    def __init__(self, trigger: str = "LOOP!") -> None:
        self._trigger = trigger
        self._fired = False
        self._history: list[LoopDetectionEvent] = []

    def is_enabled(self) -> bool:  # pragma: no cover - trivial
        return True

    def process_chunk(self, chunk: str) -> LoopDetectionEvent | None:
        if self._fired:
            return None
        if chunk and self._trigger in chunk:
            # Create a simple event
            evt = LoopDetectionEvent(
                pattern=self._trigger,
                repetition_count=4,
                total_length=len(chunk),
                confidence=0.99,
                buffer_content=chunk,
                timestamp=0.0,
            )
            self._history.append(evt)
            self._fired = True
            return evt
        return None

    def reset(self) -> None:  # pragma: no cover - unused here
        self._fired = False
        self._history.clear()

    def get_loop_history(self) -> list[LoopDetectionEvent]:  # pragma: no cover - unused
        return list(self._history)

    def get_current_state(self) -> dict[str, object]:  # pragma: no cover - unused
        return {"fired": self._fired}

    async def check_for_loops(self, content: str):  # pragma: no cover - legacy path
        # Not used by LoopDetectionProcessor in this pipeline
        return None


@pytest.mark.asyncio
async def test_loop_detection_runs_before_tool_call_repair() -> None:
    # Processors in the intended order
    json_proc = JsonRepairProcessor(
        repair_service=__import__(
            "src.core.services.json_repair_service", fromlist=["JsonRepairService"]
        ).JsonRepairService(),
        buffer_cap_bytes=4096,
        strict_mode=False,
    )
    loop_proc = LoopDetectionProcessor(loop_detector=SimpleLoopDetector("LOOP!"))
    tool_proc = ToolCallRepairProcessor(ToolCallRepairService())
    normalizer = StreamNormalizer([json_proc, loop_proc, tool_proc])

    # Stream: repetitive text that should trigger loop detection, then a textual tool call
    async def stream() -> AsyncGenerator[str, None]:
        yield "Prelude "
        yield "LOOP! LOOP! LOOP! LOOP!"
        yield ' and TOOL CALL: myfunc {"x":1}'

    outputs: list[StreamingContent] = []
    async for item in normalizer.process_stream(stream(), output_format="objects"):
        outputs.append(item)

    # Expect a cancellation output from LoopDetectionProcessor
    assert any(o.is_cancellation for o in outputs)
    # Ensure no tool_call conversion occurred before cancellation
    cancel_idx = next(i for i, o in enumerate(outputs) if o.is_cancellation)
    assert not any(
        '"type": "function"' in (o.content or "") for o in outputs[: cancel_idx + 1]
    )
