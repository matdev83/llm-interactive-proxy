"""CLI and config wiring for streaming loop detection (opt-in)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from src.core.cli import apply_cli_args, parse_cli_args
from src.core.config.app_config import AppConfig, load_config


def test_parse_cli_args_accepts_enable_loop_detection() -> None:
    args = parse_cli_args(["--enable-loop-detection"])
    assert args.enable_loop_detection is True


def test_load_config_default_streaming_loop_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOOP_DETECTION_ENABLED", raising=False)
    cfg = load_config(None, environ=dict(os.environ))
    assert cfg.session.streaming_loop_detection_enabled is False


def test_load_config_enables_streaming_when_env_true(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOOP_DETECTION_ENABLED", "true")
    cfg = load_config(None, environ=dict(os.environ))
    assert cfg.session.streaming_loop_detection_enabled is True


def test_load_config_disables_streaming_when_env_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOOP_DETECTION_ENABLED", "false")
    cfg = load_config(None, environ=dict(os.environ))
    assert cfg.session.streaming_loop_detection_enabled is False


def test_apply_cli_args_enable_loop_detection_sets_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOOP_DETECTION_ENABLED", raising=False)
    with patch("src.core.cli.load_config", return_value=AppConfig()):
        cfg = apply_cli_args(parse_cli_args(["--enable-loop-detection"]))
    assert cfg.session.streaming_loop_detection_enabled is True
