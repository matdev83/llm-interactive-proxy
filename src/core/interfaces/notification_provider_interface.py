"""Interface for notification delivery providers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class INotificationProvider(ABC):
    """Low-level interface for delivering notifications."""

    @abstractmethod
    async def send(
        self,
        title: str,
        message: str,
        *,
        url: str | None = None,
        url_label: str = "Open link",
    ) -> str | None:
        """Deliver a notification.

        Args:
            title: The notification title.
            message: The notification body text.
            url: Optional URL to open when clicking the notification or an action button.
            url_label: Optional label for the URL action button.

        Returns:
            Provider-specific notification ID if successful, None otherwise.
        """
