"""
Authentication error handler for the resilience layer.

Handles authentication errors by permanently disabling the backend instance
until it is manually reactivated.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.common.exceptions import AuthenticationError
from src.core.interfaces.resilience_interface import (
    ActionType,
    ErrorContext,
    ResilienceAction,
)
from src.core.services.resilience.handlers.base_handler import BaseErrorHandler

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# HTTP status codes indicating authentication failures.
#
# IMPORTANT: Do not treat generic 403 responses as authentication failures.
# Many providers use 403 for policy blocks, temporary account restrictions,
# or quota-related denial. Permanently disabling an instance on 403 can turn a
# transient/semantic failure into persistent RoutingError 503s for clients.
#
# If a connector wants a 403 to be treated as auth, it should raise
# AuthenticationError explicitly.
AUTH_STATUS_CODES = frozenset([401])


class AuthErrorHandler(BaseErrorHandler):
    """Handles authentication errors by disabling instances.

    When an authentication error is detected (401/403 or AuthenticationError),
    the backend instance is marked as permanently disabled. This prevents
    further requests to the instance until it is manually reactivated.

    Use cases:
    - Invalid API key
    - Expired API key
    - Revoked access
    - Insufficient permissions
    """

    def can_handle(self, error: Exception) -> bool:
        """Check if this is an authentication error.

        Args:
            error: The exception to check

        Returns:
            True if this is a 401/403, AuthenticationError, or contains a block message
        """
        # Check for our domain AuthenticationError
        if isinstance(error, AuthenticationError):
            return True

        # Check for specific block message "To continue, validate"
        error_msg = str(error)
        if "To continue, validate" in error_msg:
            return True

        # Check for HTTP 401 status code
        status_code = getattr(error, "status_code", None)
        if status_code in AUTH_STATUS_CODES:
            return True

        # Check for httpx/requests response with 401
        response = getattr(error, "response", None)
        if response is not None:
            resp_status = getattr(response, "status_code", None)
            if resp_status in AUTH_STATUS_CODES:
                return True

        return False

    def _do_handle(self, context: ErrorContext) -> ResilienceAction:
        """Handle the authentication error by disabling the instance.

        Args:
            context: Error context with instance, model, and error details

        Returns:
            ResilienceAction indicating instance was disabled
        """
        backend_type = str(context.extra.get("backend_type", "")).lower()
        instance_id_lower = str(context.instance_id or "").lower()
        if "oauth-auto" in backend_type:
            return ResilienceAction(
                type=ActionType.PROCEED,
                reason="OAuth auto backends manage auth failures per account",
            )

        # Personal backends (typically OAuth) are scoped per user/session.
        # A 401 can be transient (expired token) and the connector can refresh.
        # Permanently disabling even a scoped instance turns auth blips into
        # persistent RoutingError 503s for that user.
        # NOTE: Some failure recorders don't attach __resilience_context__ to the
        # error (e.g., failures observed after returning an error envelope).
        # In that case, infer OAuth-ness from the instance id.
        # OpenCode Go uses one API key for both OpenAI- and Anthropic-shaped routes.
        # Upstream may return HTTP 401 for ambiguous reasons (subscription, routing,
        # or header quirks). Permanently disabling the shared instance blocks every
        # model on that backend and surfaces as "no available backend instance".
        if instance_id_lower.startswith("opencode-go"):
            return ResilienceAction(
                type=ActionType.PROCEED,
                reason=(
                    "Auth errors for opencode-go do not permanently disable the instance"
                ),
            )

        if (
            context.extra.get("is_personal_backend") is True
            or "oauth" in backend_type
            or "oauth" in instance_id_lower
            or "codex" in instance_id_lower
        ):
            return ResilienceAction(
                type=ActionType.PROCEED,
                reason="Auth errors for personal/OAuth backends are not permanently disabled",
            )

        # Build a descriptive reason
        reason = self._build_reason(context.error)

        # Disable the instance permanently
        self._state.disable_instance(context.instance_id, reason)

        logger.error(
            "Instance %s permanently disabled due to authentication failure: %s",
            context.instance_id,
            reason,
        )

        return ResilienceAction(
            type=ActionType.DISABLE_INSTANCE,
            reason=reason,
            permanent=True,
        )

    def _build_reason(self, error: Exception) -> str:
        """Build a human-readable reason from the error.

        Args:
            error: The authentication error

        Returns:
            Descriptive reason string
        """
        parts = []

        # Get status code if available
        status_code = getattr(error, "status_code", None)
        if status_code:
            parts.append(f"HTTP {status_code}")

        # Get error message
        message = None

        # Try various message attributes
        for attr in ("message", "detail"):
            msg = getattr(error, attr, None)
            if msg:
                if isinstance(msg, dict):
                    message = msg.get("message") or msg.get("error") or str(msg)
                else:
                    message = str(msg)
                break

        if not message:
            message = str(error)

        # Truncate long messages
        if len(message) > 200:
            message = message[:197] + "..."

        parts.append(message)

        return " - ".join(parts) if parts else "Authentication failed"
