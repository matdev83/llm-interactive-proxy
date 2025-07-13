from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Set, Type, Protocol
import logging

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ..proxy_logic import ProxyState

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    name: str
    success: bool
    message: str


class CommandContext(Protocol):
    """Protocol for command execution context to decouple commands from FastAPI app."""
    
    @property
    def backend_type(self) -> Optional[str]:
        """Get the current backend type."""
        ...
    
    @backend_type.setter
    def backend_type(self, value: str) -> None:
        """Set the backend type."""
        ...
    
    @property
    def api_key_redaction_enabled(self) -> bool:
        """Get API key redaction setting."""
        ...
    
    @api_key_redaction_enabled.setter
    def api_key_redaction_enabled(self, value: bool) -> None:
        """Set API key redaction setting."""
        ...
    
    @property
    def command_prefix(self) -> str:
        """Get command prefix."""
        ...
    
    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        """Set command prefix."""
        ...
    
    def get_backend(self, backend_name: str) -> Optional[Any]:
        """Get backend instance by name."""
        ...
    
    def save_config(self) -> None:
        """Save configuration if config manager is available."""
        ...


class AppCommandContext:
    """Concrete implementation of CommandContext that wraps FastAPI app state."""
    
    def __init__(self, app: "FastAPI") -> None:
        self.app = app
    
    @property
    def backend_type(self) -> Optional[str]:
        return getattr(self.app.state, "backend_type", None)
    
    @backend_type.setter
    def backend_type(self, value: str) -> None:
        self.app.state.backend_type = value
        # Also update the backend reference
        backend_attr = f"{value}_backend"
        if hasattr(self.app.state, backend_attr):
            self.app.state.backend = getattr(self.app.state, backend_attr)
    
    @property
    def api_key_redaction_enabled(self) -> bool:
        return getattr(self.app.state, "api_key_redaction_enabled", False)
    
    @api_key_redaction_enabled.setter
    def api_key_redaction_enabled(self, value: bool) -> None:
        self.app.state.api_key_redaction_enabled = value
    
    @property
    def command_prefix(self) -> str:
        return getattr(self.app.state, "command_prefix", "!/")
    
    @command_prefix.setter
    def command_prefix(self, value: str) -> None:
        self.app.state.command_prefix = value
    
    def get_backend(self, backend_name: str) -> Optional[Any]:
        backend_attr = f"{backend_name}_backend"
        return getattr(self.app.state, backend_attr, None)
    
    def save_config(self) -> None:
        config_manager = getattr(self.app.state, "config_manager", None)
        if config_manager:
            try:
                config_manager.save()
            except Exception as e:
                logger.error(f"Failed to save configuration: {e}")
                raise


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

    def execute(self, args: Mapping[str, Any],
                state: "ProxyState") -> CommandResult:
        raise NotImplementedError

    def execute_with_context(
        self, 
        args: Mapping[str, Any], 
        state: "ProxyState", 
        context: Optional[CommandContext] = None
    ) -> CommandResult:
        """Execute command with context. Default implementation calls execute for backward compatibility."""
        return self.execute(args, state)


# Registry -----------------------------------------------------------------
command_registry: Mapping[str, Type[BaseCommand]] = {}


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
