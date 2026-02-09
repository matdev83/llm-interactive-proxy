"""Access mode configuration model.

Provides configuration for proxy access modes: Single User Mode (default)
and Multi User Mode.
"""

from __future__ import annotations

from enum import Enum

from pydantic import ConfigDict, Field

from src.core.interfaces.model_bases import DomainModel


class AccessMode(str, Enum):
    """Proxy access mode enumeration."""

    SINGLE_USER = "single_user"  # Default: local development, OAuth allowed
    MULTI_USER = "multi_user"  # Production: shared deployment, OAuth blocked


class AccessModeConfig(DomainModel):
    """Access mode configuration.

    Controls the operational security posture of the proxy:
    - Single User Mode: Default mode for local development; allows OAuth connectors,
      optional authentication, localhost-only binding.
    - Multi User Mode: Production mode for shared deployments; blocks OAuth connectors,
      requires authentication for non-localhost, allows any IP binding.

    Default behavior:
    - Default mode is Single User Mode for backward compatibility
    - Mode is immutable after startup (no runtime switching)

    Attributes:
        mode: The access mode (single_user or multi_user). Defaults to SINGLE_USER.
    """

    model_config = ConfigDict(frozen=True)

    mode: AccessMode = Field(
        default=AccessMode.SINGLE_USER,
        description="Proxy access mode (single_user or multi_user)",
    )

    def is_single_user(self) -> bool:
        """Check if running in Single User Mode.

        Returns:
            True if mode is SINGLE_USER, False otherwise.
        """
        return self.mode == AccessMode.SINGLE_USER

    def is_multi_user(self) -> bool:
        """Check if running in Multi User Mode.

        Returns:
            True if mode is MULTI_USER, False otherwise.
        """
        return self.mode == AccessMode.MULTI_USER
