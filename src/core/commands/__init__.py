from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

__all__ = ["handlers"]


def __getattr__(name: str) -> Any:
    if name == "handlers":
        module: ModuleType = importlib.import_module("src.core.commands.handlers")
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
