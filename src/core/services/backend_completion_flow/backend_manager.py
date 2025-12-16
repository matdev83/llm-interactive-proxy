"""Backend management logic for backend completion flow."""

from __future__ import annotations

import logging
import time
from typing import Any

from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import IResilienceCoordinator

logger = logging.getLogger(__name__)


class BackendManager:
    """Handles backend acquisition, availability checks, and health validation."""

    def __init__(
        self,
        backend_lifecycle_manager: IBackendLifecycleManager,
        resilience_coordinator: IResilienceCoordinator | None,
        failover_routes: dict[str, dict[str, Any]] | None = None,
    ):
        """Initialize the backend manager."""
        self._backend_lifecycle_manager = backend_lifecycle_manager
        self._resilience = resilience_coordinator
        self._failover_routes = failover_routes or {}

    async def check_backend_availability(
        self, backend_type: str, effective_model: str, allow_failover: bool
    ) -> None:
        """Check if the backend is available (not disabled, not rate limited).

        Args:
            backend_type: The backend name
            effective_model: The model name
            allow_failover: Whether failover is allowed

        Raises:
            BackendError: If backend is permanently disabled
            RateLimitExceededError: If backend is rate limited
        """
        # Check if backend is permanently disabled
        disabled_info = self._backend_lifecycle_manager.get_disabled_backends().get(
            backend_type
        )
        if disabled_info and not (
            allow_failover
            and (
                effective_model in self._failover_routes
                or backend_type in self._failover_routes
            )
        ):
            raise BackendError(
                message=(
                    f"Backend {backend_type} is permanently disabled: "
                    f"{disabled_info.get('reason', 'authentication failed')}"
                ),
                backend_name=backend_type,
            )

        # Check resilience coordinator for instance/model availability
        if self._resilience:
            decision = self._resilience.check_availability(
                backend_type, effective_model
            )
            if not decision.should_proceed():
                cooldown_info = (
                    f" (retry after {decision.cooldown_remaining:.1f}s)"
                    if decision.cooldown_remaining
                    else ""
                )
                raise RateLimitExceededError(
                    message=f"{decision.reason}{cooldown_info}",
                    reset_at=(
                        time.time() + decision.cooldown_remaining
                        if decision.cooldown_remaining
                        else None
                    ),
                )

    async def acquire_backend(
        self, backend_type: str, session_id: str | None
    ) -> LLMBackend:
        """Get or create a backend instance and verify it's healthy.

        Args:
            backend_type: The backend name
            session_id: Optional session ID for per-session backends

        Returns:
            The backend instance

        Raises:
            BackendError: If backend cannot be initialized or is unhealthy
            RateLimitExceededError: If backend is rate limited
        """
        # Initialize backend only after passing rate limiting checks
        try:
            backend = await self._backend_lifecycle_manager.get_or_create(
                backend_type, session_id=session_id
            )
        except (TypeError, ValueError, AttributeError, KeyError) as e:
            raise BackendError(
                message=f"Failed to initialize backend {backend_type}",
                backend_name=backend_type,
                details={"error": str(e)},
            ) from e

        # Check if backend is rate limited by retry-after
        if hasattr(backend, "get_retry_after_remaining"):
            retry_after_remaining = backend.get_retry_after_remaining()
            if retry_after_remaining is not None:
                # Ensure it is a number before using
                if isinstance(retry_after_remaining, (int, float)):
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Backend %s is rate limited, retry after %.1f seconds",
                            backend_type,
                            retry_after_remaining,
                        )
                    raise RateLimitExceededError(
                        message=f"Backend {backend_type} is rate limited",
                        details={
                            "backend": backend_type,
                            "retry_after_seconds": retry_after_remaining,
                        },
                        reset_at=time.time() + retry_after_remaining,
                    )
                else:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Backend %s returned invalid retry_after type: %s",
                            backend_type,
                            type(retry_after_remaining),
                        )

        # Check if backend is functional, with recovery attempt
        if (
            hasattr(backend, "is_backend_functional")
            and not backend.is_backend_functional()
        ):
            # Try to recover the backend before giving up
            recovered = False
            if hasattr(backend, "_validate_runtime_credentials"):
                try:
                    recovered = await backend._validate_runtime_credentials()
                    if recovered and logger.isEnabledFor(logging.INFO):
                        logger.info(
                            "Backend %s recovered after validation check",
                            backend_type,
                        )
                except Exception as e:
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Backend %s recovery attempt failed: %s",
                            backend_type,
                            e,
                        )

            # Re-check functional status after recovery attempt
            if not recovered and not backend.is_backend_functional():
                # Get detailed validation errors if available
                validation_errors: list[str] = []
                if hasattr(backend, "get_validation_errors"):
                    validation_errors = backend.get_validation_errors()

                error_details: dict[str, Any] = {
                    "reason": "Backend reported as non-functional",
                }

                if validation_errors:
                    error_details["validation_errors"] = validation_errors
                    error_message = f"Backend {backend_type} is not functional: {'; '.join(validation_errors)}"
                else:
                    error_message = f"Backend {backend_type} is not functional"

                # Log the error for visibility
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Backend %s is not functional: %s",
                        backend_type,
                        error_message,
                    )

                raise BackendError(
                    message=error_message,
                    backend_name=backend_type,
                    details=error_details,
                )

        return backend
