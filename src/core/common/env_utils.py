"""Utility helpers for environment-driven feature flags."""

from __future__ import annotations

import os

_TRUE_VALUES = {"1", "true", "yes", "on"}


def get_env_flag(name: str, default: bool) -> bool:
    """Return a boolean flag sourced from the environment."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES
