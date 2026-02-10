from __future__ import annotations

from pathlib import Path

from src.core.config.app_config import AppConfig, load_config
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def test_b2bua_defaults_are_safe() -> None:
    cfg = AppConfig()

    assert cfg.session.b2bua.enabled is False
    assert cfg.session.b2bua.continuity_max_age_seconds == 3600
    assert cfg.session.b2bua.continuity_sliding_expiration is True
    assert cfg.session.b2bua.persistent_mapping_store_enabled is False
    assert cfg.session.b2bua.echo_enabled is True
    assert cfg.session.b2bua.echo_header_name == "x-b2bua-session-id"
    assert cfg.session.b2bua.enable_unsafe_heuristic_session_inference is False
    assert cfg.session.b2bua.deployment_mode == "single-process"


def test_b2bua_env_settings_are_loaded_and_tracked() -> None:
    env = {
        "SESSION_B2BUA_ENABLED": "true",
        "SESSION_B2BUA_CONTINUITY_MAX_AGE_SECONDS": "900",
        "SESSION_B2BUA_CONTINUITY_SLIDING_EXPIRATION": "false",
        "SESSION_B2BUA_PERSISTENT_MAPPING_STORE_ENABLED": "true",
        "SESSION_B2BUA_ECHO_ENABLED": "false",
        "SESSION_B2BUA_ECHO_HEADER_NAME": "x-custom-a-session-id",
        "SESSION_B2BUA_ENABLE_UNSAFE_HEURISTIC_SESSION_INFERENCE": "true",
        "SESSION_B2BUA_DEPLOYMENT_MODE": "multi-worker",
    }

    resolution = ParameterResolution()
    cfg = load_config(None, environ=env, resolution=resolution)

    assert cfg.session.b2bua.enabled is True
    assert cfg.session.b2bua.continuity_max_age_seconds == 900
    assert cfg.session.b2bua.continuity_sliding_expiration is False
    assert cfg.session.b2bua.persistent_mapping_store_enabled is True
    assert cfg.session.b2bua.echo_enabled is False
    assert cfg.session.b2bua.echo_header_name == "x-custom-a-session-id"
    assert cfg.session.b2bua.enable_unsafe_heuristic_session_inference is True
    assert cfg.session.b2bua.deployment_mode == "multi-worker"

    report = {entry.name: entry for entry in resolution.build_report(cfg)}
    assert report["session.b2bua.enabled"].source is ParameterSource.ENVIRONMENT
    assert (
        report["session.b2bua.persistent_mapping_store_enabled"].source
        is ParameterSource.ENVIRONMENT
    )


def test_b2bua_environment_overrides_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "\n".join(
            [
                "session:",
                "  b2bua:",
                "    enabled: false",
                "    continuity_max_age_seconds: 42",
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_config(
        cfg_path,
        environ={
            "SESSION_B2BUA_ENABLED": "true",
            "SESSION_B2BUA_CONTINUITY_MAX_AGE_SECONDS": "900",
        },
    )

    assert cfg.session.b2bua.enabled is True
    assert cfg.session.b2bua.continuity_max_age_seconds == 900
