from __future__ import annotations

from typing import Any

class ValidationError(Exception):
    message: str
    path: list[Any]
