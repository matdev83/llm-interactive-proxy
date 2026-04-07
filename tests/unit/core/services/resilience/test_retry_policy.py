"""Tests for shared resilience retry policy helpers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import stamina
from src.core.common.exceptions import BackendError
from src.core.services.resilience.retry_after import extract_retry_after_seconds
from src.core.services.resilience.retry_policy import AsyncRetryExecutor, RetryPolicy


class RetryableError(Exception):
    """Retryable test exception."""


class NonRetryableError(Exception):
    """Non-retryable test exception."""


def test_extract_retry_after_seconds_from_headers() -> None:
    error_string = BackendError(
        "rate limit",
        status_code=429,
        details={"headers": {"retry-after": "12.5"}},
    )
    error_numeric = BackendError(
        "rate limit",
        status_code=429,
        details={"headers": {"Retry-After": 7}},
    )

    assert extract_retry_after_seconds(error_string) == 12.5
    assert extract_retry_after_seconds(error_numeric) == 7.0


def test_extract_retry_after_seconds_ignores_invalid_retry_after_date() -> None:
    error = BackendError(
        "retry after 6 seconds",
        status_code=429,
        details={"headers": {"retry-after": "not-a-valid-http-date"}},
    )

    assert extract_retry_after_seconds(error) == 6.0


def test_extract_retry_after_seconds_from_details_fields() -> None:
    error_seconds = BackendError(
        "rate limit",
        status_code=429,
        details={"retry_after_seconds": "9"},
    )
    error_retry_after = BackendError(
        "rate limit",
        status_code=429,
        details={"retry_after": 4},
    )

    assert extract_retry_after_seconds(error_seconds) == 9.0
    assert extract_retry_after_seconds(error_retry_after) == 4.0


def test_extract_retry_after_seconds_from_google_retry_formats() -> None:
    retry_info_error = BackendError(
        "rate limit",
        status_code=429,
        details={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "1.25s",
                    }
                ]
            }
        },
    )
    error_info_error = BackendError(
        "rate limit",
        status_code=429,
        details={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "metadata": {"quotaResetDelay": "2m3s"},
                    }
                ]
            }
        },
    )

    assert extract_retry_after_seconds(retry_info_error) == 1.25
    assert extract_retry_after_seconds(error_info_error) == 123.0


def test_extract_retry_after_seconds_accepts_zero_duration_strings() -> None:
    retry_info_error = BackendError(
        "rate limit",
        status_code=429,
        details={
            "error": {
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.RetryInfo",
                        "retryDelay": "0s",
                    }
                ]
            }
        },
    )

    assert extract_retry_after_seconds(retry_info_error) == 0.0


@pytest.mark.asyncio
async def test_async_retry_executor_retries_only_for_configured_errors() -> None:
    non_retry_calls = 0
    retry_calls = 0

    async def non_retry_operation() -> None:
        nonlocal non_retry_calls
        non_retry_calls += 1
        raise NonRetryableError("do not retry")

    async def retry_operation() -> str:
        nonlocal retry_calls
        retry_calls += 1
        if retry_calls == 1:
            raise RetryableError("retry once")
        return "ok"

    executor = AsyncRetryExecutor(
        RetryPolicy(attempts=4, wait_initial=0.1, wait_max=1.0, wait_jitter=0.0)
    )

    with pytest.raises(NonRetryableError):
        await executor.execute(
            non_retry_operation,
            should_retry=lambda error: isinstance(error, RetryableError),
        )
    assert non_retry_calls == 1

    result = await executor.execute(
        retry_operation,
        should_retry=lambda error: isinstance(error, RetryableError),
    )
    assert result == "ok"
    assert retry_calls == 2


@pytest.mark.asyncio
async def test_async_retry_executor_uses_retry_after_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = 0
    retry_error = BackendError(
        "rate limited",
        status_code=429,
        details={"retry_after": 3.5},
    )

    async def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise retry_error
        return "done"

    executor = AsyncRetryExecutor(
        RetryPolicy(attempts=3, wait_initial=0.1, wait_max=5.0, wait_jitter=0.0)
    )
    result = await executor.execute(
        operation,
        should_retry=lambda error: isinstance(error, BackendError),
    )

    assert result == "done"
    assert sleep_calls == [3.5]


@pytest.mark.asyncio
async def test_async_retry_executor_stamina_testing_caps_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep_mock = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep_mock)

    attempts = 0

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise RetryableError("still failing")

    executor = AsyncRetryExecutor(RetryPolicy(attempts=100, wait_initial=0.1))

    with stamina.set_testing(True, attempts=3, cap=True), pytest.raises(RetryableError):
        await executor.execute(
            operation,
            should_retry=lambda error: isinstance(error, RetryableError),
        )

    assert attempts == 3
    assert sleep_mock.await_count == 2
    assert all(call.args == (0.0,) for call in sleep_mock.await_args_list)


@pytest.mark.asyncio
async def test_async_retry_executor_attaches_retry_history_on_exhaustion() -> None:
    async def operation() -> None:
        raise RetryableError("exhausted")

    executor = AsyncRetryExecutor(
        RetryPolicy(
            attempts=3,
            wait_initial=0.2,
            wait_max=5.0,
            wait_jitter=0.0,
            wait_exp_base=2.0,
        )
    )

    with (
        stamina.set_testing(True, attempts=3, cap=True),
        pytest.raises(RetryableError) as exc_info,
    ):
        await executor.execute(
            operation,
            should_retry=lambda error: isinstance(error, RetryableError),
        )

    history = getattr(exc_info.value, "__retry_history__", None)
    assert isinstance(history, list)
    assert len(history) == 2
    assert [entry.attempt_num for entry in history] == [1, 2]
    assert [entry.wait_for_seconds for entry in history] == [0.2, 0.4]
    assert all(entry.caused_by_type == "RetryableError" for entry in history)
    assert all(entry.used_retry_after_hint is False for entry in history)
