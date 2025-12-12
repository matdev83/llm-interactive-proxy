"""
Policies for retry and auth refresh handling in the Gemini connector stack.

These policies encapsulate the decision-making for retry/backoff and
authentication refresh so that orchestration layers can stay lean and
explicitly document their behavior.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from src.core.common.exceptions import AuthenticationError, BackendError

logger = logging.getLogger(__name__)


@dataclass
class RetryDecision:
    """Decision returned by retry policy evaluations."""

    should_retry: bool
    sleep_seconds: float | None = None
    reason: str | None = None


@dataclass
class AuthRefreshDecision:
    """Decision returned by auth refresh policy evaluations."""

    should_refresh: bool
    force_reload: bool = False
    timeout_seconds: float = 30.0
    reason: str | None = None


class IRetryPolicy(Protocol):
    """Interface for retry/backoff decisions."""

    def should_retry(
        self, error: BackendError, attempt: int, *, is_streaming: bool = False
    ) -> RetryDecision:
        """Return retry decision for the given error and attempt count."""
        ...


class IAuthRefreshPolicy(Protocol):
    """Interface for auth refresh decisions."""

    def should_refresh(
        self, error: Exception, attempt: int, *, is_streaming: bool = False
    ) -> AuthRefreshDecision:
        """Return auth refresh decision for the given error and attempt count."""
        ...


class RateLimitRetryPolicy(IRetryPolicy):
    """Retry policy that handles rate limit style errors."""

    def __init__(
        self,
        *,
        retry_delay_extractor: Callable[[BackendError], float | None] | None = None,
        is_rate_limit_like: Callable[[BackendError], bool] | None = None,
        max_attempts: int = 1,
    ) -> None:
        self._retry_delay_extractor = retry_delay_extractor
        self._is_rate_limit_like = is_rate_limit_like or self._default_is_rate_limit
        self._max_attempts = max_attempts

    @staticmethod
    def _default_is_rate_limit(error: BackendError) -> bool:
        return getattr(error, "status_code", None) == 429

    def should_retry(
        self, error: BackendError, attempt: int, *, is_streaming: bool = False
    ) -> RetryDecision:
        if not self._is_rate_limit_like(error):
            return RetryDecision(False, reason="not_rate_limited")

        if attempt >= self._max_attempts:
            return RetryDecision(False, reason="max_attempts_reached")

        delay_value = None
        if self._retry_delay_extractor is not None:
            delay = self._retry_delay_extractor(error)
            if delay is not None and delay > 0:
                delay_value = delay

        if delay_value is None:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "RateLimitRetryPolicy: attempt=%s, streaming=%s, delay=None -> no retry",
                    attempt,
                    is_streaming,
                )
            return RetryDecision(False, reason="no_retry_after")

        decision = RetryDecision(
            should_retry=True,
            sleep_seconds=delay_value,
            reason="rate_limit",
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "RateLimitRetryPolicy: attempt=%s, streaming=%s, delay=%s",
                attempt,
                is_streaming,
                delay_value,
            )

        return decision


class AuthRefreshPolicy(IAuthRefreshPolicy):
    """Auth refresh policy that encapsulates 401 retry rules."""

    def __init__(self, *, timeout_seconds: float = 30.0, max_attempts: int = 1) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts

    def _is_auth_error(self, error: Exception) -> bool:
        if isinstance(error, AuthenticationError):
            return True
        if isinstance(error, BackendError):
            return getattr(error, "status_code", None) == 401
        return False

    def should_refresh(
        self, error: Exception, attempt: int, *, is_streaming: bool = False
    ) -> AuthRefreshDecision:
        if not self._is_auth_error(error):
            return AuthRefreshDecision(False, reason="not_auth_error")

        if attempt >= self._max_attempts:
            return AuthRefreshDecision(False, reason="max_attempts_reached")

        decision = AuthRefreshDecision(
            should_refresh=True,
            force_reload=True,
            timeout_seconds=self._timeout_seconds,
            reason="auth_refresh",
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "AuthRefreshPolicy: attempt=%s, streaming=%s, timeout=%s",
                attempt,
                is_streaming,
                self._timeout_seconds,
            )

        return decision


__all__ = [
    "AuthRefreshDecision",
    "AuthRefreshPolicy",
    "IAuthRefreshPolicy",
    "IRetryPolicy",
    "RateLimitRetryPolicy",
    "RetryDecision",
]
