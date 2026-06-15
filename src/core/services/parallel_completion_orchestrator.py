"""Orchestrate parallel composite streaming completions."""

from __future__ import annotations

import asyncio
import contextlib
import copy
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
from src.core.domain.responses import StreamingResponseEnvelope
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
    ) -> StreamingResponseEnvelope:
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

        return StreamingResponseEnvelope(
            content=_race_stream(),
            cancel_callback=_cancel_all_legs,
        )

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
                update={"model": leaf_selector.normalized_selector},
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
