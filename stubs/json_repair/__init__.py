"""Lightweight stub implementation of the ``json_repair`` package for tests."""

from __future__ import annotations

import json
import re

__all__ = ["repair_json"]


def repair_json(payload: str) -> str:
    """Attempt to repair simple JSON formatting issues."""

    try:
        json.loads(payload)
        return payload
    except json.JSONDecodeError:
        normalized = payload.replace("'", '"')
        normalized = re.sub(r",(\s*[}\]])", r"\1", normalized)
        return normalized
