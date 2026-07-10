"""Configuration for Codex model catalog auto-discovery.

Lives under ``backends.openai_codex.extra.codex.model_catalog`` (and the v2 /
app-server equivalents). The parsing helper
:func:`codex_model_catalog_config_from_mapping` is implemented in a later TDD
phase alongside its tests; only the data model is defined here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CodexModelCatalogConfig:
    """Operator-tunable knobs for catalog discovery and fallback.

    Attributes:
        discovery_enabled: When True (default), run ``codex debug models`` at
            startup and use the parsed catalog; on any failure fall back to the
            shipped snapshot. When False, skip discovery and use the snapshot.
        fallback_path: Optional override path to a fallback catalog JSON file
            (same format as ``codex debug models`` output). When None, the
            shipped snapshot under ``src/resources/codex/`` is used.
        codex_binary_path: Optional explicit path to the codex binary. When
            None, the connector resolves the binary via PATH / ``CODEX_BIN`` /
            npm-global locations.
        discovery_timeout_seconds: Hard timeout for the ``codex debug models``
            subprocess call before falling back.
    """

    discovery_enabled: bool = True
    fallback_path: str | None = None
    codex_binary_path: str | None = None
    discovery_timeout_seconds: float = 10.0


DEFAULT_CODEX_MODEL_CATALOG_CONFIG = CodexModelCatalogConfig()

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_STRINGS
    return bool(value)


def _coerce_str_or_none(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _coerce_timeout(value: object, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, int | float):
        seconds = float(value)
    elif isinstance(value, str):
        try:
            seconds = float(value.strip())
        except ValueError:
            return default
    else:
        return default
    if seconds <= 0:
        return default
    return seconds


def codex_model_catalog_config_from_mapping(
    raw: Mapping[str, object] | None,
) -> CodexModelCatalogConfig:
    """Build a :class:`CodexModelCatalogConfig` from a YAML/settings mapping."""
    if not raw:
        return DEFAULT_CODEX_MODEL_CATALOG_CONFIG
    return CodexModelCatalogConfig(
        discovery_enabled=_coerce_bool(raw.get("discovery_enabled"), True),
        fallback_path=_coerce_str_or_none(raw.get("fallback_path")),
        codex_binary_path=_coerce_str_or_none(raw.get("codex_binary_path")),
        discovery_timeout_seconds=_coerce_timeout(
            raw.get("discovery_timeout_seconds"), 10.0
        ),
    )


__all__ = [
    "DEFAULT_CODEX_MODEL_CATALOG_CONFIG",
    "CodexModelCatalogConfig",
    "codex_model_catalog_config_from_mapping",
]
