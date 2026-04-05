from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.domain.cbor_capture import CapturedWireEvent


class IWireCaptureRecorder(ABC):
    """Canonical low-level recorder for CBOR V2 wire capture events."""

    @abstractmethod
    async def capture_event(self, event: CapturedWireEvent) -> None:
        """Record a fully materialized low-level capture event."""
