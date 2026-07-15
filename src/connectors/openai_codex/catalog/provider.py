"""Catalog provider.

Orchestrates discovery (``codex debug models``) -> fallback (shipped snapshot)
and caches the resolved catalog. Connectors resolve the catalog through DI
(:class:`ICodexModelCatalog`) rather than constructing this provider directly.
"""

from __future__ import annotations

import logging

from src.connectors.openai_codex.catalog.config import CodexModelCatalogConfig
from src.connectors.openai_codex.catalog.discovery_service import (
    CodexCatalogDiscoveryService,
)
from src.connectors.openai_codex.catalog.fallback_loader import (
    CodexCatalogFallbackLoader,
)
from src.connectors.openai_codex.catalog.interfaces import (
    ICodexCatalogDiscoveryService,
    ICodexCatalogFallbackLoader,
)
from src.connectors.openai_codex.catalog.types import CodexModelCatalog

logger = logging.getLogger(__name__)


class CodexModelCatalogProvider:
    """Resolve the Codex model catalog via discovery, falling back to a snapshot."""

    def __init__(
        self,
        *,
        config: CodexModelCatalogConfig,
        fallback_loader: ICodexCatalogFallbackLoader | None = None,
        discovery_service: ICodexCatalogDiscoveryService | None = None,
    ) -> None:
        self._config = config
        self._fallback_loader = (
            fallback_loader
            if fallback_loader is not None
            else CodexCatalogFallbackLoader(fallback_path=config.fallback_path)
        )
        self._discovery_service = (
            discovery_service
            if discovery_service is not None
            else CodexCatalogDiscoveryService(
                codex_binary_path=config.codex_binary_path,
                timeout_seconds=config.discovery_timeout_seconds,
            )
        )
        self._catalog: CodexModelCatalog | None = None
        self._catalog_source: str | None = None

    async def load(self) -> None:
        """Eagerly resolve the catalog (discovery, else fallback) and cache it.

        Idempotent: subsequent calls return without re-running discovery.
        """
        if self._catalog is not None:
            return
        if self._config.discovery_enabled:
            try:
                discovered = await self._discovery_service.discover()
            except Exception as exc:  # - fall back on any discovery failure
                logger.warning(
                    "Codex catalog discovery raised: %s; falling back to snapshot.",
                    exc,
                    exc_info=True,
                )
                discovered = None
            if discovered is not None:
                logger.info(
                    "Codex model catalog loaded via discovery (%d routable models).",
                    len(discovered.routable_slugs()),
                )
                self._catalog = discovered
                self._catalog_source = "discovery"
                return
            logger.info(
                "Codex catalog discovery unavailable; falling back to shipped snapshot."
            )
        self._catalog = self._fallback_loader.load()
        self._catalog_source = "fallback"
        logger.info(
            "Codex model catalog loaded from fallback snapshot (%d routable models).",
            len(self._catalog.routable_slugs()),
        )

    def get_catalog(self) -> CodexModelCatalog:
        """Return the resolved catalog. Raises if :meth:`load` was not called."""
        if self._catalog is None:
            raise RuntimeError("Codex model catalog not loaded; call load() first.")
        return self._catalog

    def get_catalog_source(self) -> str:
        """Return ``discovery`` or ``fallback`` for the loaded catalog."""

        if self._catalog_source is None:
            raise RuntimeError("Codex model catalog not loaded; call load() first.")
        return self._catalog_source

    def load_fallback_only(self) -> CodexModelCatalog:
        """Load and return the fallback snapshot synchronously (no discovery).

        Standalone escape hatch used when no DI catalog is available (e.g.
        tests, or when the startup discovery stage did not run). Does not
        populate :meth:`get_catalog`.
        """
        return self._fallback_loader.load()


__all__ = ["CodexModelCatalogProvider"]
