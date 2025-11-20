from __future__ import annotations

from typing import cast

from src.core.cli import apply_cli_args, build_cli_parser, parse_cli_args
from src.core.config.app_config import AppConfig, SessionConfig


def test_env_parses_angel_model(monkeypatch) -> None:
    monkeypatch.setenv("ANGEL_MODEL", "openai:gpt-4o-mini?temperature=1")
    cfg = AppConfig.from_env()
    assert cfg.session.angel_model == "openai:gpt-4o-mini?temperature=1"


def test_cli_parses_angel_model(tmp_path) -> None:
    parser = build_cli_parser()
    args = parser.parse_args(
        [
            "--command-prefix",
            "!/",
            "--use-angel-model",
            "anthropic:claude-3-5-sonnet?temperature=1",
        ]
    )
    result = apply_cli_args(args, return_resolution=True)
    if isinstance(result, tuple):
        cfg = cast(AppConfig, result[0])
    else:
        cfg = cast(AppConfig, result)
    assert cfg.session.angel_model == "anthropic:claude-3-5-sonnet?temperature=1"


def test_cli_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("ANGEL_MODEL", "openai:gpt-4o-mini?temperature=0.5")
    args = parse_cli_args(
        [
            "--command-prefix",
            "!/",
            "--use-angel-model",
            "openrouter:gpt-4?temperature=1",
        ]
    )
    result = apply_cli_args(args, return_resolution=True)
    if isinstance(result, tuple):
        cfg = cast(AppConfig, result[0])
    else:
        cfg = cast(AppConfig, result)
    assert cfg.session.angel_model == "openrouter:gpt-4?temperature=1"


def test_config_file_value_is_loaded() -> None:
    cfg = AppConfig(session=SessionConfig(angel_model="anthropic:claude-3-5-sonnet"))
    assert cfg.session.angel_model == "anthropic:claude-3-5-sonnet"


def test_env_parses_angel_frequency(monkeypatch) -> None:
    monkeypatch.setenv("ANGEL_FREQUENCY", "5")
    cfg = AppConfig.from_env()
    assert cfg.session.angel_frequency == 5


def test_cli_sets_angel_frequency() -> None:
    parser = build_cli_parser()
    args = parser.parse_args(["--command-prefix", "!/", "--angel-frequency", "7"])
    result = apply_cli_args(args, return_resolution=True)
    cfg = cast(AppConfig, result[0] if isinstance(result, tuple) else result)
    assert cfg.session.angel_frequency == 7


def test_angel_frequency_defaults_to_one() -> None:
    cfg = AppConfig()
    assert cfg.session.angel_frequency == 1
