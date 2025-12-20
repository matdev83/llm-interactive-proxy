"""
Loop detector factory service.

This service provides per-stream loop detector instances with fail-open behavior.

Requirements: 4.4, 5.5
"""

from __future__ import annotations

import logging
from typing import cast

from src.core.interfaces.backend_request_manager_components import (
    ILoopDetectorFactory,
)
from src.core.interfaces.di_interface import IServiceProvider
from src.core.interfaces.loop_detector_interface import ILoopDetector

logger = logging.getLogger(__name__)


class LoopDetectorFactory(ILoopDetectorFactory):
    """Factory for creating per-stream loop detector instances."""

    def __init__(self, provider: IServiceProvider) -> None:
        """Initialize the loop detector factory.

        Args:
            provider: Service provider for resolving ILoopDetector service
        """
        self._provider = provider

    def create(self) -> ILoopDetector:
        """Return a ready loop detector instance.

        Returns:
            A loop detector instance that has been reset and is ready for use

        The factory attempts to resolve ILoopDetector from DI. If unavailable,
        it falls back to creating a HybridLoopDetector instance directly.
        """
        try:
            detector = self._provider.get_service(cast(type, ILoopDetector))
            if detector is not None:
                detector.reset()
                return detector
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to resolve ILoopDetector from DI, using fallback",
                    exc_info=True,
                )

        # Fallback: create a standalone detector
        try:
            from src.loop_detection.hybrid_detector import HybridLoopDetector

            fallback = HybridLoopDetector()
            fallback.reset()
            return fallback
        except Exception:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "Failed to create fallback loop detector",
                    exc_info=True,
                )
            # Final fallback: return a no-op detector
            from src.loop_detection.detector import NoOpLoopDetector

            return NoOpLoopDetector()
