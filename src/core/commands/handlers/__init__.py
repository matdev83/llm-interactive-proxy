from __future__ import annotations

# pyright: reportUnsupportedDunderAll=false
import importlib
from types import ModuleType
from typing import Any

__all__ = [
    "base_handler",
    "command_handler",
    "failover_command_handler",
    "hello_command_handler",
    "help_command_handler",
    "loop_detection_command_handler",
    "loop_detection_handlers",
    "model_command_handler",
    "project_dir_handler",
    "reasoning_aliases",
    "reasoning_handlers",
    "set_command_handler",
    "unset_command_handler",
]


def __getattr__(name: str) -> Any:
    if name in __all__:
        module: ModuleType = importlib.import_module(
            f"src.core.commands.handlers.{name}"
        )
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
