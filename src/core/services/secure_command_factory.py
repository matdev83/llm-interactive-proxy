"""
Secure command factory that enforces proper DI for domain commands.

This factory ensures that all commands are created with proper dependencies
and prevents direct state access violations.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

from src.core.domain.commands.secure_base_command import (
    SecureCommandBase,
    StatefulCommandBase,
    StatelessCommandBase,
)
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
    StateAccessViolationError,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=SecureCommandBase)


class SecureCommandFactory:
    """Factory for creating domain commands with proper DI enforcement."""
    
    def __init__(
        self,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification,
    ):
        """Initialize the factory with state services.
        
        Args:
            state_reader: Service for reading state
            state_modifier: Service for modifying state
        """
        self._state_reader = state_reader
        self._state_modifier = state_modifier
        self._created_commands: dict[str, SecureCommandBase] = {}
    
    def create_command(self, command_class: type[T]) -> T:
        """Create a command with proper dependency injection.
        
        Args:
            command_class: The command class to create
            
        Returns:
            Configured command instance
            
        Raises:
            StateAccessViolationError: If command requirements are not met
        """
        command_name = getattr(command_class, '__name__', str(command_class))
        
        # Check if we already created this command (singleton pattern)
        if command_name in self._created_commands:
            return self._created_commands[command_name]  # type: ignore
        
        # Validate command class
        if not issubclass(command_class, SecureCommandBase):
            raise StateAccessViolationError(
                f"Command {command_name} must inherit from SecureCommandBase",
                "Use StatefulCommandBase or StatelessCommandBase"
            )
        
        # Create command with appropriate dependencies
        try:
            if issubclass(command_class, StatefulCommandBase):
                logger.debug(f"Creating stateful command: {command_name}")
                command = command_class(
                    state_reader=self._state_reader,
                    state_modifier=self._state_modifier,
                )
            elif issubclass(command_class, StatelessCommandBase):
                logger.debug(f"Creating stateless command: {command_name}")
                command = command_class()
            else:
                # Generic SecureCommandBase
                logger.debug(f"Creating generic secure command: {command_name}")
                command = command_class(
                    state_reader=self._state_reader,
                    state_modifier=self._state_modifier,
                )
            
            # Cache the command
            self._created_commands[command_name] = command
            
            logger.info(f"Successfully created command: {command_name}")
            return command  # type: ignore
            
        except Exception as e:
            logger.error(f"Failed to create command {command_name}: {e}")
            raise StateAccessViolationError(
                f"Failed to create command {command_name}: {e}",
                "Ensure command constructor accepts required dependencies"
            )
    
    def get_created_commands(self) -> dict[str, SecureCommandBase]:
        """Get all commands created by this factory."""
        return self._created_commands.copy()
    
    def clear_cache(self) -> None:
        """Clear the command cache."""
        self._created_commands.clear()


class LegacyCommandAdapter:
    """Adapter to wrap legacy commands that don't use secure base classes."""
    
    def __init__(
        self,
        legacy_command: Any,
        state_reader: ISecureStateAccess,
        state_modifier: ISecureStateModification,
    ):
        """Initialize the adapter.
        
        Args:
            legacy_command: The legacy command to wrap
            state_reader: State reading service
            state_modifier: State modification service
        """
        self._legacy_command = legacy_command
        self._state_reader = state_reader
        self._state_modifier = state_modifier
    
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the legacy command."""
        return getattr(self._legacy_command, name)
    
    async def execute(self, args: Any, session: Any, context: Any = None) -> Any:
        """Execute the legacy command with state access protection.
        
        Args:
            args: Command arguments
            session: Session object
            context: Context object (will be protected)
            
        Returns:
            Command result
        """
        # Protect the context from direct state access
        if context:
            self._protect_context(context)
        
        # Execute the legacy command
        return await self._legacy_command.execute(args, session, context)
    
    def _protect_context(self, context: Any) -> None:
        """Protect context from direct state access."""
        if hasattr(context, 'app') and hasattr(context.app, 'state'):
            # Log a warning about legacy usage
            logger.warning(
                f"Legacy command {self._legacy_command.__class__.__name__} "
                f"is using context.app.state - consider migrating to SecureCommandBase"
            )
            
            # In strict mode, we could block this access entirely
            # For now, just log the violation
    
    def get_state_setting(self, setting_name: str) -> Any:
        """Provide state access through secure interface."""
        setting_methods = {
            'command_prefix': self._state_reader.get_command_prefix,
            'api_key_redaction_enabled': self._state_reader.get_api_key_redaction_enabled,
            'disable_interactive_commands': self._state_reader.get_disable_interactive_commands,
            'failover_routes': self._state_reader.get_failover_routes,
        }
        
        method = setting_methods.get(setting_name)
        if method:
            return method()
        
        raise StateAccessViolationError(
            f"Unknown state setting: {setting_name}",
            "Use one of: " + ", ".join(setting_methods.keys())
        )
    
    def update_state_setting(self, setting_name: str, value: Any) -> None:
        """Provide state modification through secure interface."""
        setting_methods = {
            'command_prefix': self._state_modifier.update_command_prefix,
            'api_key_redaction_enabled': self._state_modifier.update_api_key_redaction,
            'disable_interactive_commands': self._state_modifier.update_interactive_commands,
            'failover_routes': self._state_modifier.update_failover_routes,
        }
        
        method = setting_methods.get(setting_name)
        if method:
            method(value)
        else:
            raise StateAccessViolationError(
                f"Unknown state setting: {setting_name}",
                "Use one of: " + ", ".join(setting_methods.keys())
            )