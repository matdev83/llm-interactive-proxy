"""Experimental OpenAI Codex connector with websocket v2 transport semantics.

Inherits the auto-discovered Codex model catalog from the ``openai-codex``
connector (no hardcoded model slugs).
"""

from src.connectors._openai_codex_connector import OPENAI_VENDOR_PREFIX
from src.connectors._openai_codex_v2_connector import OpenAICodexV2Connector
from src.connectors.openai_codex.catalog import (
    CodexModelCatalog,
    CodexModelCatalogConfig,
    CodexModelCatalogProvider,
    ICodexModelCatalog,
)

__all__: list[str] = [
    "OPENAI_VENDOR_PREFIX",
    "OpenAICodexV2Connector",
    "CodexModelCatalog",
    "CodexModelCatalogConfig",
    "CodexModelCatalogProvider",
    "ICodexModelCatalog",
]
