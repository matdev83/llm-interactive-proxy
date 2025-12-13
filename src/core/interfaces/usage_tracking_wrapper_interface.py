"""Interface for usage tracking wrapper.

Responsible for wrapping streams to track usage metrics
including TTFT, TPS, and completion tokens.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class IUsageTrackingWrapper(ABC):
    """Service interface for wrapping streams with usage tracking."""

    @abstractmethod
    def wrap_stream_for_usage(
        self,
        stream: AsyncIterator[Any],
        ctp_record_id: str | None,
        ptb_record_id: str | None,
        start_time: float,
    ) -> AsyncIterator[Any]:
        """Wrap stream to track usage metrics.

        Tracks:
        - Time to first token (TTFT) measured on first valid completion token
        - Total duration
        - Streaming tokens per second (TPS)
        - Final usage data from chunks

        No-op when IUsageTrackingService is not available or both record IDs are None.

        Args:
            stream: The stream to wrap.
            ctp_record_id: Chat-to-provider record ID for usage tracking.
            ptb_record_id: Provider-to-backend record ID for usage tracking.
            start_time: Start time for duration calculation.

        Returns:
            Wrapped async iterator that tracks usage metrics.
        """
