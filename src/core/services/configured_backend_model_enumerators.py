"""Startup-safe model sources for configured local-agent backend instances."""

from __future__ import annotations

from typing import Any

from src.connectors.base import add_vendor_prefix
from src.core.common.model_catalog import BackendModelEnumeration
from src.core.config.app_config import BackendConfig


class ExplicitConfiguredModelEnumerator:
    """Treat an instance's explicit ``models`` list as its complete catalog."""

    def __init__(self, *, connector: str, source: str = "configured") -> None:
        self._connector = connector
        self._source = source

    async def enumerate(
        self, instance_name: str, config: BackendConfig
    ) -> BackendModelEnumeration:
        models = [str(model).strip() for model in config.models if str(model).strip()]
        if not models:
            return BackendModelEnumeration.unavailable(
                instance_name=instance_name,
                connector=self._connector,
                source=self._source,
                error_code="models_not_configured",
                instance_pinned=True,
            )
        return BackendModelEnumeration.available(
            instance_name=instance_name,
            connector=self._connector,
            models=models,
            source=self._source,
            instance_pinned=True,
        )


class CodexAppServerConfiguredModelEnumerator:
    """Project the shared startup Codex catalog onto an App Server instance."""

    def __init__(self, *, catalog: Any, catalog_source: str) -> None:
        self._catalog = catalog
        self._catalog_source = catalog_source

    async def enumerate(
        self, instance_name: str, config: BackendConfig
    ) -> BackendModelEnumeration:
        del config
        models = ["openai/auto"]
        if self._catalog_source == "discovery":
            models.extend(
                add_vendor_prefix(str(slug), "openai")
                for slug in self._catalog.routable_slugs()
            )
        return BackendModelEnumeration.available(
            instance_name=instance_name,
            connector="openai-codex-app-server",
            models=models,
            source=f"codex_{self._catalog_source}",
            instance_pinned=True,
        )


__all__ = [
    "CodexAppServerConfiguredModelEnumerator",
    "ExplicitConfiguredModelEnumerator",
]
