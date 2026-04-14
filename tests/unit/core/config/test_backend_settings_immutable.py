"""Tests for frozen BackendSettings aggregate."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from src.core.config.models.backends import BackendConfig, BackendSettings


def test_backend_settings_is_frozen() -> None:
    b = BackendSettings()
    with pytest.raises(ValidationError):
        b.default_backend = "other"  # type: ignore[misc]


def test_backend_settings_setitem_raises() -> None:
    b = BackendSettings()
    with pytest.raises(TypeError, match="immutable"):
        b["openai"] = BackendConfig(api_key="x")


def test_get_named_backend_configs_returns_extras() -> None:
    b = BackendSettings(openai=BackendConfig(api_key="k"))
    names = b.get_named_backend_configs()
    assert "openai" in names
    assert names["openai"].api_key == "k"


def test_model_copy_updates_backend_entry() -> None:
    b = BackendSettings()
    b2 = b.model_copy(update={"openai": BackendConfig(api_key="z")})
    assert b2.get_named_backend_configs()["openai"].api_key == "z"
