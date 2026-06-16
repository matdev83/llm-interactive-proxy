from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.composite_routing_state import PARALLEL_COMPLETION_ACTIVE_KEY
from src.core.services.parallel_completion_orchestrator import (
    ParallelCompletionOrchestrator,
    try_parse_parallel_plan,
)


def _parallel_plan() -> CompositeRoutePlan:
    return CompositeRoutePlan(
        source_selector="openai:gpt-4!anthropic:claude-3",
        normalized_selector="openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        uri_params={},
                    )
                ),
            ]
        ),
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-parallel",
        session_id="session-parallel",
    )


def _request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="openai:gpt-4!anthropic:claude-3",
        messages=[ChatMessage(role="user", content="hello")],
    )


async def _stream_from_tokens(
    tokens: list[Any],
) -> AsyncIterator[ProcessedResponse]:
    for token in tokens:
        yield token


def _streaming_envelope(
    tokens: list[Any],
    *,
    cancel_callback: AsyncMock | None = None,
) -> StreamingResponseEnvelope:
    return StreamingResponseEnvelope(
        content=_stream_from_tokens(tokens),
        cancel_callback=cancel_callback,
    )


def test_try_parse_parallel_plan_detects_top_level_parallel_selector() -> None:
    plan = try_parse_parallel_plan(_request(), _context())
    assert plan is not None
    assert isinstance(plan.root_node, CompositeParallelGroupNode)


def test_try_parse_parallel_plan_returns_none_for_failover_selector() -> None:
    request = CanonicalChatRequest(
        model="openai:gpt-4|anthropic:claude-3",
        messages=[ChatMessage(role="user", content="hello")],
    )
    assert try_parse_parallel_plan(request, _context()) is None


@pytest.mark.asyncio
async def test_orchestrator_non_streaming_aggregates_winner_stream() -> None:
    orchestrator = ParallelCompletionOrchestrator()

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        assert stream is True
        assert request.stream is True
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={
                            "id": "chatcmpl-win",
                            "created": 123,
                            "model": "openai:gpt-4",
                            "choices": [
                                {
                                    "delta": {
                                        "content": "hello",
                                        "reasoning_content": "think",
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": "call_1",
                                                "type": "function",
                                                "function": {
                                                    "name": "f",
                                                    "arguments": '{"a"',
                                                },
                                            }
                                        ],
                                    }
                                }
                            ],
                        }
                    ),
                    ProcessedResponse(
                        content={
                            "model": "openai:gpt-4",
                            "choices": [
                                {
                                    "delta": {
                                        "content": " world",
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "function": {"arguments": ":1}"},
                                            }
                                        ],
                                    },
                                    "finish_reason": "tool_calls",
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 1,
                                "completion_tokens": 2,
                                "total_tokens": 3,
                            },
                        }
                    ),
                ]
            )
        return _streaming_envelope([])

    response = await orchestrator.execute(
        plan=_parallel_plan(),
        request=_request(),
        context=_context(),
        stream=False,
        call_completion=call_completion,
    )

    assert isinstance(response, ResponseEnvelope)
    assert isinstance(response.content, dict)
    assert response.content["model"] == "openai:gpt-4"
    assert response.content["usage"] == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
    }
    choice = response.content["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    message = choice["message"]
    assert message["content"] == "hello world"
    assert message["reasoning_content"] == "think"
    assert message["reasoning"] == "think"
    assert message["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "f", "arguments": '{"a":1}'},
        }
    ]


@pytest.mark.asyncio
async def test_orchestrator_non_streaming_aggregates_sse_framed_winner_chunks() -> None:
    orchestrator = ParallelCompletionOrchestrator()

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        assert stream is True
        assert request.stream is True
        del allow_failover, context
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content=(
                            b'data: {"id":"chatcmpl-sse","object":"chat.completion.chunk",'
                            b'"created":123,"model":"openai:gpt-4","choices":[{"index":0,'
                            b'"delta":{"content":"sse ","reasoning_content":"think "},'
                            b'"finish_reason":null}]}\n\n'
                        )
                    ),
                    ProcessedResponse(
                        content=(
                            'data: {"id":"chatcmpl-sse","object":"chat.completion.chunk",'
                            '"created":123,"model":"openai:gpt-4","choices":[{"index":0,'
                            '"delta":{"content":"chunk","reasoning_content":"more",'
                            '"tool_calls":[{"index":0,"id":"call_sse","type":"function",'
                            '"function":{"name":"tool","arguments":"{}"}}]},'
                            '"finish_reason":"tool_calls"}]}\n\n'
                        )
                    ),
                ]
            )
        return _streaming_envelope([])

    response = await orchestrator.execute(
        plan=_parallel_plan(),
        request=_request(),
        context=_context(),
        stream=False,
        call_completion=call_completion,
    )

    assert isinstance(response, ResponseEnvelope)
    assert isinstance(response.content, dict)
    assert response.content["id"] == "chatcmpl-sse"
    message = response.content["choices"][0]["message"]
    assert message["content"] == "sse chunk"
    assert message["reasoning_content"] == "think more"
    assert message["tool_calls"] == [
        {
            "id": "call_sse",
            "type": "function",
            "function": {"name": "tool", "arguments": "{}"},
        }
    ]


@pytest.mark.asyncio
async def test_orchestrator_starts_legs_and_bridges_winner_token() -> None:
    started: list[str] = []
    cancel_a = AsyncMock()

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        assert stream is True
        assert allow_failover is False
        assert context is not None
        assert context.extensions.get(PARALLEL_COMPLETION_ACTIVE_KEY) is True
        started.append(request.model)
        if request.model == "openai:gpt-4":
            return _streaming_envelope([], cancel_callback=cancel_a)
        return _streaming_envelope(
            [ProcessedResponse(content={"choices": [{"delta": {"content": "win"}}]})],
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = await orchestrator.execute(
        plan=_parallel_plan(),
        request=_request(),
        context=_context(),
        stream=True,
        call_completion=call_completion,
    )
    assert isinstance(envelope, StreamingResponseEnvelope)
    assert envelope.content is not None

    chunks: list[ProcessedResponse] = []
    async for chunk in envelope.content:
        chunks.append(chunk)

    assert set(started) == {"openai:gpt-4", "anthropic:claude-3"}
    assert len(chunks) == 1
    assert chunks[0].content == {"choices": [{"delta": {"content": "win"}}]}
    cancel_a.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_cancel_callback_stops_all_legs() -> None:
    cancel_a = AsyncMock()
    cancel_b = AsyncMock()
    release = asyncio.Event()

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        async def _blocked_stream() -> AsyncIterator[ProcessedResponse]:
            await release.wait()
            yield ProcessedResponse(content={"choices": [{"delta": {"content": "x"}}]})

        if request.model == "openai:gpt-4":
            return StreamingResponseEnvelope(
                content=_blocked_stream(),
                cancel_callback=cancel_a,
            )
        return StreamingResponseEnvelope(
            content=_blocked_stream(),
            cancel_callback=cancel_b,
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = await orchestrator.execute(
        plan=_parallel_plan(),
        request=_request(),
        context=_context(),
        stream=True,
        call_completion=call_completion,
    )
    assert envelope.content is not None
    assert envelope.cancel_callback is not None

    consume_task = asyncio.create_task(_drain_stream(envelope.content))
    await asyncio.sleep(0.05)
    await envelope.cancel_callback()
    await asyncio.sleep(0.05)
    if not consume_task.done():
        consume_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consume_task

    cancel_a.assert_awaited_once()
    cancel_b.assert_awaited_once()


async def _drain_stream(stream: AsyncIterator[ProcessedResponse]) -> None:
    async for _chunk in stream:
        return


@pytest.mark.asyncio
async def test_orchestrator_cancel_callback_after_winner_bridged_cancels_winner_leg() -> (
    None
):
    cancel_a = AsyncMock()
    cancel_b = AsyncMock()
    release_winner_rest = asyncio.Event()

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        async def _winner_stream() -> AsyncIterator[ProcessedResponse]:
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "win-first"}}]},
            )
            await release_winner_rest.wait()
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "win-rest"}}]},
            )

        async def _loser_stream() -> AsyncIterator[ProcessedResponse]:
            await asyncio.Event().wait()
            yield ProcessedResponse(
                content={"choices": [{"delta": {"content": "lose"}}]},
            )

        if request.model == "openai:gpt-4":
            return StreamingResponseEnvelope(
                content=_loser_stream(),
                cancel_callback=cancel_a,
            )
        return StreamingResponseEnvelope(
            content=_winner_stream(),
            cancel_callback=cancel_b,
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = await orchestrator.execute(
        plan=_parallel_plan(),
        request=_request(),
        context=_context(),
        stream=True,
        call_completion=call_completion,
    )
    assert envelope.content is not None
    assert envelope.cancel_callback is not None

    chunks: list[ProcessedResponse] = []
    async for chunk in envelope.content:
        chunks.append(chunk)
        if isinstance(chunk.content, dict) and chunk.content.get("choices"):
            break

    assert envelope.cancel_callback is not None
    await envelope.cancel_callback()

    cancel_a.assert_awaited_once()
    cancel_b.assert_awaited_once()
    assert any(
        chunk.content == {"choices": [{"delta": {"content": "win-first"}}]}
        for chunk in chunks
    )
