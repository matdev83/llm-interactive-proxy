"""Codex model catalog subsystem.

Auto-discovery (``codex debug models``) + shipped fallback snapshot, shared by
the ``openai-codex``, ``openai-codex-v2`` and ``openai-codex-app-server``
connectors. Behavior is filled in across TDD phases; this package exposes the
data models, interfaces, config and (currently stubbed) implementation classes.
"""

from __future__ import annotations

from src.connectors.openai_codex.catalog.config import (
    DEFAULT_CODEX_MODEL_CATALOG_CONFIG,
    CodexModelCatalogConfig,
    codex_model_catalog_config_from_mapping,
)
from src.connectors.openai_codex.catalog.discovery_service import (
    CodexCatalogDiscoveryService,
)
from src.connectors.openai_codex.catalog.fallback_loader import (
    CodexCatalogFallbackLoader,
)
from src.connectors.openai_codex.catalog.interfaces import (
    ICodexCatalogDiscoveryService,
    ICodexCatalogFallbackLoader,
    ICodexCatalogParser,
    ICodexModelCatalog,
    ICodexModelCatalogProvider,
)
from src.connectors.openai_codex.catalog.parser import CodexCatalogParser
from src.connectors.openai_codex.catalog.provider import CodexModelCatalogProvider
from src.connectors.openai_codex.catalog.types import (
    CodexModelCatalog,
    CodexModelReasoningProfile,
)

__all__ = [
    "DEFAULT_CODEX_MODEL_CATALOG_CONFIG",
    "CodexCatalogDiscoveryService",
    "CodexCatalogFallbackLoader",
    "CodexCatalogParser",
    "CodexModelCatalog",
    "CodexModelCatalogConfig",
    "CodexModelCatalogProvider",
    "CodexModelReasoningProfile",
    "ICodexCatalogDiscoveryService",
    "ICodexCatalogFallbackLoader",
    "ICodexCatalogParser",
    "ICodexModelCatalog",
    "ICodexModelCatalogProvider",
    "codex_model_catalog_config_from_mapping",
]
