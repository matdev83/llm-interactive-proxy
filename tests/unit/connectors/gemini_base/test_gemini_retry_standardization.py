"""Standardization tests for Gemini shared retry integration."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from src.connectors.gemini_base.streaming_executor import StreamingExecutor
from src.core.common.exceptions import BackendError
from src.core.services.resilience.retry_policy import RetryAttemptRecord, RetryBudget


@pytest.mark.asyncio
async def test_rate_limit_retry_wait_uses_provider_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    executor = StreamingExecutor(translation_service=MagicMock())
    error = BackendError(
        message="rate limited",
        code="rate_limit_exceeded",
        status_code=429,
        details={"retry_after": 4.0},
    )

    record = await executor._wait_for_rate_limit_retry(error)

    assert record.used_retry_after_hint is True
    assert record.wait_for_seconds == 4.0
    assert sleep_calls == [4.0]


@pytest.mark.asyncio
async def test_rate_limit_retry_wait_falls_back_to_exponential_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    executor = StreamingExecutor(translation_service=MagicMock())
    error = BackendError(
        message="rate limited",
        code="rate_limit_exceeded",
        status_code=429,
        details={},
    )

    record = await executor._wait_for_rate_limit_retry(error)

    assert record.used_retry_after_hint is False
    assert record.wait_for_seconds == executor.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    assert len(sleep_calls) == 1
    assert sleep_calls[0] >= executor.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    assert sleep_calls[0] <= executor.DEFAULT_RATE_LIMIT_BACKOFF_SECONDS + 0.3


def test_backend_cooldown_only_moves_forward() -> None:
    executor = StreamingExecutor(translation_service=MagicMock())
    backend_scope = executor._get_backend_cooldown_scope("gemini-oauth-auto")
    model = "gemini-test-model"

    executor._set_backend_cooldown(backend_scope, model, 5.0)
    first_remaining = executor._get_backend_cooldown_remaining(backend_scope, model)

    executor._set_backend_cooldown(backend_scope, model, 1.0)
    second_remaining = executor._get_backend_cooldown_remaining(backend_scope, model)

    executor._set_backend_cooldown(backend_scope, model, 8.0)
    third_remaining = executor._get_backend_cooldown_remaining(backend_scope, model)

    assert second_remaining >= first_remaining - 0.25
    assert third_remaining >= second_remaining


def test_backend_cooldown_scope_uses_backend_type_only() -> None:
    executor = StreamingExecutor(translation_service=MagicMock())
    assert (
        executor._get_backend_cooldown_scope("gemini-oauth-auto") == "gemini-oauth-auto"
    )
    assert executor._get_backend_cooldown_scope(" GEMINI ") == "gemini"


@pytest.mark.asyncio
async def test_retry_exhaustion_surfaces_backend_error_with_retry_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executor = StreamingExecutor(translation_service=MagicMock())
    source_error = BackendError(
        message="rate limited",
        code="rate_limit_exceeded",
        status_code=429,
        details={"retry_after": 1.5},
    )

    retry_failure = RuntimeError("retries exhausted")
    cast(Any, retry_failure).__retry_history__ = [
        RetryAttemptRecord(
            attempt_num=1,
            wait_for_seconds=1.5,
            caused_by_type="BackendError",
            caused_by_message="rate limited",
            used_retry_after_hint=True,
        )
    ]

    async def fake_execute(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise retry_failure

    monkeypatch.setattr(executor._shared_retry_executor, "execute", fake_execute)

    with pytest.raises(BackendError) as exc_info:
        await executor._wait_for_rate_limit_retry(
            source_error,
            retry_budget=RetryBudget(attempts=1),
        )

    details = exc_info.value.details
    assert details["retry_after"] == 1.5
    assert isinstance(details["retry_history"], list)
    assert details["retry_history"][0]["attempt_num"] == 1
    assert details["retry_history"][0]["wait_for_seconds"] == 1.5
