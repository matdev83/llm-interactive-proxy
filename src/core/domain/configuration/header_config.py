from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from src.core.domain.base import ValueObject


class HeaderOverrideMode(str, Enum):
    """Enum for header override modes."""

    DEFAULT = "default"
    PASSTHROUGH = "passthrough"
    OVERRIDE = "override"


class HeaderConfig(ValueObject):
    """Configuration for a single header, handling override and pass-through logic."""

    mode: HeaderOverrideMode = Field(
        default=HeaderOverrideMode.PASSTHROUGH,
        description="The mode for handling the header.",
    )
    override_value: str | None = Field(
        default=None,
        description="The override value for the header.",
    )
    default_value: str = Field(
        "",
        description="The default value for the header.",
    )
    passthrough_name: str = Field(
        "",
        description="The name of the header to look for in incoming requests for pass-through.",
    )

    def resolve_value(self, incoming_headers: dict[str, Any] | None) -> str:
        """Resolve the final header value based on the configuration."""
        if self.mode == HeaderOverrideMode.OVERRIDE and self.override_value is not None:
            return self.override_value

        if (
            self.mode == HeaderOverrideMode.PASSTHROUGH
            and incoming_headers
            and self.passthrough_name in incoming_headers
        ):
            value = incoming_headers[self.passthrough_name]
            if isinstance(value, str):
                return value

        return self.default_value
