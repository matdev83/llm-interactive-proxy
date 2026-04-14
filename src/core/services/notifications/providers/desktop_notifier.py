"""Implementation of desktop notification provider using desktop-notifier."""

from __future__ import annotations

import logging
import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

try:
    from desktop_notifier import Button, DesktopNotifier

    has_desktop_notifier = True
except ImportError:
    Button = None  # type: ignore
    DesktopNotifier = None  # type: ignore
    has_desktop_notifier = False

from src.core.interfaces.notification_provider_interface import INotificationProvider

if TYPE_CHECKING:
    from desktop_notifier import Button as ButtonType
else:
    ButtonType = object  # type: ignore

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

    async def send(
        self,
        title: str,
        message: str,
        *,
        url: str | None = None,
        url_label: str = "Open link",
    ) -> str | None:
        """Deliver a desktop notification."""
        if not has_desktop_notifier:
            return None

        try:
            if self._notifier is None and DesktopNotifier is not None:
                self._notifier = DesktopNotifier(app_name="LLM Interactive Proxy")

            if self._notifier:
                buttons: tuple[ButtonType, ...] = ()
                on_clicked: Callable[[], object] | None = None
                if url and Button is not None:
                    buttons = (
                        Button(
                            title=url_label,
                            on_pressed=lambda: webbrowser.open(url, new=2),
                        ),
                    )
                    on_clicked = lambda: webbrowser.open(url, new=2)

                return cast(
                    str | None,
                    await self._notifier.send(
                        title=title,
                        message=message,
                        buttons=buttons,
                        on_clicked=on_clicked,
                    ),
                )
        except Exception as e:
            logger.warning("DesktopNotifierProvider failed to send notification: %s", e)

        return None
