"""Result types for models.dev / model catalog resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.core.domain.model_capabilities import ModelLimits


class ModelCatalogMatchTier(str, Enum):
    """How the catalog entry was matched."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    VENDOR_STRIPPED = "vendor_stripped"
    PREFIX = "prefix"
    TOKEN_OVERLAP = "token_overlap"
    FUZZY = "fuzzy"
    NONE = "none"


@dataclass(frozen=True)
class ModelCatalogMatchResult:
    """Outcome of resolving a model id against the loaded catalog."""

    tier: ModelCatalogMatchTier
    limits: ModelLimits | None
    input_modalities: frozenset[str] | None
    resolved_catalog_key: str | None
    catalog_provider_id: str | None
