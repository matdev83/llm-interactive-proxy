"""Implementation of desktop notification provider using desktop-notifier."""

from __future__ import annotations

import logging
from typing import Any, cast

try:
    from desktop_notifier import DesktopNotifier

    has_desktop_notifier = True
except ImportError:
    DesktopNotifier = None  # type: ignore
    has_desktop_notifier = False

from src.core.interfaces.notification_provider_interface import INotificationProvider

logger = logging.getLogger(__name__)


class DesktopNotifierProvider(INotificationProvider):
    """Notification provider using the desktop-notifier library."""

    def __init__(self) -> None:
        self._notifier: Any = None
        if not has_desktop_notifier:
            logger.debug(
                "DesktopNotifierProvider initialized but 'desktop-notifier' "
                "package is not installed."
            )

    async def send(self, title: str, message: str) -> str | None:
        """Deliver a desktop notification."""
        if not has_desktop_notifier:
            return None

        try:
            if self._notifier is None and DesktopNotifier is not None:
                self._notifier = DesktopNotifier()

            if self._notifier:
                return cast(str | None, await self._notifier.send(title=title, message=message))
        except Exception as e:
            logger.debug("DesktopNotifierProvider failed to send: %s", e)

        return None
