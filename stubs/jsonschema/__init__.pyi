from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .exceptions import ValidationError as ValidationError

def validate(instance: Any, schema: Mapping[str, Any]) -> None: ...

class Draft7Validator:
    def __init__(self, schema: Mapping[str, Any]) -> None: ...
    def iter_errors(self, instance: Any) -> Iterable[ValidationError]: ...
