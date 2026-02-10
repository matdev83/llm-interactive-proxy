"""Regression tests for loop detection on metadata-only streaming chunks."""

import pytest
from src.core.domain.streaming_response_processor import LoopDetectionProcessor
from src.core.ports.streaming_contracts import StreamingContent
from src.loop_detection.hybrid_detector import HybridLoopDetector


def _create_sensitive_detector() -> HybridLoopDetector:
    """Create a detector config that surfaces false positives quickly in tests."""
    return HybridLoopDetector(
        short_detector_config={
            "content_chunk_size": 10,
            "content_loop_threshold": 2,
            "max_history_length": 512,
        },
        long_detector_config={
            "min_pattern_length": 40,
            "max_pattern_length": 4096,
            "min_repetitions": 2,
            "max_history": 4096,
        },
    )


@pytest.mark.asyncio
async def test_metadata_only_openai_chunks_do_not_trigger_loop_detection() -> None:
    """Repeated metadata-only chunks should not be treated as content loops."""
    processor = LoopDetectionProcessor(
        loop_detector_factory=_create_sensitive_detector,
        min_chunks_before_detection=1,
    )

    payload = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 123,
        "model": "test-model",
        "choices": [
            {
                "index": 0,
                "finish_reason": None,
                "delta": {
                    "reasoning_content": ".",
                    "reasoning": ".",
                    "thinking": ".",
                    "thought": ".",
                    "content": "",
                },
            }
        ],
    }

    for _ in range(25):
        chunk = StreamingContent(
            content=payload, metadata={"session_id": "metadata-only"}
        )
        result = await processor.process(chunk)
        assert not result.is_cancellation
        assert result.metadata.get("loop_detected") is not True


@pytest.mark.asyncio
async def test_visible_text_still_triggers_loop_detection() -> None:
    """Loop detection should still trigger for repeated visible output text."""
    processor = LoopDetectionProcessor(
        loop_detector_factory=_create_sensitive_detector,
        min_chunks_before_detection=1,
    )

    cancelled = False
    for _ in range(12):
        chunk = StreamingContent(
            content={
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": None,
                        "delta": {"content": "REPEAT REPEAT REPEAT "},
                    }
                ]
            },
            metadata={"session_id": "visible-text"},
        )
        result = await processor.process(chunk)
        if result.is_cancellation:
            cancelled = True
            break

    assert cancelled is True
