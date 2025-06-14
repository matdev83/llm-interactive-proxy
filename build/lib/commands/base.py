from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Type

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..proxy_logic import ProxyState


@dataclass
class CommandResult:
    name: str
    success: bool
    message: str


class BaseCommand:
    """Base class for proxy commands."""

    # command name used in messages
    name: str
    # short string describing command syntax
    format: str = ""
    # human friendly description
    description: str = ""
    # usage examples
    examples: List[str] = []

    def __init__(
        self,
        app: Optional[FastAPI] = None,
        functional_backends: Optional[Set[str]] = None,
    ) -> None:
        self.app = app
        self.functional_backends = functional_backends or set()

    def execute(self, args: Dict[str, Any],
                state: "ProxyState") -> CommandResult:
        raise NotImplementedError


# Registry -----------------------------------------------------------------
command_registry: Dict[str, Type[BaseCommand]] = {}


def register_command(cls: Type[BaseCommand]) -> Type[BaseCommand]:
    """Class decorator to register a command in the global registry."""
    command_registry[cls.name.lower()] = cls
    return cls


def create_command_instances(
    app: Optional[FastAPI], functional_backends: Optional[Set[str]] = None
) -> List[BaseCommand]:
    """Instantiate all registered commands."""
    instances: List[BaseCommand] = []
    for cls in command_registry.values():
        instances.append(cls(app=app, functional_backends=functional_backends))
    return instances
