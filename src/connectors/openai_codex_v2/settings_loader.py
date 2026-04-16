"""Settings loader for the experimental ``openai-codex-v2`` backend."""

from __future__ import annotations

from src.connectors.openai_codex.settings import SettingsLoader


class OpenAICodexV2SettingsLoader(SettingsLoader):
    """Loads ``backends.openai_codex_v2`` / ``openai-codex-v2`` with WS v2 defaults."""

    def __init__(self) -> None:
        super().__init__(
            backend_yaml_attr="openai_codex_v2",
            backend_registry_lookup="openai-codex-v2",
            default_websocket_enabled=True,
            default_websocket_beta_mode="v2",
        )
