"""JSON sanitization for response adapters."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.core.services.steering_leak_protection import SteeringLeakProtector

logger = logging.getLogger(__name__)


class JSONSanitizer:
    """Ensure JSON-safe content by converting non-serializable objects.

    Recursively sanitizes content to ensure all objects are JSON-serializable.
    Integrates with SteeringLeakProtector for final security layer.
    """

    def __init__(
        self,
        protector: SteeringLeakProtector | None = None,
    ) -> None:
        """Initialize JSON sanitizer.

        Args:
            protector: Optional SteeringLeakProtector instance. If not provided,
                     falls back to global accessor.
        """
        self._protector = protector
        self._async_mock_type: type | None = None
        try:
            from unittest.mock import AsyncMock

            self._async_mock_type = AsyncMock
        except ImportError:
            pass

    def sanitize(self, content: Any) -> Any:
        """Convert non-serializable objects to safe representations.

        Args:
            content: Content to sanitize

        Returns:
            JSON-safe content
        """
        # Apply steering leak protection for dict content
        if isinstance(content, dict):
            protector = self._get_protector()
            if protector and protector.enabled:
                result = protector.sanitize_dict(content)
                if result.had_leak:
                    logger.warning(
                        "SECURITY: Sanitized leaked steering data from JSON content"
                    )
                content = result.data

        return self._sanitize_recursive(content)

    def _sanitize_recursive(self, obj: Any) -> Any:
        """Recursively sanitize content to ensure JSON serializability.

        Args:
            obj: Object to sanitize

        Returns:
            Sanitized object
        """
        if obj is None:
            return None

        if isinstance(obj, dict):
            return {k: self._sanitize_recursive(v) for k, v in obj.items()}

        if isinstance(obj, list):
            return [self._sanitize_recursive(v) for v in obj]

        if isinstance(obj, tuple):
            return tuple(self._sanitize_recursive(v) for v in obj)

        # Check for coroutines
        try:
            if asyncio.iscoroutine(obj):
                return str(obj)
        except TypeError:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Sanitize: Could not check for coroutine: %s", obj)

        # Check for AsyncMock
        if self._async_mock_type is not None:
            try:
                if isinstance(obj, self._async_mock_type):
                    return str(obj)
            except TypeError:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug("Sanitize: Could not check for async_mock: %s", obj)

        # Try JSON serialization
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)

    def _get_protector(self) -> SteeringLeakProtector | None:
        """Get steering leak protector instance.

        Returns:
            Protector instance or None
        """
        if self._protector is not None:
            return self._protector

        try:
            from src.core.services.steering_leak_protection import (
                get_steering_leak_protector,
            )

            return get_steering_leak_protector()
        except Exception as e:  # noqa: F841 - used via exc_info=True
            # Log at WARNING level: failure to get steering leak protector is
            # important for security (could leak steering prompts)
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Could not get steering leak protector",
                    exc_info=True,
                )
            return None
