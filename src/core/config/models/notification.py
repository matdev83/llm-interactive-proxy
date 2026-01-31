"""Notification configuration model.

Provides configuration for OS notification system.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NotificationConfig(BaseModel):
    """Configuration for OS notifications.

    Controls whether desktop notifications are enabled globally across the proxy.

    Default behavior:
    - Enabled when proxy binds to localhost (127.0.0.1)
    - Disabled when proxy binds to any other interface

    Priority (highest to lowest):
    1. CLI flag (--enable-notifications / --disable-notifications)
    2. Environment variable (LLM_PROXY_ENABLE_NOTIFICATIONS)
    3. Config file entry (notifications.enabled)
    4. Default based on bind address
    """

    enabled: bool | None = Field(
        default=None,
        description="Whether desktop notifications are enabled. None means auto-detect based on bind address.",
    )

    def is_enabled(self, host: str) -> bool:
        """Determine if notifications should be enabled.

        If enabled is explicitly set (not None), return that value.
        Otherwise, enable only for localhost bindings.

        Args:
            host: The host address the proxy is bound to

        Returns:
            True if notifications should be enabled, False otherwise
        """
        if self.enabled is not None:
            return self.enabled

        # Default: enable for localhost only
        localhost_addresses = {"127.0.0.1", "localhost", "::1"}
        return host in localhost_addresses
