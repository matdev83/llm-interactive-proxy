"""Tests for the legacy ``src.core.cli_v2`` compatibility layer."""

from __future__ import annotations

import os
import socket

import pytest

from src.core.cli_v2 import AppConfig, apply_cli_args, is_port_in_use, parse_cli_args
from src.core.cli_v2 import main as cli_main
from src.core.config.app_config import ModelAliasRule


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment variables modified by the CLI are reset."""

    for key in {
        "PROXY_PORT",
        "COMMAND_PREFIX",
        "FORCE_CONTEXT_WINDOW",
        "THINKING_BUDGET",
        "LLM_BACKEND",
    }:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def backend_choices(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Provide a deterministic set of backends for CLI parsing."""

    choices = ["openai", "gemini"]
    from src.core import cli as cli_module

    monkeypatch.setattr(
        cli_module.backend_registry,
        "get_registered_backends",
        lambda: list(choices),
    )
    return choices


def test_parse_cli_args_accepts_model_alias(backend_choices: list[str]) -> None:
    args = parse_cli_args(
        [
            "--default-backend",
            backend_choices[0],
            "--model-alias",
            r"^gpt-(.*)=openrouter:openai/gpt-\\1",
        ]
    )

    assert args.default_backend == backend_choices[0]
    assert args.model_aliases == [
        (r"^gpt-(.*)", r"openrouter:openai/gpt-\\1")
    ], "Model alias should be parsed into pattern/replacement tuples"


def test_parse_cli_args_rejects_invalid_model_alias(backend_choices: list[str]) -> None:
    with pytest.raises(SystemExit):
        parse_cli_args([
            "--default-backend",
            backend_choices[0],
            "--model-alias",
            "invalid-alias",
        ])


def test_apply_cli_args_updates_configuration(monkeypatch: pytest.MonkeyPatch, backend_choices: list[str], tmp_path) -> None:
    log_file = tmp_path / "proxy.log"
    args = parse_cli_args(
        [
            "--default-backend",
            backend_choices[0],
            "--port",
            "9999",
            "--command-prefix",
            "@!",
            "--force-context-window",
            "4096",
            "--thinking-budget",
            "123",
            "--log",
            str(log_file),
            "--model-alias",
            r"^gpt-(.*)=openrouter:openai/gpt-\\1",
        ]
    )

    config = apply_cli_args(args)

    assert isinstance(config, AppConfig)
    assert config.port == 9999
    assert config.command_prefix == "@!"
    assert config.context_window_override == 4096
    assert config.logging.log_file == str(log_file)
    assert config.backends.default_backend == backend_choices[0]
    assert os.environ["PROXY_PORT"] == "9999"
    assert os.environ["COMMAND_PREFIX"] == "@!"
    assert os.environ["FORCE_CONTEXT_WINDOW"] == "4096"
    assert os.environ["THINKING_BUDGET"] == "123"
    assert os.environ["LLM_BACKEND"] == backend_choices[0]
    assert [
        (alias.pattern, alias.replacement)
        for alias in config.model_aliases
    ] == [(r"^gpt-(.*)", r"openrouter:openai/gpt-\\1")]
    assert all(isinstance(alias, ModelAliasRule) for alias in config.model_aliases)


def test_is_port_in_use_detects_bound_socket() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        host, port = listener.getsockname()
        assert is_port_in_use(host, port)

    assert not is_port_in_use(host, port)


def test_main_delegates_to_cli(monkeypatch: pytest.MonkeyPatch, backend_choices: list[str]) -> None:
    called = {}

    def fake_main(*, argv, build_app_fn):
        called["argv"] = argv
        called["build_app_fn"] = build_app_fn

    monkeypatch.setattr("src.core.cli.main", fake_main)
    cli_main(argv=["--default-backend", backend_choices[0]], build_app_fn=None)

    assert called == {
        "argv": ["--default-backend", backend_choices[0]],
        "build_app_fn": None,
    }
