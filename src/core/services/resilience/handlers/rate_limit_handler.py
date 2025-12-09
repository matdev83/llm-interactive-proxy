"""
Rate limit error handler for the resilience layer.

Handles 429 errors with retry-after support at two granularities:
- Instance-wide (all models affected)
- Model-specific (only the specific model on that instance)
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.core.common.exceptions import RateLimitExceededError
from src.core.interfaces.resilience_interface import (
    ActionType,
    ErrorContext,
    ResilienceAction,
)
from src.core.services.resilience.handlers.base_handler import BaseErrorHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Keywords in error messages that indicate instance-wide rate limits
INSTANCE_WIDE_INDICATORS = frozenset(
    [
        "account",
        "organization",
        "org",
        "api_key",
        "api key",
        "apikey",
        "billing",
        "quota",
        "subscription",
    ]
)

# Default cooldown when retry-after is not provided
DEFAULT_COOLDOWN_SECONDS = 60.0


class RateLimitErrorHandler(BaseErrorHandler):
    """Handles 429 rate limit errors with retry-after support.

    This handler:
    1. Detects rate limit errors (RateLimitExceededError or HTTP 429)
    2. Extracts retry-after duration from error details/headers
    3. Determines if the limit is instance-wide or model-specific
    4. Sets the appropriate cooldown in the state manager
    """

    def __init__(
        self,
        state_manager: Any,
        next_handler: Any | None = None,
        default_cooldown: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        """Initialize the handler.

        Args:
            state_manager: The state manager for tracking cooldowns
            next_handler: The next handler in the chain
            default_cooldown: Default cooldown when retry-after not provided
        """
        super().__init__(state_manager, next_handler)
        self._default_cooldown = default_cooldown

    def can_handle(self, error: Exception) -> bool:
        """Check if this is a rate limit error.

        Args:
            error: The exception to check

        Returns:
            True if this is a 429/rate limit error
        """
        # Check for our domain RateLimitExceededError
        if isinstance(error, RateLimitExceededError):
            return True

        # Check for HTTP 429 status code
        status_code = getattr(error, "status_code", None)
        if status_code == 429:
            return True

        # Check for httpx/requests response with 429
        response = getattr(error, "response", None)
        if response is not None:
            resp_status = getattr(response, "status_code", None)
            if resp_status == 429:
                return True

        return False

    def _do_handle(self, context: ErrorContext) -> ResilienceAction:
        """Handle the rate limit error.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction with cooldown duration
        """
        retry_after = self._extract_retry_after(context.error)

        # Determine if instance-wide or model-specific
        if self._is_instance_wide_limit(context.error):
            self._state.set_instance_cooldown(context.instance_id, retry_after)
            logger.warning(
                "Instance %s rate limited for %.1f seconds (all models affected)",
                context.instance_id,
                retry_after,
            )
            return ResilienceAction(
                type=ActionType.COOLDOWN,
                duration=retry_after,
                reason=f"Instance-wide rate limit for {retry_after:.1f}s",
            )
        else:
            self._state.set_model_cooldown(
                context.instance_id, context.model, retry_after
            )
            logger.warning(
                "Model %s on instance %s rate limited for %.1f seconds",
                context.model,
                context.instance_id,
                retry_after,
            )
            return ResilienceAction(
                type=ActionType.COOLDOWN,
                duration=retry_after,
                reason=f"Model rate limit for {retry_after:.1f}s",
            )

    def _extract_retry_after(self, error: Exception) -> float:
        """Extract retry-after duration from error.

        Checks in order:
        1. RateLimitExceededError.reset_at (timestamp)
        2. error.details['retry_after_seconds']
        3. error.details['headers']['retry-after']
        4. Default fallback

        Args:
            error: The rate limit error

        Returns:
            Retry-after duration in seconds
        """
        # Check RateLimitExceededError.reset_at (Unix timestamp)
        reset_at = getattr(error, "reset_at", None)
        if reset_at is not None:
            try:
                remaining = float(reset_at) - time.time()
                if remaining > 0:
                    return remaining
            except (ValueError, TypeError):
                pass

        # Check details dict for retry_after_seconds
        details = getattr(error, "details", None) or {}
        if isinstance(details, dict):
            # Direct retry_after_seconds
            retry_seconds = details.get("retry_after_seconds")
            if retry_seconds is not None:
                try:
                    return float(retry_seconds)
                except (ValueError, TypeError):
                    pass

            # Check headers for Retry-After
            headers = details.get("headers", {})
            if isinstance(headers, dict):
                retry_after = headers.get("retry-after") or headers.get("Retry-After")
                if retry_after is not None:
                    parsed = self._parse_retry_after_header(retry_after)
                    if parsed is not None:
                        return parsed

        # Check for retry_after directly on error
        retry_after_direct = getattr(error, "retry_after", None)
        if retry_after_direct is not None:
            try:
                return float(retry_after_direct)
            except (ValueError, TypeError):
                pass

        # Default fallback
        return self._default_cooldown

    def _parse_retry_after_header(self, value: str | int | float) -> float | None:
        """Parse Retry-After header value.

        The header can be:
        - A number of seconds (integer or float)
        - An HTTP-date (not commonly used, we'll treat as seconds)

        Args:
            value: The header value

        Returns:
            Seconds to wait, or None if parsing fails
        """
        if isinstance(value, int | float):
            return float(value)

        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                # Could be an HTTP-date, but most APIs use seconds
                logger.debug("Could not parse Retry-After header: %s", value)
                return None

        return None

    def _is_instance_wide_limit(self, error: Exception) -> bool:
        """Detect if rate limit affects entire instance or just the model.

        Instance-wide limits typically mention:
        - account, organization
        - api_key, api key
        - billing, quota, subscription

        Model-specific limits mention:
        - model, tokens per minute, requests per minute

        Args:
            error: The rate limit error

        Returns:
            True if the limit appears to be instance-wide
        """
        # Collect message text from various attributes
        message_parts = []

        # Standard message attribute
        msg = getattr(error, "message", None)
        if msg:
            message_parts.append(str(msg))

        # HTTP detail
        detail = getattr(error, "detail", None)
        if detail:
            if isinstance(detail, dict):
                message_parts.append(str(detail.get("message", "")))
                message_parts.append(str(detail.get("error", "")))
            else:
                message_parts.append(str(detail))

        # Details dict
        details = getattr(error, "details", None)
        if details and isinstance(details, dict):
            message_parts.append(str(details.get("message", "")))
            message_parts.append(str(details.get("error", "")))

        # String representation
        message_parts.append(str(error))

        # Combine and lowercase
        full_message = " ".join(message_parts).lower()

        # Check for instance-wide indicators
        return any(indicator in full_message for indicator in INSTANCE_WIDE_INDICATORS)
