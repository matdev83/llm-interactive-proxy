"""Lightweight fallback implementation of the ``json_repair`` package."""

from __future__ import annotations

import ast
import json
from typing import Any


def repair_json(json_string: str, **_: Any) -> str:
    """Repair a JSON string by attempting tolerant parsing.

    This fallback tries a normal ``json.loads`` first.  If parsing fails we
    fall back to ``ast.literal_eval`` which tolerates trailing commas and
    single-quoted keys/values.  The parsed object is then re-serialized to a
    JSON string so the rest of the code-path can consume it normally.
    """

    try:
        # Fast path for already-valid JSON.
        json.loads(json_string)
        return json_string
    except json.JSONDecodeError:
        try:
            repaired_obj = ast.literal_eval(json_string)
        except (SyntaxError, ValueError) as exc:  # pragma: no cover - mirrors library failure
            raise exc

    return json.dumps(repaired_obj)
