"""Usage payload models.

This module defines the UsagePayload model for protocol-specific usage payloads.
"""

from __future__ import annotations

from pydantic import Field
from pydantic.types import JsonValue

from src.core.interfaces.model_bases import DomainModel


class UsagePayload(DomainModel):
    """Protocol-specific usage payload container."""

    payload: dict[str, JsonValue] = Field(..., description="Usage payload dictionary")
