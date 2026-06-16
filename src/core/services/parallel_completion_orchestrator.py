"""Orchestrate parallel composite streaming completions."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, cast

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
    CompositeRoutingInput,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.composite_routing_state import (
    PARALLEL_COMPLETION_ACTIVE_KEY,
    contains_top_level_operator,
    resolve_composite_routing_surface,
)
from src.core.services.composite_selector_parser import CompositeSelectorParser
from src.core.services.parallel_completion_racer import (
    ParallelCompletionRacer,
    ParallelRaceLeg,
)
from src.core.services.parallel_routing_policy import (
    ensure_parallel_streaming_supported,
    is_parallel_composite_plan,
)

__all__ = [
    "CallCompletionFn",
    "ParallelCompletionOrchestrator",
    "try_parse_parallel_plan",
]

CallCompletionFn = Callable[
    ...,
    Awaitable[StreamingResponseEnvelope],
]

ParallelCompletionResult = ResponseEnvelope | StreamingResponseEnvelope


@dataclass(slots=True)
class _LegRuntime:
    leg_id: str
    envelope: StreamingResponseEnvelope | None = None
    stream: AsyncIterator[Any] | None = None
    call_task: asyncio.Task[StreamingResponseEnvelope] | None = None
    cancelled: bool = False
    cancel_order: list[str] = field(default_factory=list)


def try_parse_parallel_plan(
    request: CanonicalChatRequest,
    context: RequestContext | None,
) -> CompositeRoutePlan | None:
    model = request.model.strip()
    if not model or not contains_top_level_operator(model, "!"):
        return None

    parser = CompositeSelectorParser()
    plan = parser.parse(
        CompositeRoutingInput(
            selector=model,
            surface=resolve_composite_routing_surface(context),
        )
    )
    if is_parallel_composite_plan(plan):
        return plan
    return None


class ParallelCompletionOrchestrator:
    def __init__(self, racer: ParallelCompletionRacer | None = None) -> None:
        self._racer = racer or ParallelCompletionRacer()

    async def execute(
        self,
        *,
        plan: CompositeRoutePlan,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        stream: bool,
        call_completion: CallCompletionFn,
    ) -> ParallelCompletionResult:
        ensure_parallel_streaming_supported(plan=plan, stream=stream)
        root = plan.root_node
        if not isinstance(root, CompositeParallelGroupNode):
            raise ValueError("parallel orchestration requires a parallel group root")

        client_cancelled = asyncio.Event()
        leg_runtimes: dict[str, _LegRuntime] = {}
        legs = [
            self._build_race_leg(
                leaf=leaf,
                index=index,
                request=request,
                context=context,
                call_completion=call_completion,
                leg_runtimes=leg_runtimes,
            )
            for index, leaf in enumerate(root.children)
        ]

        async def _race_stream() -> AsyncIterator[ProcessedResponse]:
            async for chunk, _winner_id in self._racer.race(
                legs,
                client_cancelled=client_cancelled,
                keepalive_factory=_keepalive_factory,
            ):
                if isinstance(chunk, ProcessedResponse):
                    yield chunk
                    continue
                yield ProcessedResponse(content=chunk)

        async def _cancel_all_legs() -> None:
            client_cancelled.set()
            await asyncio.gather(
                *(
                    self._cancel_leg_runtime(runtime)
                    for runtime in leg_runtimes.values()
                    if not runtime.cancelled
                ),
                return_exceptions=True,
            )

        streaming_envelope = StreamingResponseEnvelope(
            content=_race_stream(),
            cancel_callback=_cancel_all_legs,
        )
        if stream:
            return streaming_envelope
        return await _collect_streaming_envelope_to_response(streaming_envelope)

    def _build_race_leg(
        self,
        *,
        leaf: CompositeLeafNode,
        index: int,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        call_completion: CallCompletionFn,
        leg_runtimes: dict[str, _LegRuntime],
    ) -> ParallelRaceLeg:
        leaf_selector = leaf.leaf_selector
        leg_id = f"parallel-{index}-{leaf_selector.normalized_selector}"
        runtime = _LegRuntime(leg_id=leg_id)
        leg_runtimes[leg_id] = runtime

        async def _stream_factory() -> AsyncIterator[Any]:
            leg_request = request.model_copy(
                update={"model": leaf_selector.normalized_selector, "stream": True},
                deep=True,
            )
            leg_context = self._clone_context_for_leg(context)
            completion_coro = call_completion(
                leg_request,
                stream=True,
                allow_failover=False,
                context=leg_context,
            )
            runtime.call_task = asyncio.create_task(
                cast(Coroutine[Any, Any, StreamingResponseEnvelope], completion_coro)
            )
            envelope = await runtime.call_task
            runtime.envelope = envelope
            if envelope.content is None:
                return
            runtime.stream = envelope.content
            async for chunk in envelope.content:
                yield chunk

        async def _cancel() -> None:
            await self._cancel_leg_runtime(runtime)

        return ParallelRaceLeg(
            leg_id=leg_id,
            stream_factory=_stream_factory,
            cancel=_cancel,
            handicap_seconds=leaf_selector.handicap_seconds,
            ttft_timeout_seconds=leaf_selector.ttft_timeout_seconds,
        )

    @staticmethod
    def _clone_context_for_leg(
        context: RequestContext | None,
    ) -> RequestContext | None:
        if context is None:
            return None
        extensions = copy.deepcopy(context.extensions) if context.extensions else {}
        extensions[PARALLEL_COMPLETION_ACTIVE_KEY] = True
        return RequestContext(
            headers=context.headers,
            cookies=context.cookies,
            state=context.state,
            app_state=None,
            client_host=context.client_host,
            session_id=context.session_id,
            request_id=context.request_id,
            agent=context.agent,
            original_request=context.original_request,
            processing_context=(
                copy.deepcopy(context.processing_context)
                if context.processing_context
                else None
            ),
            domain_request=context.domain_request,
            raw_body=context.raw_body,
            backend=context.backend,
            effective_model=context.effective_model,
            requested_model=context.requested_model,
            extensions=extensions,
            b2bua_identity=(
                copy.deepcopy(context.b2bua_identity)
                if context.b2bua_identity
                else None
            ),
            original_domain_request=context.original_domain_request,
        )

    async def _cancel_leg_runtime(self, runtime: _LegRuntime) -> None:
        if runtime.cancelled:
            return
        runtime.cancelled = True

        envelope = runtime.envelope
        if envelope is not None and envelope.cancel_callback is not None:
            await envelope.cancel_callback()

        call_task = runtime.call_task
        if call_task is not None and not call_task.done():
            call_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await call_task


def _keepalive_factory() -> ProcessedResponse:
    return ProcessedResponse(
        content=": keep-alive\n\n",
        metadata={"_keepalive": True},
    )


async def _collect_streaming_envelope_to_response(
    envelope: StreamingResponseEnvelope,
) -> ResponseEnvelope:
    content_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: dict[int, dict[str, Any]] = {}
    response_id: str | None = None
    response_model: str | None = None
    created: int | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    if envelope.content is not None:
        async for item in envelope.content:
            raw = _coerce_stream_chunk_to_dict(item.content)
            if raw is None:
                continue
            raw_id = raw.get("id")
            if response_id is None and isinstance(raw_id, str):
                response_id = raw_id
            raw_model = raw.get("model")
            if response_model is None and isinstance(raw_model, str):
                response_model = raw_model
            raw_created = raw.get("created")
            if created is None and isinstance(raw_created, int):
                created = raw_created
            if isinstance(raw.get("usage"), dict):
                usage = cast(dict[str, Any], raw["usage"])

            choices = raw.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            first_choice = choices[0]
            if not isinstance(first_choice, dict):
                continue
            raw_finish_reason = first_choice.get("finish_reason")
            if isinstance(raw_finish_reason, str):
                finish_reason = raw_finish_reason
            delta = first_choice.get("delta")
            if not isinstance(delta, dict):
                continue
            _append_text_delta(delta, key="content", parts=content_parts)
            _append_text_delta(delta, key="reasoning_content", parts=reasoning_parts)
            _append_text_delta(delta, key="reasoning", parts=reasoning_parts)
            _append_text_delta(delta, key="thinking", parts=reasoning_parts)
            _merge_tool_call_deltas(tool_calls, delta.get("tool_calls"))

    if envelope.cancel_callback is not None:
        await envelope.cancel_callback()

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(content_parts),
    }
    reasoning = "".join(reasoning_parts)
    if reasoning:
        message["reasoning_content"] = reasoning
        message["reasoning"] = reasoning
        message["thinking"] = reasoning
    if tool_calls:
        message["tool_calls"] = [
            tool_calls[index] for index in sorted(tool_calls.keys())
        ]

    response_content: dict[str, Any] = {
        "id": response_id or f"chatcmpl-parallel-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": response_model or "parallel",
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason or "stop",
            }
        ],
    }
    if usage is not None:
        response_content["usage"] = usage
    return ResponseEnvelope(
        content=response_content,
        metadata={"_parallel_completion_aggregated": True},
    )


def _append_text_delta(delta: dict[str, Any], *, key: str, parts: list[str]) -> None:
    value = delta.get(key)
    if isinstance(value, str) and value:
        parts.append(value)


def _merge_tool_call_deltas(
    tool_calls: dict[int, dict[str, Any]],
    raw_tool_calls: Any,
) -> None:
    if not isinstance(raw_tool_calls, list):
        return
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            continue
        index_value = raw_call.get("index")
        index = index_value if isinstance(index_value, int) else len(tool_calls)
        current = tool_calls.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if isinstance(raw_call.get("id"), str):
            current["id"] = raw_call["id"]
        if isinstance(raw_call.get("type"), str):
            current["type"] = raw_call["type"]
        raw_function = raw_call.get("function")
        if not isinstance(raw_function, dict):
            continue
        function = cast(dict[str, Any], current.setdefault("function", {}))
        if isinstance(raw_function.get("name"), str):
            function["name"] = raw_function["name"]
        if isinstance(raw_function.get("arguments"), str):
            function["arguments"] = (
                str(function.get("arguments", "")) + raw_function["arguments"]
            )


def _coerce_stream_chunk_to_dict(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        text = raw
    else:
        return None

    payload_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data:"):
            data = stripped[5:].lstrip()
            if data and data != "[DONE]":
                payload_lines.append(data)
    if not payload_lines:
        return None
    try:
        parsed = json.loads("\n".join(payload_lines))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
