"""Configuration for scheduled sliding usage window warm-up requests."""

from __future__ import annotations

import re

from pydantic import ConfigDict, Field, field_validator

from src.core.domain.model_utils import (
    has_explicit_backend_selector,
    parse_model_backend,
)
from src.core.interfaces.model_bases import DomainModel

_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class UsageWindowWarmupEntryConfig(DomainModel):
    """Single scheduled warm-up entry for a concrete backend:model route."""

    model_config = ConfigDict(frozen=True)

    model: str = Field(...)
    time: str = Field(...)
    execute_on_weekend: bool = False

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("usage window warm-up model must be provided")
        if "^" in trimmed or "|" in trimmed:
            raise ValueError(
                "usage window warm-up model cannot use composite routing operators"
            )
        if not has_explicit_backend_selector(trimmed):
            raise ValueError(
                "usage window warm-up model must use an explicit backend:model route"
            )

        parsed = parse_model_backend(trimmed)
        if not parsed.backend_type.strip() or not parsed.model_name.strip():
            raise ValueError(
                "usage window warm-up model must include a non-empty backend and model"
            )
        return trimmed

    @field_validator("time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        trimmed = value.strip()
        if not _TIME_PATTERN.fullmatch(trimmed):
            raise ValueError("usage window warm-up time must use HH:MM 24-hour format")
        return trimmed


class UsageWindowWarmupConfig(DomainModel):
    """Top-level warm-up scheduler configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    entries: list[UsageWindowWarmupEntryConfig] = Field(default_factory=list)


DEFAULT_USAGE_WINDOW_WARMUP_CONFIG = UsageWindowWarmupConfig()


__all__ = [
    "DEFAULT_USAGE_WINDOW_WARMUP_CONFIG",
    "UsageWindowWarmupConfig",
    "UsageWindowWarmupEntryConfig",
]
