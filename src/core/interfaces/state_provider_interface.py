"""
State provider interface for enforcing proper state access patterns.

This interface ensures that all state access goes through proper abstractions
and prevents direct framework state manipulation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IStateProvider(Protocol):
    """Protocol for state providers that can be injected into services."""
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a setting value."""
        ...
    
    def set_setting(self, key: str, value: Any) -> None:
        """Set a setting value."""
        ...


class ISecureStateAccess(ABC):
    """Interface for secure state access that prevents direct manipulation."""
    
    @abstractmethod
    def get_command_prefix(self) -> str | None:
        """Get the command prefix through secure access."""
    
    @abstractmethod
    def get_api_key_redaction_enabled(self) -> bool:
        """Get API key redaction setting through secure access."""
    
    @abstractmethod
    def get_disable_interactive_commands(self) -> bool:
        """Get interactive commands disabled setting through secure access."""
    
    @abstractmethod
    def get_failover_routes(self) -> list[dict[str, Any]] | None:
        """Get failover routes through secure access."""


class ISecureStateModification(ABC):
    """Interface for secure state modification with proper validation."""
    
    @abstractmethod
    def update_command_prefix(self, prefix: str) -> None:
        """Update command prefix with validation."""
    
    @abstractmethod
    def update_api_key_redaction(self, enabled: bool) -> None:
        """Update API key redaction with validation."""
    
    @abstractmethod
    def update_interactive_commands(self, disabled: bool) -> None:
        """Update interactive commands setting with validation."""
    
    @abstractmethod
    def update_failover_routes(self, routes: list[dict[str, Any]]) -> None:
        """Update failover routes with validation."""


class StateAccessViolationError(Exception):
    """Raised when attempting to access state through invalid means."""
    
    def __init__(self, message: str, suggested_interface: str | None = None):
        super().__init__(message)
        self.suggested_interface = suggested_interface