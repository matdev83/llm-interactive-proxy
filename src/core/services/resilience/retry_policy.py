"""Shared stamina-backed async retry policy primitives."""

from __future__ import annotations

import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

import stamina

from src.core.services.resilience.retry_after import extract_retry_after_seconds

T = TypeVar("T")
RetryPredicate = Callable[[Exception], bool]
RetryAfterExtractor = Callable[[Exception], float | None]
RetryRecordCallback = Callable[["RetryAttemptRecord"], None]


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Base retry policy used by ``AsyncRetryExecutor``."""

    attempts: int | None = 3
    timeout_seconds: float | None = 45.0
    wait_initial: float = 0.1
    wait_max: float = 5.0
    wait_jitter: float = 1.0
    wait_exp_base: float = 2.0


@dataclass(frozen=True, slots=True)
class RetryBudget:
    """Optional per-call overrides for retry policy fields."""

    attempts: int | None = None
    timeout_seconds: float | None = None
    wait_initial: float | None = None
    wait_max: float | None = None
    wait_jitter: float | None = None
    wait_exp_base: float | None = None


@dataclass(frozen=True, slots=True)
class RetryAttemptRecord:
    """Deterministic metadata for each scheduled retry."""

    attempt_num: int
    wait_for_seconds: float
    caused_by_type: str
    caused_by_message: str
    used_retry_after_hint: bool


class AsyncRetryExecutor:
    """Execute async callables using a shared stamina retry policy."""

    def __init__(self, policy: RetryPolicy | None = None) -> None:
        self._policy = policy or RetryPolicy()

    async def execute(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        should_retry: RetryPredicate | None = None,
        retry_after_extractor: RetryAfterExtractor | None = extract_retry_after_seconds,
        retry_budget: RetryBudget | None = None,
        on_retry_scheduled: RetryRecordCallback | None = None,
    ) -> T:
        """Run an async operation with retry semantics controlled by stamina."""
        predicate = should_retry or (lambda _error: False)
        extractor = retry_after_extractor or (lambda _error: None)
        policy = self._merge_policy(retry_budget)
        retry_history: list[RetryAttemptRecord] = []

        def _backoff_hook(error: Exception) -> bool | float:
            if not predicate(error):
                return False

            attempt_num = len(retry_history) + 1
            if policy.attempts is not None and attempt_num >= policy.attempts:
                return False

            retry_after_hint = self._normalize_non_negative(extractor(error))
            if retry_after_hint is not None:
                used_retry_after_hint = True
                wait_for = retry_after_hint
            else:
                used_retry_after_hint = False
                wait_for = self._compute_wait_lower_bound(policy, attempt_num)
            retry_history.append(
                RetryAttemptRecord(
                    attempt_num=attempt_num,
                    wait_for_seconds=wait_for,
                    caused_by_type=type(error).__name__,
                    caused_by_message=str(error),
                    used_retry_after_hint=used_retry_after_hint,
                )
            )
            if on_retry_scheduled is not None:
                on_retry_scheduled(retry_history[-1])

            if used_retry_after_hint:
                return wait_for

            return True

        try:
            async for attempt in stamina.retry_context(
                on=_backoff_hook,
                attempts=policy.attempts,
                timeout=policy.timeout_seconds,
                wait_initial=policy.wait_initial,
                wait_max=policy.wait_max,
                wait_jitter=policy.wait_jitter,
                wait_exp_base=policy.wait_exp_base,
            ):
                with attempt:
                    return await operation()
        except Exception as error:
            if retry_history:
                cast(Any, error).__retry_history__ = list(retry_history)
            raise

        raise AssertionError("unreachable")

    def _merge_policy(self, retry_budget: RetryBudget | None) -> RetryPolicy:
        if retry_budget is None:
            return self._normalized_policy(self._policy)

        return self._normalized_policy(
            RetryPolicy(
                attempts=(
                    retry_budget.attempts
                    if retry_budget.attempts is not None
                    else self._policy.attempts
                ),
                timeout_seconds=(
                    retry_budget.timeout_seconds
                    if retry_budget.timeout_seconds is not None
                    else self._policy.timeout_seconds
                ),
                wait_initial=(
                    retry_budget.wait_initial
                    if retry_budget.wait_initial is not None
                    else self._policy.wait_initial
                ),
                wait_max=(
                    retry_budget.wait_max
                    if retry_budget.wait_max is not None
                    else self._policy.wait_max
                ),
                wait_jitter=(
                    retry_budget.wait_jitter
                    if retry_budget.wait_jitter is not None
                    else self._policy.wait_jitter
                ),
                wait_exp_base=(
                    retry_budget.wait_exp_base
                    if retry_budget.wait_exp_base is not None
                    else self._policy.wait_exp_base
                ),
            )
        )

    @staticmethod
    def _normalized_policy(policy: RetryPolicy) -> RetryPolicy:
        attempts = policy.attempts
        if attempts is not None:
            attempts = max(1, int(attempts))

        timeout_seconds = policy.timeout_seconds
        if timeout_seconds is not None:
            timeout_seconds = max(0.0, float(timeout_seconds))

        wait_initial = max(0.0, float(policy.wait_initial))
        wait_max = max(wait_initial, float(policy.wait_max))
        wait_jitter = max(0.0, float(policy.wait_jitter))
        wait_exp_base = max(1.0, float(policy.wait_exp_base))

        return RetryPolicy(
            attempts=attempts,
            timeout_seconds=timeout_seconds,
            wait_initial=wait_initial,
            wait_max=wait_max,
            wait_jitter=wait_jitter,
            wait_exp_base=wait_exp_base,
        )

    @staticmethod
    def _normalize_non_negative(value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value < 0:
            return None
        return float(value)

    @staticmethod
    def _compute_wait_lower_bound(policy: RetryPolicy, attempt_num: int) -> float:
        if attempt_num <= 0:
            return 0.0
        baseline = policy.wait_initial * (policy.wait_exp_base ** (attempt_num - 1))
        return min(policy.wait_max, baseline)


__all__ = [
    "AsyncRetryExecutor",
    "RetryAttemptRecord",
    "RetryBudget",
    "RetryPolicy",
]
