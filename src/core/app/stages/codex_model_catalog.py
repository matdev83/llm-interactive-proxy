"""Startup stage: discover the Codex model catalog and register it in DI.

Runs ``codex debug models`` at startup (via
:class:`src.connectors.openai_codex.catalog.provider.CodexModelCatalogProvider`)
and registers the resolved :class:`ICodexModelCatalog` as a DI singleton shared
by the ``openai-codex``, ``openai-codex-v2`` and ``openai-codex-app-server``
connectors. On any discovery failure the provider falls back to the shipped
snapshot; if that also fails, the stage logs and leaves registration absent
(connectors then fall back to their own shipped-file load).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, cast

from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection

if TYPE_CHECKING:
    from src.connectors.openai_codex.catalog.config import CodexModelCatalogConfig

logger = logging.getLogger(__name__)

# Backend config attributes that may carry an ``extra.codex.model_catalog``
# section. The first one found wins; the app-server variant consumes the shared
# catalog and does not contribute discovery config.
_CODEX_CONFIG_BACKEND_ATTRS = ("openai_codex", "openai_codex_v2")


def resolve_codex_model_catalog_config(
    config: AppConfig,
) -> CodexModelCatalogConfig:
    """Resolve the catalog config from the first codex backend that defines it.

    Returns ``DEFAULT_CODEX_MODEL_CATALOG_CONFIG`` when no backend provides a
    ``model_catalog`` section.
    """
    from src.connectors.openai_codex.catalog.config import (
        DEFAULT_CODEX_MODEL_CATALOG_CONFIG,
        codex_model_catalog_config_from_mapping,
    )
    from src.connectors.openai_codex.utils import to_mapping

    backends = getattr(config, "backends", None)
    for attr in _CODEX_CONFIG_BACKEND_ATTRS:
        backend = _get_backend(backends, attr)
        if backend is None:
            continue
        extra = getattr(backend, "extra", None)
        if not isinstance(extra, Mapping):
            continue
        codex = extra.get("codex")
        if not isinstance(codex, Mapping):
            continue
        model_catalog = codex.get("model_catalog")
        if model_catalog is None:
            continue
        return codex_model_catalog_config_from_mapping(to_mapping(model_catalog))
    return DEFAULT_CODEX_MODEL_CATALOG_CONFIG


def _get_backend(backends: Any, attr: str) -> Any:
    if backends is None:
        return None
    backend = getattr(backends, attr, None)
    if backend is not None:
        return backend
    lookup = getattr(backends, "lookup", None)
    if callable(lookup):
        try:
            return lookup(attr.replace("_", "-"))
        except Exception as exc:  # - lookup is best-effort
            logger.debug("backends.lookup(%s) failed: %s", attr, exc)
            return None
    return None


class CodexModelCatalogStage(InitializationStage):
    """Discover and register the Codex model catalog at startup."""

    @property
    def name(self) -> str:
        return "codex_model_catalog"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        from src.connectors.openai_codex.catalog.interfaces import ICodexModelCatalog
        from src.connectors.openai_codex.catalog.provider import (
            CodexModelCatalogProvider,
        )

        catalog_config = resolve_codex_model_catalog_config(config)
        provider = CodexModelCatalogProvider(config=catalog_config)
        try:
            await provider.load()
        except Exception as exc:  # - never fail startup over catalog
            logger.error(
                "Codex model catalog load failed; connectors will lazy-load "
                "the shipped fallback. Error: %s",
                exc,
                exc_info=True,
            )
            return

        try:
            catalog = provider.get_catalog()
        except RuntimeError:
            return

        services.add_instance(cast(type[Any], ICodexModelCatalog), catalog)
        services.add_instance(CodexModelCatalogProvider, provider)
        logger.info(
            "Codex model catalog registered (%d routable models).",
            len(catalog.routable_slugs()),
        )
