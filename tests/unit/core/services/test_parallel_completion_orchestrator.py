from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
    CompositeRoutingInput,
    RoutingSurface,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.composite_routing_state import (
    PARALLEL_COMPLETION_ACTIVE_KEY,
    is_composite_selector,
)
from src.core.services.composite_selector_parser import CompositeSelectorParser
from src.core.services.parallel_completion_orchestrator import (
    ParallelCompletionOrchestrator,
    _try_select_special_thinker_parallel_executor,
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


def test_try_parse_parallel_plan_extracts_executor_first_for_special_route() -> None:
    context = _context()
    request = CanonicalChatRequest(
        model=(
            "[thinker]opencode-go:opencode-go/glm-5.2?reasoning_effort=high^"
            "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
            "opencode-go:minimaxai/minimax-m3"
        ),
        messages=[ChatMessage(role="user", content="hello")],
    )

    plan = try_parse_parallel_plan(request, context)

    assert plan is not None
    assert isinstance(plan.root_node, CompositeParallelGroupNode)
    stored_state = context.extensions["interleaved_thinking_weighted_cycle_state"]
    assert isinstance(stored_state, dict)
    assert stored_state["next_index"] == 1


def test_try_parse_parallel_plan_returns_none_for_thinker_turn_of_special_route() -> (
    None
):
    context = _context()
    context.extensions["interleaved_thinking_weighted_cycle_state"] = {
        "selector": (
            "[weight=1][thinker]opencode-go:opencode-go/glm-5.2?reasoning_effort=high^"
            "[weight=1][handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
            "opencode-go:minimaxai/minimax-m3"
        ),
        "sequence": [
            "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
            "opencode-go:minimaxai/minimax-m3",
            "opencode-go:opencode-go/glm-5.2?reasoning_effort=high",
        ],
        "next_index": 1,
    }
    request = CanonicalChatRequest(
        model=(
            "[thinker]opencode-go:opencode-go/glm-5.2?reasoning_effort=high^"
            "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
            "opencode-go:minimaxai/minimax-m3"
        ),
        messages=[ChatMessage(role="user", content="hello")],
    )

    assert try_parse_parallel_plan(request, context) is None
    stored_state = context.extensions["interleaved_thinking_weighted_cycle_state"]
    assert isinstance(stored_state, dict)
    assert stored_state["next_index"] == 1


def test_special_thinker_executor_non_parallel_plan_does_not_advance_cycle_state() -> (
    None
):
    parser = CompositeSelectorParser()
    plan = parser.parse(
        CompositeRoutingInput(
            selector="[thinker]openai:gpt-4^openai:gpt-4|anthropic:claude-3",
            surface=RoutingSurface.MAIN,
        )
    )
    context = _context()

    selected = _try_select_special_thinker_parallel_executor(
        plan=plan,
        parser=parser,
        context=context,
    )

    assert selected is None
    assert "interleaved_thinking_weighted_cycle_state" not in context.extensions


def test_annotated_parallel_selector_is_composite_model_selector() -> None:
    assert is_composite_selector(
        "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
        "[handicap=5]nvidia:deepseek-ai/deepseek-v4-pro?reasoning_effort=max!"
        "nvidia:stepfun-ai/step-3.7-flash?reasoning_effort=high"
    )


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
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_parallel_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
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
async def test_orchestrator_leg_context_preserves_parent_app_state() -> None:
    orchestrator = ParallelCompletionOrchestrator()
    app_state = object()
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=app_state,
        request_id="req-parallel",
        session_id="session-parallel",
    )
    seen_app_states: list[object | None] = []
    started: list[str] = []

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        assert stream is True
        assert allow_failover is False
        leg_context = context
        assert leg_context is not None
        seen_app_states.append(leg_context.app_state)
        started.append(request.model)
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={"choices": [{"delta": {"content": "win"}}]}
                    )
                ],
            )
        return _streaming_envelope([])

    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_parallel_plan(),
            request=_request(),
            context=context,
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None

    async for _chunk in envelope.content:
        pass

    assert set(started) == {"openai:gpt-4", "anthropic:claude-3"}
    assert seen_app_states
    assert all(item is app_state for item in seen_app_states)


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
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_parallel_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
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
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_parallel_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
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


@pytest.mark.asyncio
async def test_orchestrator_fast_winner_cleans_up_handicap_wait_tasks() -> None:
    plan = CompositeRoutePlan(
        source_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        normalized_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="[handicap=10]openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        handicap_seconds=10.0,
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        handicap_seconds=0.0,
                        uri_params={},
                    )
                ),
            ]
        ),
    )

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={"choices": [{"delta": {"content": "win"}}]}
                    )
                ]
            )
        return _streaming_envelope(
            [ProcessedResponse(content={"choices": [{"delta": {"content": "lose"}}]})]
        )

    before_tasks = asyncio.all_tasks()
    orchestrator = ParallelCompletionOrchestrator()
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=plan,
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None

    chunks = [chunk async for chunk in envelope.content]
    await asyncio.sleep(0)

    assert [chunk.content for chunk in chunks] == [
        {"choices": [{"delta": {"content": "win"}}]}
    ]
    leaked_tasks = [
        task
        for task in asyncio.all_tasks() - before_tasks
        if not task.done() and "Event.wait" in repr(task)
    ]
    assert leaked_tasks == []


@pytest.mark.asyncio
async def test_orchestrator_terminal_error_accelerates_delayed_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.DEBUG,
        logger="src.core.services.parallel_completion_racer",
    )
    plan = CompositeRoutePlan(
        source_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        normalized_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="[handicap=10]openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        handicap_seconds=10.0,
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        handicap_seconds=0.0,
                        uri_params={},
                    )
                ),
            ]
        ),
    )
    started: list[str] = []

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        started.append(request.model)
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={"error": "rate limit"}, metadata={"error": True}
                    )
                ]
            )
        return _streaming_envelope(
            [
                ProcessedResponse(
                    content={"choices": [{"delta": {"content": "fallback"}}]}
                )
            ]
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=plan,
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None

    chunks = await asyncio.wait_for(_collect_stream(envelope.content), timeout=0.5)

    assert started == ["openai:gpt-4", "anthropic:claude-3"]
    assert [chunk.content for chunk in chunks] == [
        {"choices": [{"delta": {"content": "fallback"}}]}
    ]
    assert "Parallel race accelerating delayed legs" in caplog.text
    assert "parallel_race_winner_selected" in caplog.text


async def _collect_stream(
    stream: AsyncIterator[ProcessedResponse],
) -> list[ProcessedResponse]:
    chunks: list[ProcessedResponse] = []
    async for chunk in stream:
        chunks.append(chunk)
    return chunks


def _handicap_plan() -> CompositeRoutePlan:
    return CompositeRoutePlan(
        source_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        normalized_selector="[handicap=10]openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="[handicap=10]openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        handicap_seconds=10.0,
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        handicap_seconds=0.0,
                        uri_params={},
                    )
                ),
            ]
        ),
    )


@pytest.mark.asyncio
async def test_orchestrator_early_winner_skips_delayed_leg_call_completion() -> None:
    dispatched: list[str] = []

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        dispatched.append(request.model)
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={"choices": [{"delta": {"content": "win"}}]}
                    )
                ]
            )
        return _streaming_envelope(
            [ProcessedResponse(content={"choices": [{"delta": {"content": "lose"}}]})]
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_handicap_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None
    chunks = [chunk async for chunk in envelope.content]
    await asyncio.sleep(0)

    assert dispatched == ["openai:gpt-4"]
    assert [chunk.content for chunk in chunks] == [
        {"choices": [{"delta": {"content": "win"}}]}
    ]


@pytest.mark.asyncio
async def test_orchestrator_pending_leg_cancellation_logs_without_upstream_resources(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="src.core.services.parallel_completion_orchestrator",
    )

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        if request.model == "openai:gpt-4":
            return _streaming_envelope(
                [
                    ProcessedResponse(
                        content={"choices": [{"delta": {"content": "win"}}]}
                    )
                ]
            )
        return _streaming_envelope(
            [ProcessedResponse(content={"choices": [{"delta": {"content": "lose"}}]})]
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_handicap_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None
    await _collect_stream(envelope.content)
    await asyncio.sleep(0)

    delayed_leg_id = "parallel-1-anthropic:claude-3"
    cancel_requested = [
        record.message
        for record in caplog.records
        if record.message.startswith("parallel_leg_cancel_requested")
        and delayed_leg_id in record.message
    ]
    cancel_completed = [
        record.message
        for record in caplog.records
        if record.message.startswith("parallel_leg_cancel_completed")
        and delayed_leg_id in record.message
    ]
    assert cancel_requested
    assert cancel_completed
    assert "envelope=False" in cancel_requested[0]
    assert "call_task=False" in cancel_requested[0]
    assert "request_id=req-parallel" in cancel_requested[0]
    assert "session_id=session-parallel" in cancel_requested[0]
    assert "envelope=False" in cancel_completed[0]
    assert "call_task=False" in cancel_completed[0]


@pytest.mark.asyncio
async def test_orchestrator_logs_upstream_dispatch_requested(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="src.core.services.parallel_completion_orchestrator",
    )

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        return _streaming_envelope(
            [ProcessedResponse(content={"choices": [{"delta": {"content": "win"}}]})]
        )

    orchestrator = ParallelCompletionOrchestrator()
    envelope = cast(
        StreamingResponseEnvelope,
        await orchestrator.execute(
            plan=_parallel_plan(),
            request=_request(),
            context=_context(),
            stream=True,
            call_completion=call_completion,
        ),
    )
    assert envelope.content is not None
    await _collect_stream(envelope.content)

    dispatch_logs = [
        record.message
        for record in caplog.records
        if record.message.startswith("parallel_leg_upstream_dispatch_requested")
    ]
    assert len(dispatch_logs) >= 1
    assert any(
        "leg=parallel-0-openai:gpt-4" in message
        and "model=openai:gpt-4" in message
        and "request_id=req-parallel" in message
        and "session_id=session-parallel" in message
        for message in dispatch_logs
    )


@pytest.mark.asyncio
async def test_orchestrator_cancel_during_call_completion_skips_streaming(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.INFO,
        logger="src.core.services.parallel_completion_orchestrator",
    )
    call_entered = asyncio.Event()
    release_call = asyncio.Event()
    leg_runtimes: dict[str, Any] = {}

    async def call_completion(
        request: CanonicalChatRequest,
        *,
        stream: bool,
        allow_failover: bool,
        context: RequestContext | None,
    ) -> StreamingResponseEnvelope:
        del stream, allow_failover, context
        call_entered.set()
        await release_call.wait()
        return _streaming_envelope(
            [
                ProcessedResponse(
                    content={"choices": [{"delta": {"content": "should-not-stream"}}]}
                )
            ]
        )

    orchestrator = ParallelCompletionOrchestrator()
    request = CanonicalChatRequest(
        model="anthropic:claude-3",
        messages=[ChatMessage(role="user", content="hello")],
    )
    leg = orchestrator._build_race_leg(
        leaf=CompositeLeafNode(
            leaf_selector=CompositeLeafSelector(
                raw_selector="anthropic:claude-3",
                normalized_selector="anthropic:claude-3",
                uri_params={},
            )
        ),
        index=0,
        request=request,
        context=_context(),
        call_completion=call_completion,
        leg_runtimes=leg_runtimes,
    )
    runtime = leg_runtimes[leg.leg_id]

    async def _collect_stream_chunks() -> list[Any]:
        chunks: list[Any] = []
        async for chunk in leg.stream_factory():
            chunks.append(chunk)
        return chunks

    stream_task = asyncio.create_task(_collect_stream_chunks())
    await asyncio.wait_for(call_entered.wait(), timeout=1.0)
    assert runtime.call_task is not None
    runtime.cancelled = True
    release_call.set()
    chunks = await asyncio.wait_for(stream_task, timeout=1.0)

    assert chunks == []
    dispatch_cancelled = [
        record.message
        for record in caplog.records
        if record.message.startswith("parallel_leg_upstream_dispatch_cancelled")
        and "anthropic:claude-3" in record.message
    ]
    assert dispatch_cancelled
