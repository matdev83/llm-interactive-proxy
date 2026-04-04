"""Default failure handling strategy implementation.

This module provides the default strategy for handling backend failures,
implementing invisible resilience through wait-and-retry and automatic failover.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING

from src.core.common.exceptions import (
    AuthenticationError,
    InvalidRequestError,
    RateLimitExceededError,
    RoutingError,
    ValidationError,
)
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingConfig,
    FailureHandlingResult,
    IBackendInstanceDiscovery,
    IFailureHandlingStrategy,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DefaultFailureHandlingStrategy(IFailureHandlingStrategy):
    """Default implementation of the failure handling strategy.

    This strategy provides invisible resilience by:
    1. Waiting silently for short rate limits (< max_silent_wait)
    2. Failing over to alternative backend instances for longer waits
    3. Surfacing errors only when no recovery is possible

    The goal is to make transient failures invisible to the client,
    improving UX for agentic workflows.
    """

    def __init__(
        self,
        config: FailureHandlingConfig | None = None,
        backend_discovery: IBackendInstanceDiscovery | None = None,
    ):
        """Initialize the strategy.

        Args:
            config: Configuration for failure handling behavior.
            backend_discovery: Service to discover alternative backend instances.
        """
        self._config = config or FailureHandlingConfig()
        self._backend_discovery = backend_discovery

    @property
    def config(self) -> FailureHandlingConfig:
        """Get the current configuration."""
        return self._config

    def decide(
        self,
        error: Exception,
        model: str,
        current_backend: str,
        attempted_backends: list[str],
        elapsed_time: float,
        is_streaming: bool,
        content_started: bool,
        available_backends: list[str] | None = None,
    ) -> FailureHandlingResult:
        """Decide how to handle a backend failure.

        Decision logic:
        1. If content already started streaming -> SURFACE_ERROR (can't recover)
        2. If max failover hops exceeded -> SURFACE_ERROR
        3. If total timeout budget exceeded -> SURFACE_ERROR
        4. If recoverable error with short retry-after -> WAIT_AND_RETRY
        5. If alternative backend available -> FAILOVER_IMMEDIATE
        6. Otherwise -> SURFACE_ERROR
        """
        # Rule 1: Can't recover mid-stream
        if content_started:
            logger.debug(
                "Content already started, cannot recover from error: %s", error
            )
            return FailureHandlingResult(
                decision=FailureDecision.SURFACE_ERROR,
                error_to_surface=error,
                reason="Content already streaming, cannot recover",
            )

        # Rule 2: Max failover hops exceeded (attempt budget exhausted)
        if len(attempted_backends) >= self._config.max_failover_hops:
            logger.info(
                "Max failover hops (%d) exceeded for model %s, surfacing error",
                self._config.max_failover_hops,
                model,
            )
            return FailureHandlingResult(
                decision=FailureDecision.SURFACE_ERROR,
                error_to_surface=RoutingError(
                    message=f"Attempt budget exhausted. Max failover hops ({self._config.max_failover_hops}) exceeded for model {model}.",
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "reason": "attempt_budget_exhausted",
                        "model": model,
                        "attempted_backends": attempted_backends,
                    },
                ),
                reason=f"Max failover hops ({self._config.max_failover_hops}) exceeded",
            )

        # Rule 3: Total timeout budget exceeded (attempt budget exhausted)
        if elapsed_time >= self._config.total_timeout_budget:
            logger.info(
                "Total timeout budget (%.1fs) exceeded for model %s, surfacing error",
                self._config.total_timeout_budget,
                model,
            )
            return FailureHandlingResult(
                decision=FailureDecision.SURFACE_ERROR,
                error_to_surface=RoutingError(
                    message=f"Attempt budget exhausted. Total timeout budget ({self._config.total_timeout_budget}s) exceeded for model {model}.",
                    details={
                        "code": "temporarily_unavailable",
                        "category": "availability",
                        "retryable": True,
                        "reason": "attempt_budget_exhausted",
                        "model": model,
                        "elapsed_time": elapsed_time,
                        "attempted_backends": attempted_backends,
                    },
                ),
                reason=f"Total timeout budget ({self._config.total_timeout_budget}s) exceeded",
            )

        # Check if error is recoverable
        is_recoverable = self._is_recoverable_error(error)
        retry_after = self._extract_retry_after(error)

        # Rule 4: Recoverable error with short wait time
        if is_recoverable and retry_after is not None:
            # Add a small safety buffer past provider Retry-After to avoid
            # reconnecting at the exact edge of the rate-limit window.
            wait_time = max(
                retry_after
                + (1.0 if self._has_provider_retry_after_header(error) else 0.0),
                self._config.min_retry_wait,
            )

            # Check if wait time is acceptable
            remaining_budget = self._config.total_timeout_budget - elapsed_time
            if (
                retry_after <= self._config.max_silent_wait
                and wait_time <= remaining_budget
            ):
                logger.info(
                    "Recoverable error on %s, will wait %.1fs and retry (retry-after: %.1fs)",
                    current_backend,
                    wait_time,
                    retry_after,
                )
                return FailureHandlingResult(
                    decision=FailureDecision.WAIT_AND_RETRY,
                    wait_seconds=wait_time,
                    reason=f"Waiting {wait_time:.1f}s for rate limit reset",
                )

        # Rule 5: Try to find an alternative backend
        alternatives = self._find_alternatives(
            model, current_backend, attempted_backends, available_backends
        )

        if alternatives:
            next_backend = alternatives[0]
            logger.info(
                "Failing over from %s to %s for model %s (error: %s)",
                current_backend,
                next_backend,
                model,
                type(error).__name__,
            )
            return FailureHandlingResult(
                decision=FailureDecision.FAILOVER_IMMEDIATE,
                next_backend=next_backend,
                reason=f"Failing over to {next_backend}",
            )

        # Rule 6: No recovery possible
        logger.info(
            "No recovery possible for model %s after trying %s, surfacing error: %s",
            model,
            attempted_backends,
            error,
        )
        return FailureHandlingResult(
            decision=FailureDecision.SURFACE_ERROR,
            error_to_surface=error,
            reason="No alternative backends available",
        )

    def _is_recoverable_error(self, error: Exception) -> bool:
        """Determine if an error is recoverable (worth waiting/retrying).

        Recoverable errors:
        - HTTP 429 Rate Limit
        - HTTP 503 Service Unavailable (if retry-after present)
        - Connection timeouts (transient network issues)

        Unrecoverable errors:
        - HTTP 401/403 Authentication errors
        - HTTP 400 Bad Request
        - HTTP 500 Internal Server Error
        - Invalid API key
        - Model not found
        """
        # Check error type
        if isinstance(
            error, AuthenticationError | ValidationError | InvalidRequestError
        ):
            return False

        if isinstance(error, RateLimitExceededError):
            return True

        # Check status code
        status_code = getattr(error, "status_code", None)
        if status_code == 429:
            return True
        if status_code == 503:
            # 503 is recoverable only if retry-after is present
            return self._extract_retry_after(error) is not None
        if status_code in (400, 401, 403, 500):
            return False

        # Check error code
        error_code = getattr(error, "code", None)
        if error_code in ("invalid_api_key", "model_not_found", "invalid_request"):
            return False
        if error_code in ("rate_limit", "rate_limit_exceeded", "quota_exceeded"):
            return True

        # Check if it looks like a connection error (often recoverable)
        error_msg = str(error).lower()
        return any(
            term in error_msg
            for term in ("timeout", "connection", "network", "temporarily")
        )

    def _extract_retry_after(self, error: Exception) -> float | None:
        """Extract retry-after duration from an error.

        Looks for retry-after in multiple places:
        1. RateLimitExceededError.reset_at (as timestamp, convert to seconds)
        2. error.details['retry_after'] (as seconds)
        3. error.details['error']['details'][*]['retryDelay'] (Google format)
        """
        # Check RateLimitExceededError.reset_at
        if isinstance(error, RateLimitExceededError):
            reset_at = getattr(error, "reset_at", None)
            if reset_at is not None:
                reset_at_float = float(reset_at)
                # reset_at could be a timestamp or seconds from now
                now = time.time()
                if reset_at_float >= now:
                    return max(0.0, reset_at_float - now)
                if reset_at_float > 1e9:  # Looks like a Unix timestamp
                    return max(0.0, reset_at_float - now)
                return reset_at_float

        # Check details dict
        details = getattr(error, "details", None)
        if not details:
            return None

        # Direct retry_after in details
        if "retry_after" in details:
            with contextlib.suppress(TypeError, ValueError):
                return float(details["retry_after"])

        # Explicit normalized retry_after_seconds in details
        if "retry_after_seconds" in details:
            with contextlib.suppress(TypeError, ValueError):
                return float(details["retry_after_seconds"])

        headers = details.get("headers")
        if isinstance(headers, dict):
            retry_after_header = headers.get("retry-after") or headers.get(
                "Retry-After"
            )
            if retry_after_header is not None:
                with contextlib.suppress(TypeError, ValueError):
                    return float(retry_after_header)

        # Google-style nested details
        error_info = details.get("error", details)
        if isinstance(error_info, dict):
            details_list = error_info.get("details", [])
            if isinstance(details_list, list):
                for detail in details_list:
                    if not isinstance(detail, dict):
                        continue
                    # RetryInfo format
                    retry_delay = detail.get("retryDelay")
                    if retry_delay:
                        return self._parse_duration_string(retry_delay)
                    # ErrorInfo metadata format
                    metadata = detail.get("metadata", {})
                    if isinstance(metadata, dict):
                        reset_delay = metadata.get("quotaResetDelay")
                        if reset_delay:
                            return self._parse_duration_string(reset_delay)

        return None

    @staticmethod
    def _has_provider_retry_after_header(error: Exception) -> bool:
        details = getattr(error, "details", None)
        if not isinstance(details, dict):
            return False

        if "retry_after_seconds" in details:
            return True

        headers = details.get("headers")
        if not isinstance(headers, dict):
            return False

        return (
            headers.get("retry-after") is not None
            or headers.get("Retry-After") is not None
        )

    @staticmethod
    def _parse_duration_string(duration: str) -> float | None:
        """Parse duration string like '10s' or '4h51m33.9s'."""
        if not duration:
            return None

        try:
            # Simple seconds format (e.g. "17493.989s" or "0.517960407s")
            if duration.endswith("s") and "m" not in duration and "h" not in duration:
                return float(duration[:-1])

            # Complex format (e.g. "4h51m33.989s")
            total_seconds = 0.0
            current_val = ""

            for char in duration:
                if char.isdigit() or char == ".":
                    current_val += char
                elif char == "h":
                    total_seconds += float(current_val) * 3600
                    current_val = ""
                elif char == "m":
                    total_seconds += float(current_val) * 60
                    current_val = ""
                elif char == "s":
                    total_seconds += float(current_val)
                    current_val = ""

            return total_seconds if total_seconds > 0 else None
        except (ValueError, TypeError):
            return None

    def _find_alternatives(
        self,
        model: str,
        current_backend: str,
        attempted_backends: list[str],
        available_backends: list[str] | None = None,
    ) -> list[str]:
        """Find alternative backend instances for the model.

        Args:
            model: Fully qualified model name.
            current_backend: Current backend that failed.
            attempted_backends: Backends already tried.
            available_backends: Pre-computed list of available backends (if provided).

        Returns:
            List of backend instance names that could serve this model.
        """
        # Build exclusion list
        exclude = set(attempted_backends)
        exclude.add(current_backend)

        # If available backends provided, filter them
        if available_backends is not None:
            return [b for b in available_backends if b not in exclude]

        # Use backend discovery service if available
        if self._backend_discovery is not None:
            return self._backend_discovery.find_alternative_instances(
                model, list(exclude)
            )

        # No discovery available
        return []


__all__ = [
    "DefaultFailureHandlingStrategy",
]
