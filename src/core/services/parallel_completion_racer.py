"""Parallel completion racing for composite streaming routes."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.core.common.exceptions import RoutingError
from src.core.common.openai_stream_reasoning import openai_dict_has_reasoning_output
from src.core.interfaces.response_processor_interface import ProcessedResponse

__all__ = ["ParallelCompletionRacer", "ParallelRaceLeg"]

logger = logging.getLogger(__name__)


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


def _parse_sse_payload(raw: bytes | str) -> bool | None:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = raw

    has_data_line = False
    payload_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("data:"):
            has_data_line = True
            data = stripped[5:].lstrip()
            if data and data != "[DONE]":
                payload_lines.append(data)

    if not has_data_line:
        return None

    if not payload_lines:
        return False

    try:
        parsed = json.loads("\n".join(payload_lines))
    except json.JSONDecodeError:
        return False

    if isinstance(parsed, dict):
        return _dict_has_meaningful_delta_content(parsed)
    return False


def _dict_has_meaningful_delta_content(chunk: dict[str, Any]) -> bool:
    if openai_dict_has_reasoning_output(chunk):
        return True
    choices = chunk.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        if _delta_field_has_content(delta, "content") or _delta_has_tool_calls(delta):
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
    tasks = {sleep_task, accelerate_task}
    try:
        _done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        pending = {task for task in tasks if not task.done()}
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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
        if data in _KEEPALIVE_BYTE_MARKERS:
            return False
        sse_verdict = _parse_sse_payload(data)
        if sse_verdict is not None:
            return sse_verdict
        return True
    if isinstance(chunk, str):
        if not chunk.strip():
            return False
        if chunk in _KEEPALIVE_STR_MARKERS:
            return False
        sse_verdict = _parse_sse_payload(chunk)
        if sse_verdict is not None:
            return sse_verdict
        return True
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
    model: str | None = None


class ParallelCompletionRacer:
    async def race(  # noqa: C901 - async race orchestration is intentionally centralized.
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
        leg_streaming_started: dict[str, bool] = {leg.leg_id: False for leg in legs}
        handicap_accelerate = asyncio.Event()
        winner_first_chunk_emitted = False
        winner_first_chunk_emitted_event = asyncio.Event()

        def _should_stop() -> bool:
            if race_stopped.is_set():
                return True
            return client_cancelled is not None and client_cancelled.is_set()

        def _mark_race_stopped() -> None:
            race_stopped.set()
            first_token_event.set()

        async def _request_pending_leg_acceleration(
            *,
            reason: str,
            source_leg_id: str,
        ) -> None:
            async with winner_lock:
                if winner_leg_id is not None or _should_stop():
                    return
                if handicap_accelerate.is_set():
                    return
                handicap_accelerate.set()
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Parallel race accelerating delayed legs: source_leg=%s reason=%s",
                    source_leg_id,
                    reason,
                )

        async def _emit(chunk: Any, winner: str | None = None) -> None:
            await queue.put((chunk, winner))

        def _should_defer_winner_cancel(
            leg: ParallelRaceLeg,
            *,
            reason: str,
        ) -> bool:
            return (
                leg.leg_id == winner_leg_id
                and not winner_first_chunk_emitted
                and reason in {"client_cancel", "race_aborted"}
            )

        def _should_cancel_leg_task(leg: ParallelRaceLeg, *, reason: str) -> bool:
            task = leg_tasks.get(leg.leg_id)
            if task is None or task.done() or task is asyncio.current_task():
                return False
            return not _should_defer_winner_cancel(leg, reason=reason)

        async def _request_leg_cancel(leg: ParallelRaceLeg, *, reason: str) -> None:
            if leg.leg_id in cancelled_legs:
                return
            if _should_defer_winner_cancel(leg, reason=reason):
                return
            started = leg_streaming_started.get(leg.leg_id, False)
            if not started:
                not_started_reason: str | None = None
                if reason == "winner_selected":
                    not_started_reason = "winner_already_selected"
                elif reason in {"race_stopped", "client_cancel", "race_aborted"}:
                    not_started_reason = "race_stopped"
                if not_started_reason is not None:
                    logger.info(
                        "parallel_race_leg_not_started reason=%s leg=%s model=%s winner=%s",
                        not_started_reason,
                        leg.leg_id,
                        leg.model,
                        winner_leg_id,
                    )
            task = leg_tasks.get(leg.leg_id)
            logger.info(
                "parallel_race_leg_cancel_requested reason=%s leg=%s model=%s winner=%s started=%s task_done=%s",
                reason,
                leg.leg_id,
                leg.model,
                winner_leg_id,
                started,
                task.done() if task is not None else None,
            )
            try:
                await leg.cancel()
            except Exception:
                logger.warning(
                    "parallel_race_leg_cancel_callback_failed reason=%s leg=%s model=%s winner=%s",
                    reason,
                    leg.leg_id,
                    leg.model,
                    winner_leg_id,
                    exc_info=True,
                )
            else:
                cancelled_legs.add(leg.leg_id)
                logger.info(
                    "parallel_race_leg_cancel_callback_completed reason=%s leg=%s model=%s winner=%s",
                    reason,
                    leg.leg_id,
                    leg.model,
                    winner_leg_id,
                )

        async def _cancel_leg_task(leg: ParallelRaceLeg, *, reason: str) -> None:
            if not _should_cancel_leg_task(leg, reason=reason):
                return
            task = leg_tasks.get(leg.leg_id)
            if task is None or task.done() or task is asyncio.current_task():
                return
            logger.info(
                "parallel_race_leg_task_cancel_requested reason=%s leg=%s model=%s winner=%s",
                reason,
                leg.leg_id,
                leg.model,
                winner_leg_id,
            )
            task.cancel()
            logger.info(
                "parallel_race_leg_task_cancel_completed reason=%s leg=%s model=%s winner=%s",
                reason,
                leg.leg_id,
                leg.model,
                winner_leg_id,
            )

        async def _stop_leg(leg: ParallelRaceLeg, *, reason: str) -> None:
            await _request_leg_cancel(leg, reason=reason)
            await _cancel_leg_task(leg, reason=reason)

        async def _stop_loser_protocols(winner_id: str) -> None:
            losers = [leg for leg in legs if leg.leg_id != winner_id]
            if losers:
                await asyncio.gather(
                    *(
                        _request_leg_cancel(leg, reason="winner_selected")
                        for leg in losers
                    ),
                    return_exceptions=True,
                )

        async def _stop_loser_tasks(winner_id: str) -> None:
            losers = [leg for leg in legs if leg.leg_id != winner_id]
            if losers:
                await asyncio.gather(
                    *(
                        _cancel_leg_task(leg, reason="winner_selected")
                        for leg in losers
                    ),
                    return_exceptions=True,
                )

        async def _stop_all(*, reason: str = "race_stopped") -> None:
            for leg in legs:
                await _stop_leg(leg, reason=reason)

        async def _run_leg(leg: ParallelRaceLeg) -> None:
            nonlocal winner_leg_id, winner_first_chunk_emitted
            ttft_task: asyncio.Task[None] | None = None
            started_streaming = False
            try:
                start_delay = max_handicap - leg.handicap_seconds
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "parallel_race_leg_scheduled leg=%s model=%s handicap_seconds=%.3f start_delay_seconds=%.3f ttft_timeout_seconds=%.3f",
                        leg.leg_id,
                        leg.model,
                        leg.handicap_seconds,
                        start_delay,
                        leg.ttft_timeout_seconds,
                    )
                await _wait_handicap_delay(start_delay, handicap_accelerate)

                if _should_stop():
                    logger.info(
                        "parallel_race_leg_skipped reason=race_stopped leg=%s model=%s winner=%s",
                        leg.leg_id,
                        leg.model,
                        winner_leg_id,
                    )
                    return

                async with winner_lock:
                    if winner_leg_id is not None:
                        logger.info(
                            "parallel_race_leg_skipped reason=winner_already_selected leg=%s model=%s winner=%s",
                            leg.leg_id,
                            leg.model,
                            winner_leg_id,
                        )
                        return

                async def _ttft_watchdog() -> None:
                    await asyncio.sleep(leg.ttft_timeout_seconds)
                    async with winner_lock:
                        if winner_leg_id is None and not _should_stop():
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Parallel race leg TTFT timeout: leg=%s timeout_seconds=%.3f",
                                    leg.leg_id,
                                    leg.ttft_timeout_seconds,
                                )
                            await _stop_leg(leg, reason="ttft_timeout")

                if leg.ttft_timeout_seconds > 0:
                    ttft_task = asyncio.create_task(_ttft_watchdog())

                started_streaming = True
                leg_streaming_started[leg.leg_id] = True
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "parallel_race_leg_started leg=%s model=%s",
                        leg.leg_id,
                        leg.model,
                    )
                stream = leg.stream_factory()
                streaming_winner = False
                async for chunk in stream:
                    if _should_stop():
                        return

                    async with winner_lock:
                        if winner_leg_id is not None and winner_leg_id != leg.leg_id:
                            logger.info(
                                "parallel_race_leg_skipped reason=winner_already_selected leg=%s model=%s winner=%s",
                                leg.leg_id,
                                leg.model,
                                winner_leg_id,
                            )
                            return

                    if isinstance(
                        chunk, ProcessedResponse
                    ) and _is_terminal_error_chunk(chunk):
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Parallel race leg emitted terminal error before winning: leg=%s",
                                leg.leg_id,
                            )
                        await _stop_leg(leg, reason="terminal_error")
                        await _request_pending_leg_acceleration(
                            reason="terminal_error",
                            source_leg_id=leg.leg_id,
                        )
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
                    logger.info(
                        "Parallel race winner selected: parallel_race_winner_selected leg=%s model=%s",
                        leg.leg_id,
                        leg.model,
                    )
                    if ttft_task is not None:
                        ttft_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await ttft_task
                        ttft_task = None
                    await _stop_loser_protocols(leg.leg_id)
                    await _emit(chunk, leg.leg_id)
                    winner_first_chunk_emitted = True
                    winner_first_chunk_emitted_event.set()
                    await _stop_loser_tasks(leg.leg_id)
                    streaming_winner = True

            except asyncio.CancelledError:
                raise
            except RoutingError as exc:
                if logger.isEnabledFor(logging.INFO):
                    logger.info(
                        "Parallel race leg became unavailable before winning: leg=%s reason=%s",
                        leg.leg_id,
                        exc,
                    )
                await _stop_leg(leg, reason="routing_unavailable")
                await _request_pending_leg_acceleration(
                    reason="routing_unavailable",
                    source_leg_id=leg.leg_id,
                )
            except Exception:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Parallel race leg failed before winning: leg=%s",
                        leg.leg_id,
                        exc_info=True,
                    )
                await _stop_leg(leg, reason="exception")
                await _request_pending_leg_acceleration(
                    reason="exception",
                    source_leg_id=leg.leg_id,
                )
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
                if leg.leg_id == winner_leg_id:
                    winner_first_chunk_emitted_event.set()

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
            _mark_race_stopped()
            async with winner_lock:
                wait_for_winner_first_chunk = (
                    winner_leg_id is not None and not winner_first_chunk_emitted
                )
            if wait_for_winner_first_chunk:
                await winner_first_chunk_emitted_event.wait()
            await _stop_all(reason="client_cancel")
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
                _mark_race_stopped()
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
            _mark_race_stopped()

            async def _cleanup() -> None:
                if not finished_normally:
                    if winner_leg_id is not None and not winner_first_chunk_emitted:
                        await winner_first_chunk_emitted_event.wait()
                    await _stop_all(reason="race_aborted")
                background_tasks = [*leg_tasks.values(), *auxiliary_tasks]
                if not orchestrator.done():
                    orchestrator.cancel()
                for task in background_tasks:
                    if not task.done():
                        task.cancel()
                if background_tasks:
                    await asyncio.gather(*background_tasks, return_exceptions=True)
                await asyncio.gather(orchestrator, return_exceptions=True)

            await asyncio.shield(_cleanup())
