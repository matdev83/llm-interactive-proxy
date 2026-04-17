"""Background scheduler that triggers scheduled provider warm-up requests."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

from pydantic.types import JsonValue

from src.core.common.exceptions import BackendError, LLMProxyError, RoutingError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.usage_window_warmup_config import (
    UsageWindowWarmupConfig,
    UsageWindowWarmupEntryConfig,
)
from src.core.domain.model_utils import parse_model_backend
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.backend_completion_flow_interface import IBackendCompletionFlow
from src.core.interfaces.warmup_target_resolver_interface import IWarmupTargetResolver

logger = logging.getLogger(__name__)


class UsageWindowWarmupService:
    """Runs scheduled warm-up calls to shape sliding provider usage windows."""

    def __init__(
        self,
        completion_flow: IBackendCompletionFlow,
        config: UsageWindowWarmupConfig,
        *,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_provider: Callable[[], datetime] | None = None,
        random_delay_func: Callable[[], float] | None = None,
        random_number_func: Callable[[int, int], int] | None = None,
        create_task_func: Callable[..., Any] | None = None,
        target_resolver: IWarmupTargetResolver | None = None,
    ) -> None:
        self._completion_flow = completion_flow
        self._config = config
        self._sleep = sleep_func
        self._now_provider = now_provider or datetime.now
        self._random_delay_func = random_delay_func or (
            lambda: random.uniform(5.0, 35.0)
        )
        self._random_number_func = random_number_func or random.randint
        self._create_task = create_task_func or asyncio.create_task
        self._target_resolver = target_resolver
        self._entry_tasks: list[Any] = []
        self._active_execution_tasks: set[asyncio.Task[Any]] = set()
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            logger.warning("Usage window warm-up scheduler already running")
            return
        if not self._config.enabled:
            logger.info("Usage window warm-up scheduler disabled by configuration")
            return
        if not self._config.entries:
            logger.info(
                "Usage window warm-up scheduler enabled but no entries configured"
            )
            return

        self._running = True
        self._entry_tasks = []
        for entry in self._config.entries:
            task = self._create_task(
                self._run_entry_loop(entry),
                name=f"usage_window_warmup:{entry.model}:{entry.time}",
            )
            self._entry_tasks.append(task)
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Scheduled usage window warm-up for '%s' at %s",
                    entry.model,
                    entry.time,
                )

        await asyncio.sleep(0)
        logger.info(
            "Usage window warm-up scheduler started with %d entries",
            len(self._config.entries),
        )

    async def stop(self) -> None:
        if not self._running:
            return

        self._running = False
        for task in list(self._entry_tasks):
            cancel = getattr(task, "cancel", None)
            if callable(cancel):
                cancel()
            if isinstance(task, asyncio.Task):
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._entry_tasks = []

        for task in list(self._active_execution_tasks):
            task.cancel()
        if self._active_execution_tasks:
            await asyncio.gather(*self._active_execution_tasks, return_exceptions=True)
        self._active_execution_tasks.clear()
        logger.info("Usage window warm-up scheduler stopped")

    async def _run_entry_loop(self, entry: UsageWindowWarmupEntryConfig) -> None:
        while self._running:
            try:
                now = self._now_provider()
                delay = self._compute_delay_until_next_run(entry, now)
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Usage window warm-up for '%s' will run in %.3f seconds",
                        entry.model,
                        delay,
                    )
                await self._sleep(delay)
                if not self._running:
                    break
                task = self._create_task(
                    self._execute_entry(entry),
                    name=f"usage_window_warmup_execute:{entry.model}:{entry.time}",
                )
                if isinstance(task, asyncio.Task):
                    self._active_execution_tasks.add(task)
                    task.add_done_callback(self._active_execution_tasks.discard)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "Unexpected error in usage window warm-up loop for '%s': %s",
                    entry.model,
                    exc,
                    exc_info=True,
                )
                await self._sleep(60.0)

    def _compute_delay_until_next_run(
        self, entry: UsageWindowWarmupEntryConfig, now: datetime
    ) -> float:
        hour_str, minute_str = entry.time.split(":", 1)
        target = now.replace(
            hour=int(hour_str),
            minute=int(minute_str),
            second=0,
            microsecond=0,
        )
        if target < now:
            target = target + timedelta(days=1)
        if not entry.execute_on_weekend:
            while target.weekday() >= 5:
                target = target + timedelta(days=1)
        return max(0.0, (target - now).total_seconds())

    async def _execute_entry(self, entry: UsageWindowWarmupEntryConfig) -> None:
        jitter_seconds = float(self._random_delay_func())
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Usage window warm-up for '%s' waiting %.3f second jitter",
                entry.model,
                jitter_seconds,
            )
        await self._sleep(jitter_seconds)

        target_account_ids = await self._resolve_target_account_ids(entry.model)
        if target_account_ids:
            if logger.isEnabledFor(logging.INFO):
                logger.info(
                    "Usage window warm-up fan-out for '%s': %d account targets %s",
                    entry.model,
                    len(target_account_ids),
                    target_account_ids,
                )
            execution_tasks = [
                self._execute_single_target(entry, account_id)
                for account_id in target_account_ids
            ]
            await asyncio.gather(*execution_tasks)
            return

        await self._execute_single_target(entry, target_account_id=None)

    async def _resolve_target_account_ids(self, model: str) -> list[str]:
        if self._target_resolver is None:
            return []
        try:
            parsed = parse_model_backend(model)
            if parsed.backend_type not in ("openai-codex", "openai-codex-v2"):
                return []
            return await self._target_resolver.resolve_target_accounts(
                parsed.backend_type
            )
        except Exception as exc:
            logger.warning(
                "Usage window warm-up target resolution failed for '%s': %s",
                model,
                exc,
                exc_info=True,
            )
            return []

    async def _execute_single_target(
        self,
        entry: UsageWindowWarmupEntryConfig,
        target_account_id: str | None,
    ) -> None:
        target_label = target_account_id or "default"

        for attempt in range(1, 3):
            try:
                request = self._build_request(entry.model, target_account_id)
                context = self._build_request_context(entry.model, target_account_id)
                result = await self._completion_flow.call_completion(
                    request,
                    stream=False,
                    allow_failover=True,
                    context=context,
                )
                if self._is_valid_response(result):
                    logger.info(
                        "Usage window warm-up succeeded for '%s' target '%s' on attempt %d",
                        entry.model,
                        target_label,
                        attempt,
                    )
                    return

                raise BackendError(
                    message="Usage window warm-up received an invalid response",
                    details={
                        "model": entry.model,
                        "attempt": attempt,
                        "warmup_target_account_id": target_account_id,
                    },
                )
            except asyncio.CancelledError:
                raise
            except (LLMProxyError, ConnectionError, OSError, TimeoutError) as exc:
                # Expected warm-up failures (rate limits, routing, transport): log the
                # message only — full tracebacks here are noisy in production logs.
                retryable = self._is_retryable_error(exc)
                logger.warning(
                    "Usage window warm-up attempt %d/2 failed for '%s' target '%s': %s",
                    attempt,
                    entry.model,
                    target_label,
                    exc,
                )
                if not retryable or attempt >= 2:
                    logger.error(
                        "Usage window warm-up exhausted attempts for '%s' target '%s'",
                        entry.model,
                        target_label,
                    )
                    return
            except Exception as exc:
                retryable = self._is_retryable_error(exc)
                logger.error(
                    "Unexpected error during usage window warm-up attempt %d/2 "
                    "for '%s' target '%s': %s",
                    attempt,
                    entry.model,
                    target_label,
                    exc,
                    exc_info=True,
                )
                if not retryable or attempt >= 2:
                    logger.error(
                        "Usage window warm-up exhausted attempts for '%s' target '%s'",
                        entry.model,
                        target_label,
                    )
                    return

    def _build_request(self, model: str, target_account_id: str | None) -> ChatRequest:
        a = self._random_number_func(100, 9999)
        b = self._random_number_func(100, 9999)
        c = self._random_number_func(100, 9999)
        extra_body = (
            {"openai_codex_managed_account_id": target_account_id}
            if target_account_id
            else None
        )
        return ChatRequest(
            model=model,
            messages=[
                ChatMessage(
                    role="user",
                    content=f"Hi, how much is it {a} times {b} plus {c}",
                )
            ],
            extra_body=extra_body,
        )

    def _build_request_context(
        self, model: str, target_account_id: str | None
    ) -> RequestContext:
        suffix = uuid4().hex
        extensions: dict[str, JsonValue] = {
            "usage_window_warmup": cast(JsonValue, True),
        }
        if target_account_id:
            account_id_value = cast(JsonValue, target_account_id)
            extensions["warmup_target_account_id"] = account_id_value
            extensions["openai_codex_managed_account_id"] = account_id_value
        return RequestContext(
            headers={},
            cookies={},
            state=SimpleNamespace(),
            app_state=SimpleNamespace(),
            session_id=f"usage-window-warmup:{model}:{suffix}",
            request_id=f"usage-window-warmup:{suffix}",
            agent="usage-window-warmup",
            requested_model=model,
            effective_model=model,
            extensions=extensions,
        )

    @staticmethod
    def _is_valid_response(
        result: ResponseEnvelope | StreamingResponseEnvelope,
    ) -> bool:
        if getattr(result, "status_code", 500) >= 400:
            return False
        return getattr(result, "content", None) is not None

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        """Return True only for explicit temporary/transient conditions.

        Permanent failures (invalid responses, routing errors, 4xx client errors)
        are not retried. Only transport timeouts, connection issues, 5xx server
        errors, and rate limits (429) warrant a single retry attempt.
        """
        # Routing/configuration errors are permanent - no retry
        if isinstance(exc, RoutingError):
            return False

        # Low-level transport errors are temporary and retryable
        if isinstance(
            exc, TimeoutError | ConnectionError | OSError | asyncio.TimeoutError
        ):
            return True

        # Check for explicit retryable flag on LLMProxyError subclasses first
        # This takes precedence over status code heuristics
        if isinstance(exc, LLMProxyError):
            details = getattr(exc, "details", None)
            retryable_flag = (
                details.get("retryable") if isinstance(details, dict) else None
            )
            if isinstance(retryable_flag, bool):
                return retryable_flag

        # Check for retryable status codes on errors that have them
        # This covers both BackendError and LLMProxyError hierarchies
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            # 5xx server errors and 429 rate limits are retryable
            # 4xx client errors are permanent
            return status_code >= 500 or status_code == 429

        # Unknown error types - assume permanent, don't retry
        return False
