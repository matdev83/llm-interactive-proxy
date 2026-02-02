"""Interface for notification delivery providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class INotificationProvider(ABC):
    """Low-level interface for delivering notifications."""

    @abstractmethod
    async def send(self, title: str, message: str) -> str | None:
        """Deliver a notification.

        Args:
            title: The notification title.
            message: The notification body text.

        Returns:
            Provider-specific notification ID if successful, None otherwise.
        """
        pass
