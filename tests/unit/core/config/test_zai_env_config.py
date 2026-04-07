from __future__ import annotations

from unittest.mock import patch

from src.core.config.app_config import AppConfig


def test_zai_api_key_applies_to_both_zai_backends() -> None:
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        return_value=("val-zai", "process"),
    ):
        config = AppConfig.from_env(environ={"ZAI_API_KEY": "val-zai"})

    zai_cfg = config.backends.lookup("zai")
    coding_plan_cfg = config.backends.lookup("zai-coding-plan")

    assert zai_cfg is not None
    assert coding_plan_cfg is not None
    assert zai_cfg.api_key == "val-zai"
    assert coding_plan_cfg.api_key == "val-zai"


def test_zai_env_config_prefers_windows_persistent_value_when_process_is_stale() -> (
    None
):
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        return_value=("fresh-zai-key", "windows-user"),
    ):
        config = AppConfig.from_env(environ={"ZAI_API_KEY": "stale-zai-key"})

    zai_cfg = config.backends.lookup("zai")
    coding_plan_cfg = config.backends.lookup("zai-coding-plan")

    assert zai_cfg is not None
    assert coding_plan_cfg is not None
    assert zai_cfg.api_key == "fresh-zai-key"
    assert coding_plan_cfg.api_key == "fresh-zai-key"


def test_zai_env_config_preserves_base_url_and_timeout_overrides() -> None:
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        return_value=("val-zai", "process"),
    ):
        config = AppConfig.from_env(
            environ={
                "ZAI_API_KEY": "val-zai",
                "ZAI_API_BASE_URL": "https://example.invalid/zai/v4",
                "ZAI_TIMEOUT": "77",
            }
        )

    zai_cfg = config.backends.lookup("zai")

    assert zai_cfg is not None
    assert zai_cfg.api_url == "https://example.invalid/zai/v4"
    assert zai_cfg.timeout == 77


def test_zai_env_config_does_not_populate_keys_when_missing() -> None:
    with patch(
        "src.core.config.env.from_env_part3.get_env_value_with_windows_persistent_fallback",
        return_value=(None, "missing"),
    ):
        config = AppConfig.from_env(environ={})

    zai_cfg = config.backends.lookup("zai")
    coding_plan_cfg = config.backends.lookup("zai-coding-plan")

    assert zai_cfg is not None
    assert coding_plan_cfg is not None
    assert zai_cfg.api_key is None
    assert coding_plan_cfg.api_key is None
