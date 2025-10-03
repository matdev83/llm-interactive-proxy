"""Test stub for the external json_repair dependency."""
from __future__ import annotations

from typing import Any


def repair_json(content: str, *_: Any, **__: Any) -> str:
    """Return the provided JSON content unchanged.

    This lightweight fallback mirrors the interface expected by the
    application while avoiding an optional dependency during tests.
    """

    return content
