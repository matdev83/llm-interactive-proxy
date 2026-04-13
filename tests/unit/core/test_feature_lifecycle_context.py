"""Unit tests for typed ``FeatureLifecycleContext`` and dict bridge."""

from __future__ import annotations

from typing import Any

import pytest
from src.core.domain.feature_lifecycle_context import (
    FEATURE_LIFECYCLE_CONTEXT_KEY,
    FeatureLifecycleContext,
    attach_feature_lifecycle_context,
    build_feature_lifecycle_context_from_manager_chunk,
    build_feature_lifecycle_context_from_streaming_content,
    feature_lifecycle_context_from_dict,
)
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    ProcessedResponse,
)
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)


def test_build_from_streaming_content_streaming_mode_terminal() -> None:
    chunk = StreamingContent(
        content="hi",
        metadata={
            "session_id": "s1",
            "request_id": "r9",
            "backend_name": "b1",
            "model_name": "m1",
            "finish_reason": "stop",
        },
        is_done=True,
    )
    lc = build_feature_lifecycle_context_from_streaming_content(
        content=chunk,
        response_type="stream",
        session_id="s1",
        stream_id="st-1",
    )
    assert lc.is_streaming is True
    assert lc.is_terminal_chunk is True
    assert lc.finish_reason == "stop"
    assert lc.session_id == "s1"
    assert lc.stream_id == "st-1"
    assert lc.request_id == "r9"
    assert lc.backend_name == "b1"
    assert lc.model_name == "m1"
    assert lc.non_streaming_single_chunk is False


def test_build_from_streaming_content_non_streaming_single_chunk() -> None:
    chunk = StreamingContent(
        content="done",
        metadata={"non_streaming": True, "request_id": "r1"},
        is_done=True,
    )
    lc = build_feature_lifecycle_context_from_streaming_content(
        content=chunk,
        response_type="non_streaming",
        session_id="sess",
        stream_id=None,
    )
    assert lc.is_streaming is False
    assert lc.is_terminal_chunk is True
    assert lc.non_streaming_single_chunk is True
    assert lc.request_id == "r1"


def test_bridge_prefers_embedded_typed_context() -> None:
    embedded = FeatureLifecycleContext(
        is_streaming=True,
        is_terminal_chunk=False,
        finish_reason=None,
        session_id="x",
        stream_id="y",
        request_id=None,
        backend_name=None,
        model_name=None,
        non_streaming_single_chunk=False,
    )
    ctx: dict[str, object] = {
        "response_type": "wrong",
        FEATURE_LIFECYCLE_CONTEXT_KEY: embedded,
    }
    out = feature_lifecycle_context_from_dict(ctx)
    assert out is embedded


def test_bridge_synthesized_streaming_mode() -> None:
    ctx = {
        "response_type": "stream",
        "session_id": "abc",
        "stream_id": "z",
        "finish_reason": "length",
        "request_id": "req",
        "backend_name": "openai",
        "model_name": "gpt",
        "non_streaming": False,
    }
    lc = feature_lifecycle_context_from_dict(ctx, is_streaming=True)
    assert lc.is_streaming is True
    assert lc.is_terminal_chunk is True
    assert lc.finish_reason == "length"
    assert lc.session_id == "abc"
    assert lc.stream_id == "z"


def test_build_from_manager_chunk_processed_response() -> None:
    pr = ProcessedResponse(
        content="x",
        usage=None,
        metadata={"finish_reason": "tool_calls", "is_done": True},
    )
    base: dict[str, object] = {
        "stream_id": "sid",
        "request_id": "rid",
        "backend_name": "be",
        "model_name": "mo",
    }
    lc = build_feature_lifecycle_context_from_manager_chunk(
        chunk=pr,
        is_streaming=True,
        session_id="sess",
        base_context=base,
    )
    assert lc.is_streaming is True
    assert lc.finish_reason == "tool_calls"
    assert lc.is_terminal_chunk is True
    assert lc.stream_id == "sid"


def test_attach_round_trip() -> None:
    lc = FeatureLifecycleContext(
        is_streaming=False,
        is_terminal_chunk=True,
        finish_reason="stop",
        session_id="s",
        stream_id=None,
        request_id="r",
        backend_name=None,
        model_name=None,
        non_streaming_single_chunk=True,
    )
    ctx: dict[str, object] = {"response_type": "complete"}
    attach_feature_lifecycle_context(ctx, lc)
    assert ctx[FEATURE_LIFECYCLE_CONTEXT_KEY] is lc
    assert feature_lifecycle_context_from_dict(ctx) is lc


@pytest.mark.asyncio
async def test_middleware_application_processor_attaches_lifecycle() -> None:
    captured: dict[str, object] = {}

    class _Capture(IResponseMiddleware):
        async def process(
            self,
            response: Any,
            session_id: str,
            context: dict[str, object],
            is_streaming: bool = False,
            stop_event: Any = None,
        ) -> Any:
            captured.clear()
            captured.update(context)
            return response

    processor = MiddlewareApplicationProcessor([_Capture(priority=0)])
    chunk = StreamingContent(
        content="x",
        metadata={"session_id": "s3", "finish_reason": "stop"},
        is_done=True,
    )
    await processor.process(chunk)
    assert FEATURE_LIFECYCLE_CONTEXT_KEY in captured
    flc = captured[FEATURE_LIFECYCLE_CONTEXT_KEY]
    assert isinstance(flc, FeatureLifecycleContext)
    assert flc.finish_reason == "stop"
    assert flc.is_terminal_chunk is True


@pytest.mark.asyncio
async def test_response_logging_feature_uses_bridge() -> None:
    from src.core.services.response_middleware import ResponseLoggingFeature

    f = ResponseLoggingFeature()
    ctx: dict[str, object] = {
        "response_type": "stream",
        "session_id": "s2",
        FEATURE_LIFECYCLE_CONTEXT_KEY: FeatureLifecycleContext(
            is_streaming=True,
            is_terminal_chunk=True,
            finish_reason="error",
            session_id="s2",
            stream_id="st",
            request_id="rq",
            backend_name="bk",
            model_name="md",
            non_streaming_single_chunk=False,
        ),
    }
    pr = ProcessedResponse(content="hello", usage=None, metadata={})
    out = await f.process_chunk(pr, "s2", ctx, is_streaming=True)
    assert out is pr
