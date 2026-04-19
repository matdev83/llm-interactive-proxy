"""Tests for disable_stale_acp_agent_kills (ACP idle process kill) configuration."""

from __future__ import annotations

from unittest.mock import patch

from src.core.cli import apply_cli_args, build_cli_parser, parse_cli_args
from src.core.config.app_config import AppConfig, load_config
from src.core.config.parameter_resolution import ParameterSource


def test_app_config_default_disable_stale_acp_agent_kills_is_false() -> None:
    cfg = AppConfig()
    assert cfg.disable_stale_acp_agent_kills is False


def test_app_config_default_stale_acp_agent_kill_idle_seconds() -> None:
    cfg = AppConfig()
    assert cfg.stale_acp_agent_kill_idle_seconds == 3600.0


def test_from_env_sets_stale_acp_agent_kill_idle_seconds() -> None:
    env = {"STALE_ACP_AGENT_KILL_IDLE_SECONDS": "120"}
    cfg = AppConfig.from_env(environ=env)
    assert cfg.stale_acp_agent_kill_idle_seconds == 120.0


def test_cli_sets_stale_acp_agent_kill_idle_seconds() -> None:
    with patch.dict("os.environ", {}, clear=True):
        args = parse_cli_args(["--stale-acp-agent-kill-idle-seconds", "90"])
        cfg = apply_cli_args(args)
    assert cfg.stale_acp_agent_kill_idle_seconds == 90.0


def test_from_env_sets_disable_stale_acp_agent_kills() -> None:
    env = {"DISABLE_STALE_ACP_AGENT_KILLS": "true"}
    cfg = AppConfig.from_env(environ=env)
    assert cfg.disable_stale_acp_agent_kills is True


def test_cli_flag_sets_disable_stale_acp_agent_kills() -> None:
    with patch.dict("os.environ", {}, clear=True):
        args = parse_cli_args(["--disable-stale-acp-agent-kills"])
        cfg = apply_cli_args(args)
    assert cfg.disable_stale_acp_agent_kills is True


def test_env_applies_when_cli_not_passed() -> None:
    env = {"DISABLE_STALE_ACP_AGENT_KILLS": "1"}
    with patch.dict("os.environ", env, clear=True):
        args = parse_cli_args([])
        cfg = apply_cli_args(args)
    assert cfg.disable_stale_acp_agent_kills is True


def test_parser_exposes_disable_stale_acp_agent_kills() -> None:
    parser = build_cli_parser()
    args = parser.parse_args(["--disable-stale-acp-agent-kills"])
    assert args.disable_stale_acp_agent_kills is True


def test_apply_cli_args_records_resolution_for_stale_acp_flag() -> None:
    with patch.dict("os.environ", {}, clear=True):
        args = parse_cli_args(["--disable-stale-acp-agent-kills"])
        _cfg, resolution = apply_cli_args(args, return_resolution=True)
    cli = resolution.latest_by_source(ParameterSource.CLI)
    assert "disable_stale_acp_agent_kills" in cli
    rec = cli["disable_stale_acp_agent_kills"]
    assert getattr(rec, "value", rec) is True


def test_load_config_merges_disable_stale_acp_agent_kills_from_env() -> None:
    cfg = load_config(
        None,
        environ={"DISABLE_STALE_ACP_AGENT_KILLS": "true"},
    )
    assert cfg.disable_stale_acp_agent_kills is True


def test_cli_overrides_env_false_stale_kills_enabled_via_cli() -> None:
    """Env requests disable; CLI does not pass --disable -> env wins."""
    merged = {"DISABLE_STALE_ACP_AGENT_KILLS": "true"}
    with patch.dict("os.environ", merged, clear=True):
        args = parse_cli_args([])
        cfg = apply_cli_args(args)
    assert cfg.disable_stale_acp_agent_kills is True


def test_cli_explicit_disable_overrides_env_off() -> None:
    """Env says feature on (false disable); CLI --disable sets True."""
    merged = {"DISABLE_STALE_ACP_AGENT_KILLS": "false"}
    with patch.dict("os.environ", merged, clear=True):
        args = parse_cli_args(["--disable-stale-acp-agent-kills"])
        cfg = apply_cli_args(args)
    assert cfg.disable_stale_acp_agent_kills is True
