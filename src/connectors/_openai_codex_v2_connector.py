"""OpenAI Codex websocket v2 experimental connector (parallel to ``openai-codex``)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from src.connectors._openai_codex_connector import OpenAICodexConnector
from src.connectors.openai_codex.contracts import CodexConnectorDependencies
from src.connectors.openai_codex.executor import ResponseExecutor
from src.connectors.openai_codex.gpt55_account_compatibility import (
    gpt55_config_from_mapping,
)
from src.connectors.openai_codex_v2.settings_loader import OpenAICodexV2SettingsLoader
from src.connectors.openai_codex_v2.ws_lineage import CodexWebsocketV2Lineage
from src.core.config.app_config import AppConfig
from src.core.services.backend_registry import backend_registry
from src.core.services.translation_service import TranslationService


class OpenAICodexV2Connector(OpenAICodexConnector):
    """Codex connector using managed OAuth with websocket v2 + strict delta lineage.

    Inherits the auto-discovered Codex model catalog and reasoning-effort
    behavior from :class:`OpenAICodexConnector` (resolved per-instance via DI,
    else the shipped fallback snapshot). No model slugs are hardcoded here.
    """

    backend_type: str = "openai-codex-v2"

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AppConfig,
        response_processor: Any | None = None,
        translation_service: TranslationService | None = None,
        dependencies: CodexConnectorDependencies | None = None,
    ) -> None:
        fixed_deps = dependencies
        if fixed_deps is None:
            fixed_deps = CodexConnectorDependencies(
                settings_loader=OpenAICodexV2SettingsLoader()
            )
        elif fixed_deps.settings_loader is None:
            fixed_deps = replace(
                fixed_deps, settings_loader=OpenAICodexV2SettingsLoader()
            )
        super().__init__(
            client=client,
            config=config,
            response_processor=response_processor,
            translation_service=translation_service,
            dependencies=fixed_deps,
        )
        self.name = "openai-codex-v2"

    def _create_default_response_executor(
        self,
        *,
        max_retries: int,
        retry_backoff_seconds: tuple[float, ...],
    ) -> ResponseExecutor:
        websocket_cfg = self._connector_settings.get("websocket", {})
        use_websocket = bool(websocket_cfg.get("enabled", False))
        ws_beta = str(websocket_cfg.get("beta_mode") or "v2").strip().lower()
        if ws_beta not in ("v1", "v2"):
            ws_beta = "v2"
        gpt55_cfg = gpt55_config_from_mapping(
            self._connector_settings.get("gpt55_unsupported_free_plan_downgrade")
        )
        lineage = CodexWebsocketV2Lineage(self._continuation_coordinator)
        return ResponseExecutor(
            base_connector=self,
            credential_manager=self._credential_manager,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            compatibility_layer=self._compatibility_layer,
            continuation_coordinator=self._continuation_coordinator,
            use_websocket=use_websocket,
            websocket_beta_mode=ws_beta,
            connector_transport_backend=self.backend_type,
            continuation_backend_label=self.backend_type,
            codex_ws_lineage=lineage,
            preserve_tools_on_managed_ws_continuation=True,
            gpt55_free_plan_downgrade=gpt55_cfg,
        )


backend_registry.register_backend("openai-codex-v2", OpenAICodexV2Connector)
