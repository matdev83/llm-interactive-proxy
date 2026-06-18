"""Orchestrate parallel composite streaming completions."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic.types import JsonValue

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
    CompositeRoutingInput,
    CompositeWeightedGroupNode,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.composite_routing_state import (
    INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY,
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

logger = logging.getLogger(__name__)

CallCompletionFn = Callable[
    ...,
    Awaitable[StreamingResponseEnvelope],
]

ParallelCompletionResult = ResponseEnvelope | StreamingResponseEnvelope


@dataclass(slots=True)
class _LegRuntime:
    leg_id: str
    model: str
    request_id: str | None = None
    session_id: str | None = None
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
    special_parallel_plan = _try_select_special_thinker_parallel_executor(
        plan=plan,
        parser=parser,
        context=context,
    )
    if special_parallel_plan is not None:
        return special_parallel_plan
    return None


def _try_select_special_thinker_parallel_executor(
    *,
    plan: CompositeRoutePlan,
    parser: CompositeSelectorParser,
    context: RequestContext | None,
) -> CompositeRoutePlan | None:
    root = plan.root_node
    if not isinstance(root, CompositeWeightedGroupNode):
        return None
    if len(root.children) != 2:
        return None
    embedded_children = [
        child for child in root.children if child.leaf_selector.embedded_selector
    ]
    thinker_children = [
        child for child in root.children if child.leaf_selector.thinker_annotation
    ]
    if len(embedded_children) != 1 or len(thinker_children) != 1:
        return None

    sequence = [embedded_children[0], thinker_children[0]]
    next_index = 0
    cycle_state = (
        context.extensions.get(INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY)
        if context is not None
        else None
    )
    sequence_selectors = [child.leaf_selector.normalized_selector for child in sequence]
    if isinstance(cycle_state, dict):
        stored_selector = cycle_state.get("selector")
        stored_sequence = cycle_state.get("sequence")
        stored_next_index = cycle_state.get("next_index")
        if (
            stored_selector == plan.normalized_selector
            and stored_sequence == sequence_selectors
            and isinstance(stored_next_index, int)
            and stored_next_index >= 0
        ):
            next_index = stored_next_index % len(sequence)

    selected = sequence[next_index]
    if selected.leaf_selector.thinker_annotation:
        return None

    embedded_selector = selected.leaf_selector.embedded_selector
    if not embedded_selector:
        return None
    embedded_plan = parser.parse(
        CompositeRoutingInput(
            selector=embedded_selector,
            surface=resolve_composite_routing_surface(context),
        )
    )
    if not is_parallel_composite_plan(embedded_plan):
        return None

    persisted_state = {
        "selector": plan.normalized_selector,
        "sequence": sequence_selectors,
        "next_index": (next_index + 1) % len(sequence),
    }
    if context is not None:
        context.extensions[INTERLEAVED_THINKING_WEIGHTED_CYCLE_STATE_KEY] = cast(
            JsonValue, persisted_state
        )
    return embedded_plan


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
        correlation = self._leg_correlation_fields(context)
        runtime = _LegRuntime(
            leg_id=leg_id,
            model=leaf_selector.normalized_selector,
            request_id=correlation.get("request_id"),
            session_id=correlation.get("session_id"),
        )
        leg_runtimes[leg_id] = runtime

        async def _stream_factory() -> AsyncIterator[Any]:
            if runtime.cancelled:
                logger.info(
                    "parallel_leg_upstream_dispatch_skipped leg=%s model=%s request_id=%s session_id=%s",
                    runtime.leg_id,
                    runtime.model,
                    runtime.request_id,
                    runtime.session_id,
                )
                return

            logger.info(
                "parallel_leg_upstream_dispatch_requested leg=%s model=%s request_id=%s session_id=%s",
                runtime.leg_id,
                runtime.model,
                runtime.request_id,
                runtime.session_id,
            )
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
            if runtime.cancelled:
                logger.info(
                    "parallel_leg_upstream_dispatch_cancelled leg=%s model=%s request_id=%s session_id=%s",
                    runtime.leg_id,
                    runtime.model,
                    runtime.request_id,
                    runtime.session_id,
                )
                return
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
            model=leaf_selector.normalized_selector,
        )

    @staticmethod
    def _leg_correlation_fields(context: RequestContext | None) -> dict[str, str]:
        fields: dict[str, str] = {}
        if context is None:
            return fields
        if context.request_id:
            fields["request_id"] = context.request_id
        if context.session_id:
            fields["session_id"] = context.session_id
        return fields

    @staticmethod
    def _clone_context_for_leg(
        context: RequestContext | None,
    ) -> RequestContext | None:
        if context is None:
            return None
        leg_context = context.with_processing_context()
        leg_context.processing_context = (
            copy.deepcopy(context.processing_context)
            if context.processing_context
            else None
        )
        leg_context.extensions[PARALLEL_COMPLETION_ACTIVE_KEY] = True
        return leg_context

    async def _cancel_leg_runtime(self, runtime: _LegRuntime) -> None:
        if runtime.cancelled:
            return

        envelope_exists = runtime.envelope is not None
        call_task_exists = runtime.call_task is not None
        logger.info(
            "parallel_leg_cancel_requested leg=%s model=%s envelope=%s call_task=%s request_id=%s session_id=%s",
            runtime.leg_id,
            runtime.model,
            envelope_exists,
            call_task_exists,
            runtime.request_id,
            runtime.session_id,
        )
        runtime.cancelled = True

        envelope = runtime.envelope
        if envelope is not None and envelope.cancel_callback is not None:
            logger.info(
                "parallel_leg_envelope_cancel_requested leg=%s model=%s request_id=%s session_id=%s",
                runtime.leg_id,
                runtime.model,
                runtime.request_id,
                runtime.session_id,
            )
            await envelope.cancel_callback()
            logger.info(
                "parallel_leg_envelope_cancel_completed leg=%s model=%s request_id=%s session_id=%s",
                runtime.leg_id,
                runtime.model,
                runtime.request_id,
                runtime.session_id,
            )

        call_task = runtime.call_task
        if call_task is not None and not call_task.done():
            logger.info(
                "parallel_leg_call_task_cancel_requested leg=%s model=%s request_id=%s session_id=%s",
                runtime.leg_id,
                runtime.model,
                runtime.request_id,
                runtime.session_id,
            )
            call_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await call_task
            logger.info(
                "parallel_leg_call_task_cancel_completed leg=%s model=%s request_id=%s session_id=%s",
                runtime.leg_id,
                runtime.model,
                runtime.request_id,
                runtime.session_id,
            )

        logger.info(
            "parallel_leg_cancel_completed leg=%s model=%s envelope=%s call_task=%s request_id=%s session_id=%s",
            runtime.leg_id,
            runtime.model,
            envelope_exists,
            call_task_exists,
            runtime.request_id,
            runtime.session_id,
        )


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
