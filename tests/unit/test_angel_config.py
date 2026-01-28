from __future__ import annotations

from src.core.cli import apply_cli_args, build_cli_parser, parse_cli_args
from src.core.config.app_config import AppConfig, SessionConfig


def test_env_parses_angel_model(monkeypatch) -> None:
    monkeypatch.setenv("ANGEL_MODEL", "openai:gpt-4o-mini?temperature=1")
    cfg = AppConfig.from_env()
    assert cfg.session.angel_model == "openai:gpt-4o-mini?temperature=1"


def test_cli_parses_angel_model() -> None:
    parser = build_cli_parser()
    args = parser.parse_args(
        [
            "--command-prefix",
            "!/",
            "--use-angel-model",
            "anthropic:claude-3-5-sonnet?temperature=1",
        ]
    )
    cfg, _ = apply_cli_args(args, return_resolution=True)
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
    cfg, _ = apply_cli_args(args, return_resolution=True)
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
    cfg, _ = apply_cli_args(args, return_resolution=True)
    assert cfg.session.angel_frequency == 7


def test_angel_frequency_defaults_to_ten() -> None:
    cfg = AppConfig()
    assert cfg.session.angel_frequency == 10


def test_env_parses_angel_max_history(monkeypatch) -> None:
    monkeypatch.setenv("ANGEL_MAX_HISTORY", "12")
    cfg = AppConfig.from_env()
    assert cfg.session.angel_max_history == 12


def test_cli_sets_angel_max_history() -> None:
    parser = build_cli_parser()
    args = parser.parse_args(["--command-prefix", "!/", "--angel-max-history", "9"])
    cfg, _ = apply_cli_args(args, return_resolution=True)
    assert cfg.session.angel_max_history == 9
