"""Parallel completion racing for composite streaming routes."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.core.interfaces.response_processor_interface import ProcessedResponse

__all__ = ["ParallelCompletionRacer", "ParallelRaceLeg"]


_KEEPALIVE_BYTE_MARKERS = (
    b": keep-alive\n\n",
    b": keepalive\n\n",
)
_KEEPALIVE_STR_MARKERS = (
    ": keep-alive\n\n",
    ": keepalive\n\n",
)


def _delta_field_has_content(delta: dict[str, Any], field: str) -> bool:
    value = delta.get(field)
    return isinstance(value, str) and bool(value.strip())


def _delta_has_tool_calls(delta: dict[str, Any]) -> bool:
    tool_calls = delta.get("tool_calls")
    return isinstance(tool_calls, list) and len(tool_calls) > 0


def _dict_has_meaningful_delta_content(chunk: dict[str, Any]) -> bool:
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        if (
            _delta_field_has_content(delta, "content")
            or _delta_field_has_content(delta, "reasoning_content")
            or _delta_has_tool_calls(delta)
        ):
            return True
    return False


def _is_terminal_error_chunk(chunk: ProcessedResponse) -> bool:
    metadata = chunk.metadata or {}
    if metadata.get("error"):
        return True
    if metadata.get("finish_reason") == "error":
        return True
    content = chunk.content
    return isinstance(content, dict) and bool(content.get("error"))


async def _wait_handicap_delay(
    delay: float, handicap_accelerate: asyncio.Event
) -> None:
    if delay <= 0:
        return
    sleep_task = asyncio.create_task(asyncio.sleep(delay))
    accelerate_task = asyncio.create_task(handicap_accelerate.wait())
    _done, pending = await asyncio.wait(
        {sleep_task, accelerate_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _maybe_accelerate_pending_legs(
    leg: ParallelRaceLeg,
    started: bool,
    *,
    winner_leg_id: str | None,
    winner_lock: asyncio.Lock,
    handicap_accelerate: asyncio.Event,
    should_stop: Callable[[], bool],
) -> None:
    if leg.handicap_seconds <= 0 or not started:
        return
    async with winner_lock:
        if winner_leg_id is None and not should_stop():
            handicap_accelerate.set()


def _is_meaningful_token(chunk: Any) -> bool:
    if chunk is None:
        return False
    if isinstance(chunk, ProcessedResponse):
        if chunk.metadata.get("_keepalive"):
            return False
        if _is_terminal_error_chunk(chunk):
            return False
        return _is_meaningful_token(chunk.content)
    if isinstance(chunk, bytes | bytearray):
        data = bytes(chunk)
        if not data.strip():
            return False
        return data not in _KEEPALIVE_BYTE_MARKERS
    if isinstance(chunk, str):
        if not chunk.strip():
            return False
        return chunk not in _KEEPALIVE_STR_MARKERS
    if isinstance(chunk, dict):
        if chunk.get("_keepalive"):
            return False
        return _dict_has_meaningful_delta_content(chunk)
    return bool(chunk)


@dataclass(frozen=True, slots=True)
class ParallelRaceLeg:
    leg_id: str
    stream_factory: Callable[[], AsyncIterator[Any]]
    cancel: Callable[[], Awaitable[None]]
    handicap_seconds: float = 0.0
    ttft_timeout_seconds: float = 0.0


class ParallelCompletionRacer:
    async def race(
        self,
        legs: list[ParallelRaceLeg],
        *,
        client_cancelled: asyncio.Event | None = None,
        keepalive_factory: Callable[[], Any] | None = None,
        keepalive_interval_seconds: float = 5.0,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        if not legs:
            return

        queue: asyncio.Queue[tuple[Any, str | None] | None] = asyncio.Queue()
        winner_lock = asyncio.Lock()
        winner_leg_id: str | None = None
        first_token_event = asyncio.Event()
        race_stopped = asyncio.Event()
        max_handicap = max((leg.handicap_seconds for leg in legs), default=0.0)
        leg_tasks: dict[str, asyncio.Task[None]] = {}
        auxiliary_tasks: list[asyncio.Task[None]] = []
        cancelled_legs: set[str] = set()
        handicap_accelerate = asyncio.Event()

        def _should_stop() -> bool:
            if race_stopped.is_set():
                return True
            return client_cancelled is not None and client_cancelled.is_set()

        async def _emit(chunk: Any, winner: str | None = None) -> None:
            await queue.put((chunk, winner))

        async def _stop_leg(leg: ParallelRaceLeg) -> None:
            task = leg_tasks.get(leg.leg_id)
            current = asyncio.current_task()
            if leg.leg_id not in cancelled_legs:
                cancelled_legs.add(leg.leg_id)
                await leg.cancel()
            if task is not None and not task.done() and task is not current:
                task.cancel()

        async def _stop_losers(winner_id: str) -> None:
            for leg in legs:
                if leg.leg_id != winner_id:
                    await _stop_leg(leg)

        async def _stop_all() -> None:
            for leg in legs:
                await _stop_leg(leg)

        async def _run_leg(leg: ParallelRaceLeg) -> None:
            nonlocal winner_leg_id
            ttft_task: asyncio.Task[None] | None = None
            started_streaming = False
            try:
                start_delay = max_handicap - leg.handicap_seconds
                await _wait_handicap_delay(start_delay, handicap_accelerate)

                if _should_stop():
                    return

                async with winner_lock:
                    if winner_leg_id is not None:
                        return

                async def _ttft_watchdog() -> None:
                    await asyncio.sleep(leg.ttft_timeout_seconds)
                    async with winner_lock:
                        if winner_leg_id is None and not _should_stop():
                            await _stop_leg(leg)

                if leg.ttft_timeout_seconds > 0:
                    ttft_task = asyncio.create_task(_ttft_watchdog())

                started_streaming = True
                stream = leg.stream_factory()
                streaming_winner = False
                async for chunk in stream:
                    if _should_stop():
                        return

                    async with winner_lock:
                        if winner_leg_id is not None and winner_leg_id != leg.leg_id:
                            return

                    if streaming_winner:
                        await _emit(chunk)
                        continue

                    if not _is_meaningful_token(chunk):
                        continue

                    claimed_winner = False
                    async with winner_lock:
                        if winner_leg_id is None and not _should_stop():
                            winner_leg_id = leg.leg_id
                            claimed_winner = True

                    if not claimed_winner:
                        continue

                    first_token_event.set()
                    if ttft_task is not None:
                        ttft_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await ttft_task
                        ttft_task = None
                    await _stop_losers(leg.leg_id)
                    await _emit(chunk, leg.leg_id)
                    streaming_winner = True

            except asyncio.CancelledError:
                raise
            finally:
                if ttft_task is not None:
                    ttft_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await ttft_task
                await _maybe_accelerate_pending_legs(
                    leg,
                    started_streaming,
                    winner_leg_id=winner_leg_id,
                    winner_lock=winner_lock,
                    handicap_accelerate=handicap_accelerate,
                    should_stop=_should_stop,
                )

        async def _keepalive_loop() -> None:
            while not _should_stop() and not first_token_event.is_set():
                await asyncio.sleep(keepalive_interval_seconds)
                if _should_stop() or first_token_event.is_set():
                    break
                if keepalive_factory is not None:
                    await _emit(keepalive_factory())

        async def _client_cancel_watcher() -> None:
            if client_cancelled is None:
                return
            await client_cancelled.wait()
            race_stopped.set()
            first_token_event.set()
            await _stop_all()
            await queue.put(None)

        async def _orchestrate() -> None:
            for leg in legs:
                task = asyncio.create_task(_run_leg(leg))
                leg_tasks[leg.leg_id] = task

            if keepalive_factory is not None:
                auxiliary_tasks.append(asyncio.create_task(_keepalive_loop()))

            if client_cancelled is not None:
                auxiliary_tasks.append(asyncio.create_task(_client_cancel_watcher()))

            try:
                await asyncio.gather(*leg_tasks.values(), return_exceptions=True)
            finally:
                race_stopped.set()
                first_token_event.set()
                for task in auxiliary_tasks:
                    if not task.done():
                        task.cancel()
                if auxiliary_tasks:
                    await asyncio.gather(*auxiliary_tasks, return_exceptions=True)
                await queue.put(None)

        orchestrator = asyncio.create_task(_orchestrate())

        finished_normally = False
        try:
            while True:
                item = await queue.get()
                if item is None:
                    finished_normally = True
                    break
                yield item
        finally:
            race_stopped.set()
            first_token_event.set()
            if not finished_normally:
                await _stop_all()
            if not orchestrator.done():
                orchestrator.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await orchestrator
