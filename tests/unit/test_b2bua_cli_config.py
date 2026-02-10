from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
from src.core.cli import (
    _validate_b2bua_runtime_configuration,
    _warn_if_b2bua_unsafe_heuristic_inference_enabled,
    apply_cli_args,
    parse_cli_args,
)
from src.core.config.app_config import AppConfig, ParameterResolution


def _unwrap_config(
    result: AppConfig | tuple[AppConfig, ParameterResolution],
) -> AppConfig:
    return result[0] if isinstance(result, tuple) else result


def test_cli_applies_b2bua_overrides() -> None:
    with patch("src.core.cli.load_config", return_value=AppConfig()):
        args = parse_cli_args(
            [
                "--enable-b2bua-session-handling",
                "--b2bua-continuity-max-age-seconds",
                "777",
                "--b2bua-continuity-fixed-expiration",
                "--enable-b2bua-persistent-mapping-store",
                "--disable-b2bua-session-echo",
                "--b2bua-session-echo-header-name",
                "x-custom-a-session-id",
                "--enable-unsafe-legacy-session-inference",
                "--b2bua-deployment-mode",
                "multi-worker",
            ]
        )
        cfg = _unwrap_config(apply_cli_args(args))

    assert cfg.session.b2bua.enabled is True
    assert cfg.session.b2bua.continuity_max_age_seconds == 777
    assert cfg.session.b2bua.continuity_sliding_expiration is False
    assert cfg.session.b2bua.persistent_mapping_store_enabled is True
    assert cfg.session.b2bua.echo_enabled is False
    assert cfg.session.b2bua.echo_header_name == "x-custom-a-session-id"
    assert cfg.session.b2bua.enable_unsafe_heuristic_session_inference is True
    assert cfg.session.b2bua.deployment_mode == "multi-worker"


def test_cli_b2bua_cli_overrides_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SESSION_B2BUA_ENABLED", "false")

    args = parse_cli_args(["--enable-b2bua-session-handling"])
    cfg = _unwrap_config(apply_cli_args(args))

    assert cfg.session.b2bua.enabled is True


def test_cli_warns_when_unsafe_b2bua_inference_enabled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    cfg = AppConfig(
        {
            "session": {
                "b2bua": {
                    "enabled": True,
                    "enable_unsafe_heuristic_session_inference": True,
                }
            }
        }
    )

    with caplog.at_level(logging.WARNING):
        _warn_if_b2bua_unsafe_heuristic_inference_enabled(cfg)

    assert any(
        "session.b2bua.enable_unsafe_heuristic_session_inference=true" in rec.message
        for rec in caplog.records
    )


def test_validate_b2bua_runtime_configuration_rejects_multi_worker_without_persistence() -> (
    None
):
    cfg = AppConfig(
        {
            "session": {
                "b2bua": {
                    "enabled": True,
                    "deployment_mode": "multi-worker",
                    "persistent_mapping_store_enabled": False,
                }
            }
        }
    )

    with pytest.raises(
        ValueError, match="multi-worker mode requires persistent mapping store"
    ):
        _validate_b2bua_runtime_configuration(cfg)
