from __future__ import annotations

import abc
import logging
import time
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

from src.core.config.app_config import AppConfig
from src.core.domain.connection_activity import ConnectionType
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.activity_tracker_interface import IConnectionActivityTracker
from src.core.interfaces.health_aware_interface import IHealthAware

if TYPE_CHECKING:
    from src.connectors.contracts import ConnectorChatCompletionsRequest
    from src.core.interfaces.response_processor_interface import IResponseProcessor

logger = logging.getLogger(__name__)


def strip_vendor_prefix(model: str, vendor: str) -> str:
    """Strip vendor prefix from model name if present.

    This utility helps single-vendor backends accept both vendor-prefixed
    and non-prefixed model names for backward compatibility.

    Args:
        model: Model name (e.g., "google/gemini-2.5-pro" or "gemini-2.5-pro")
        vendor: Expected vendor prefix (e.g., "google")

    Returns:
        Model name without vendor prefix (e.g., "gemini-2.5-pro")
    """
    prefix = f"{vendor}/"
    if model.startswith(prefix):
        return model[len(prefix) :]
    return model


def add_vendor_prefix(model: str, vendor: str) -> str:
    """Add vendor prefix to model name if not present.

    This utility helps single-vendor backends return fully qualified
    model names in get_available_models() for unified model routing.

    Args:
        model: Model name (e.g., "gemini-2.5-pro")
        vendor: Vendor prefix to add (e.g., "google")

    Returns:
        Model name with vendor prefix (e.g., "google/gemini-2.5-pro")
    """
    prefix = f"{vendor}/"
    if model.startswith(prefix):
        return model
    return f"{prefix}{model}"


class LLMBackend(abc.ABC, IHealthAware):
    """
    Abstract base class for Large Language Model (LLM) backends.
    Defines the interface for interacting with different LLM providers.

    Implements IHealthAware for automatic health state notifications:
    - Tracks endpoint health status
    - Receives notifications when API endpoint health changes
    - Integrates with circuit breaker logic via is_backend_functional()

    Activity Tracking:
    - Optionally tracks active connections for diagnostics
    - Provides RX/TX byte counters per session
    - Use set_activity_tracker() to enable activity tracking
    """

    backend_type: str

    def __init__(
        self, config: AppConfig, response_processor: IResponseProcessor | None = None
    ) -> None:
        self._response_processor = response_processor
        self.config = config
        self._retry_after_until: float | None = None
        # Health-aware state
        self._endpoint_healthy: bool = True
        self._auth_valid: bool = True
        self._api_url: str | None = None
        self._last_health_change_reason: str | None = None
        # Activity tracking (optional)
        self._activity_tracker: IConnectionActivityTracker | None = None
        self._instance_name: str | None = None
        # Quota headers captured from the last backend response
        self._last_quota_headers: dict[str, str] = {}

    @property
    def last_quota_headers(self) -> dict[str, str]:
        """Get the quota headers captured from the last backend response.

        Returns:
            Dictionary of quota headers (e.g., x-codex-*)
        """
        return getattr(self, "_last_quota_headers", {})

    def update_quota_headers(self, headers: Mapping[str, str]) -> None:
        """Update captured quota headers from a response.

        Args:
            headers: Response headers from the backend
        """
        if not hasattr(self, "_last_quota_headers"):
            self._last_quota_headers = {}

        quota_prefixes = ("x-codex-", "x-ratelimit-", "x-usage-")
        captured = {}
        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower.startswith(quota_prefixes):
                val = str(v)
                self._last_quota_headers[k_lower] = val
                captured[k_lower] = val

        # Also update global quota status service
        if captured:
            try:
                from src.core.services.quota_status_service import (
                    get_quota_status_service,
                )

                service = get_quota_status_service()
                service.update_quota(self.backend_type, captured)
            except ImportError:
                pass

    @property
    def api_url(self) -> str | None:
        """The API URL this backend is configured to use.

        Returns:
            The API endpoint URL, or None if not yet initialized.
        """
        return self._api_url

    @api_url.setter
    def api_url(self, value: str | None) -> None:
        """Set the API URL for this backend."""
        self._api_url = value

    @property
    def is_endpoint_healthy(self) -> bool:
        """Current health status of the backend's API endpoint.

        Returns:
            True if the endpoint is considered healthy.
        """
        # Use getattr for defensive programming - some test backends may not
        # call super().__init__() and thus won't have this attribute
        return getattr(self, "_endpoint_healthy", True) and getattr(
            self, "_auth_valid", True
        )

    def mark_auth_invalid(self, reason: str = "Authentication failed") -> None:
        """Permanently mark the backend as having invalid credentials.

        This disables the backend for future routing/usage and prevents
        health check recovery.

        Args:
            reason: The reason for invalidating credentials.
        """
        self._auth_valid = False
        self._endpoint_healthy = False
        self._last_health_change_reason = reason
        if logger.isEnabledFor(logging.ERROR):
            logger.error(
                "Backend %s: %s. Backend permanently disabled.",
                getattr(self, "backend_type", "unknown"),
                reason,
            )

    async def on_endpoint_healthy(self, api_url: str) -> None:
        """Called when the API endpoint becomes healthy (recovery).

        Updates internal state and logs the recovery event.

        Args:
            api_url: The API URL that became healthy.
        """
        my_url = getattr(self, "_api_url", None)
        if my_url and my_url != api_url:
            # Not our URL, ignore
            return

        # If auth is invalid, we cannot recover via simple health check
        if not getattr(self, "_auth_valid", True):
            return

        previous_state = getattr(self, "_endpoint_healthy", True)
        self._endpoint_healthy = True
        self._last_health_change_reason = None

        if not previous_state and logger.isEnabledFor(logging.WARNING):
            # State transition: unhealthy -> healthy
            logger.warning(
                "Backend %s: endpoint %s health recovered",
                getattr(self, "backend_type", "unknown"),
                api_url,
            )

    @property
    def has_static_credentials(self) -> bool:
        """
        Whether this backend uses static credentials (e.g. env vars).
        If True, authentication failures are considered permanent.
        If False, authentication failures might be recoverable (e.g. token refresh).
        """
        return True

    async def on_endpoint_unhealthy(self, api_url: str, reason: str) -> None:
        """Called when the API endpoint becomes unhealthy (degradation).

        Updates internal state, logs a warning, and enables circuit breaker.

        Args:
            api_url: The API URL that became unhealthy.
            reason: Human-readable reason for the health degradation.
        """
        my_url = getattr(self, "_api_url", None)
        if my_url and my_url != api_url:
            # Not our URL, ignore
            return

        # If auth is invalid, we stay in that state (don't overwrite reason)
        if not getattr(self, "_auth_valid", True):
            return

        previous_state = getattr(self, "_endpoint_healthy", True)
        self._endpoint_healthy = False
        self._last_health_change_reason = reason

        if previous_state and logger.isEnabledFor(logging.WARNING):
            # State transition: healthy -> unhealthy
            logger.warning(
                "Backend %s: endpoint %s health degraded: %s",
                getattr(self, "backend_type", "unknown"),
                api_url,
                reason,
            )

    @abc.abstractmethod
    async def chat_completions(
        self,
        request: ConnectorChatCompletionsRequest,
    ) -> ResponseEnvelope | StreamingResponseEnvelope:
        """
        Forwards a chat completion request to the LLM backend.

        Args:
            request: Canonical connector request containing the domain chat payload,
                processed messages, effective model, optional identity and cancellation
                fields, connector-facing context, and JSON-safe provider options.

        Returns:
            Either a ResponseEnvelope for non-streaming requests or
            a StreamingResponseEnvelope for streaming requests.
        """

    @abc.abstractmethod
    async def initialize(self, **kwargs: Any) -> None:
        """
        Initialize the backend with configuration.

        Args:
            **kwargs: Configuration parameters for the backend.
        """

    @abc.abstractmethod
    def get_available_models(self) -> list[str]:
        """
        Get a list of available models for this backend.

        IMPORTANT: All implementations MUST return model names with vendor prefixes
        in the format "<vendor>/<model-name>" for unified model routing.

        Examples:
            - ["google/gemini-2.5-pro", "google/gemini-2.5-flash"]
            - ["anthropic/claude-3-opus", "anthropic/claude-3-sonnet"]
            - ["openai/gpt-4", "openai/gpt-3.5-turbo"]

        For multi-vendor backends (like OpenRouter), models should already
        include the vendor prefix from the upstream provider.

        Use the `add_vendor_prefix()` utility function to ensure consistent
        prefixing when returning models from single-vendor backends.

        Returns:
            A list of model identifiers with vendor prefixes (e.g., "vendor/model-name").
        """

    def set_retry_after(self, retry_after_seconds: float) -> None:
        """
        Set the retry-after timestamp for this backend instance.

        Args:
            retry_after_seconds: Number of seconds to wait before retrying
        """
        if not hasattr(self, "_retry_after_until"):
            self._retry_after_until = None
        self._retry_after_until = time.time() + retry_after_seconds

    def get_retry_after_remaining(self) -> float | None:
        """
        Get the remaining seconds until retry-after expires.

        Returns:
            Remaining seconds if retry-after is active, None otherwise
        """
        retry_until = cast(float | None, getattr(self, "_retry_after_until", None))
        if retry_until is None:
            return None

        remaining = retry_until - time.time()
        if remaining <= 0:
            self._retry_after_until = None
            return None

        return remaining

    def is_rate_limited(self) -> bool:
        """
        Check if this backend is currently rate limited.

        Returns:
            True if rate limited, False otherwise
        """
        return self.get_retry_after_remaining() is not None

    def is_backend_functional(self) -> bool:
        """
        Check if this backend is currently functional.

        A backend is functional if:
        - Its API endpoint is healthy (ping and HTTP checks passing)
        - Any subclass-specific conditions are met

        Subclasses can override _is_backend_functional_internal() to add
        additional conditions without losing endpoint health checking.

        Returns:
            True if the backend is functional and can accept requests.
        """
        # Check auth validity first
        if not getattr(self, "_auth_valid", True):
            return False

        # Check endpoint health first (circuit breaker)
        # Use getattr for defensive programming - some test backends may not
        # call super().__init__() and thus won't have this attribute
        if not getattr(self, "_endpoint_healthy", True):
            return False

        # Check subclass-specific conditions
        return self._is_backend_functional_internal()

    def _is_backend_functional_internal(self) -> bool:
        """
        Internal check for subclass-specific functionality conditions.

        Subclasses should override this method instead of is_backend_functional()
        to add additional checks while preserving endpoint health checking.

        Returns:
            True if the backend passes subclass-specific functional checks.
        """
        return True

    async def _validate_runtime_credentials(self) -> bool:
        """
        Attempt to validate runtime credentials and recover if possible.
        Default implementation returns False (no recovery attempt). Subclasses can override.
        """
        return False

    def get_validation_errors(self) -> list[str]:
        """
        Get a list of validation errors if the backend is not functional.

        Includes endpoint health status if unhealthy.

        Returns:
            List of validation error messages.
        """
        errors: list[str] = []

        # Use getattr for defensive programming
        if not getattr(self, "_auth_valid", True):
            reason = (
                getattr(self, "_last_health_change_reason", None)
                or "Authentication failed"
            )
            errors.append(f"Credentials invalid: {reason}")
            # If auth is invalid, we don't need to report endpoint health
            return errors

        if not getattr(self, "_endpoint_healthy", True):
            reason = (
                getattr(self, "_last_health_change_reason", None) or "unknown reason"
            )
            errors.append(f"API endpoint unhealthy: {reason}")

        return errors

    # -------------------------------------------------------------------------
    # Activity Tracking Methods
    # -------------------------------------------------------------------------

    def set_activity_tracker(
        self, tracker: IConnectionActivityTracker, instance_name: str
    ) -> None:
        """Configure activity tracking for this backend.

        Args:
            tracker: The activity tracker service to use.
            instance_name: The unique name of this backend instance.
        """
        self._activity_tracker = tracker
        self._instance_name = instance_name

    @property
    def instance_name(self) -> str:
        """Get the instance name for this backend.

        Returns:
            The instance name, or backend_type if not set.
        """
        if self._instance_name:
            return self._instance_name
        backend_type = getattr(self, "backend_type", None)
        if isinstance(backend_type, str):
            return backend_type
        return "unknown"

    @contextmanager
    def track_connection(
        self,
        session_id: str,
        connection_type: ConnectionType,
        model: str | None = None,
    ) -> Generator[None, None, None]:
        """Context manager to track a connection's lifecycle.

        If no activity tracker is configured, this is a no-op.

        Args:
            session_id: Unique identifier for the session/request.
            connection_type: Whether streaming or non-streaming.
            model: The model being used (optional).

        Yields:
            None - the connection is tracked in the background.
        """
        tracker = self._activity_tracker
        if tracker is None:
            yield
            return

        with tracker.track_connection(
            session_id=session_id,
            backend_name=self.instance_name,
            connection_type=connection_type,
            model=model,
        ):
            yield

    def increment_rx(self, session_id: str, byte_count: int) -> None:
        """Increment received bytes counter for a session.

        Args:
            session_id: The session identifier.
            byte_count: Number of bytes received.
        """
        tracker = self._activity_tracker
        if tracker is not None:
            tracker.increment_rx(session_id, self.instance_name, byte_count)

    def increment_tx(self, session_id: str, byte_count: int) -> None:
        """Increment transmitted bytes counter for a session.

        Args:
            session_id: The session identifier.
            byte_count: Number of bytes transmitted.
        """
        tracker = self._activity_tracker
        if tracker is not None:
            tracker.increment_tx(session_id, self.instance_name, byte_count)
