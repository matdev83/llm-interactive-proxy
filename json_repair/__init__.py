"""Lightweight fallback implementation of the :mod:`json_repair` package.

This test helper implements a minimal ``repair_json`` function that can
handle the subset of malformed JSON payloads exercised by the unit tests.
It intentionally avoids any heavy dependencies while providing compatible
behaviour with the real third-party library when it is unavailable in the
execution environment.
"""

from __future__ import annotations

import ast
import json


def repair_json(source: str) -> str:
    """Return a JSON string with minor syntax issues repaired."""
    try:
        json.loads(source)
        return source
    except json.JSONDecodeError:
        try:
            value = ast.literal_eval(source)
        except (ValueError, SyntaxError) as exc:  # pragma: no cover - parity with real lib
            raise ValueError("Unable to repair JSON string") from exc
        return json.dumps(value)

