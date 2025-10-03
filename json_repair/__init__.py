"""Lightweight fallback implementation of the ``json_repair`` package."""

from __future__ import annotations

import ast
import json

__all__ = ["repair_json"]


def repair_json(payload: str) -> str:
    """Return a valid JSON string for the provided payload."""

    payload = payload.strip()
    if not payload:
        raise ValueError("Cannot repair empty JSON payload")

    try:
        json.loads(payload)
        return payload
    except json.JSONDecodeError:
        pass

    try:
        parsed = ast.literal_eval(payload)
    except (SyntaxError, ValueError) as exc:  # pragma: no cover - mirrors library
        raise ValueError("Unable to repair JSON payload") from exc

    return json.dumps(parsed)
