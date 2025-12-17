from __future__ import annotations

from typing import Any

from src.core.config.dict_utils import merge_dicts


class ConfigMerger:
    """Deterministically merge configuration layers (later layers win)."""

    def merge(self, layers: list[dict[str, Any]]) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for layer in layers:
            merge_dicts(merged, layer)
        return merged
