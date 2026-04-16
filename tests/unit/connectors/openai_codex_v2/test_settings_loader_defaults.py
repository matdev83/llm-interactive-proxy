"""Settings defaults for ``openai-codex-v2``."""

from __future__ import annotations

from src.connectors.openai_codex_v2.settings_loader import OpenAICodexV2SettingsLoader
from src.core.config.app_config import AppConfig, BackendConfig


def test_v2_defaults_enable_websocket_and_beta_v2() -> None:
    loader = OpenAICodexV2SettingsLoader()
    base = AppConfig()
    cfg = base.model_copy(
        update={
            "backends": base.backends.model_copy(
                update={"openai_codex_v2": BackendConfig()}
            )
        }
    )
    settings = loader.load(cfg)
    assert settings.websocket["enabled"] is True
    assert settings.websocket.get("beta_mode") == "v2"
