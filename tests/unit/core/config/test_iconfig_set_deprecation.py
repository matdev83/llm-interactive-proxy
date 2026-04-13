"""Tests for IConfig.set() deprecation behavior."""

from __future__ import annotations

import warnings

import pytest
from pydantic import ValidationError
from src.core.config.app_config import AppConfig
from src.core.config.models.app_config_model import AppConfigModel


def test_app_config_set_emits_deprecation_warning() -> None:
    """AppConfig.set() should emit a DeprecationWarning."""
    cfg = AppConfig()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        cfg.set("host", "0.0.0.0")

    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)
    assert (
        "IConfig.set" in str(caught[0].message)
        or "deprecated" in str(caught[0].message).lower()
    )

    # Value should still be set for backward compatibility
    assert cfg.host == "0.0.0.0"


def test_app_config_model_set_emits_deprecation_warning() -> None:
    """AppConfigModel.set() should emit a DeprecationWarning."""
    cfg = AppConfigModel()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # AppConfigModel is frozen, so set() will emit warning then raise
        with pytest.raises(ValidationError):
            cfg.set("host", "0.0.0.0")

    assert len(caught) == 1
    assert issubclass(caught[0].category, DeprecationWarning)


def test_app_config_set_still_works_for_backward_compatibility() -> None:
    """AppConfig.set() should still modify values despite deprecation."""
    cfg = AppConfig()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        cfg.set("command_prefix", "$/")
        cfg.set("port", 9000)

    assert cfg.command_prefix == "$/"
    assert cfg.port == 9000
