"""
Command handler implementation for the SOLID architecture.

This module provides command handlers that follow the SOLID principles
and implement the command handling interface.
"""

from __future__ import annotations

import abc
import logging
from typing import Any, cast

from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session

logger = logging.getLogger(__name__)


class ILegacyCommandHandler(abc.ABC):
    """Interface for legacy command handlers that use execute() method."""

    aliases: list[str] = []

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Get the name of the command."""

    @property
    def description(self) -> str:
        """Get a description of the command."""
        return f"Command handler for {self.name} command"

    @property
    def usage(self) -> str:
        """Get usage instructions for the command."""
        return f"{self.name}([param1=value1, param2=value2, ...])"

    @abc.abstractmethod
    async def execute(
        self,
        args: dict[str, str],
        session: Session,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Execute the command.

        Args:
            args: Command arguments
            session: Current session
            context: Additional context data

        Returns:
            CommandResult with the outcome of the command execution
        """


class BackendCommandHandler(ILegacyCommandHandler):
    """Command handler for setting backend-related configuration."""

    aliases = []

    @property
    def name(self) -> str:
        return "backend"

    @property
    def description(self) -> str:
        return "Change the active backend for LLM requests"

    @property
    def usage(self) -> str:
        return "backend([name=openrouter|gemini|anthropic|openai|...])"

    async def execute(
        self,
        args: dict[str, str],
        session: Session,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Set the backend type.

        Args:
            args: Command arguments with backend name
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        backend_name = args.get("name")
        if not backend_name:
            return CommandResult(
                success=False,
                message="Backend name must be specified",
                data={"name": self.name},
            )

        try:
            # Create new backend config with updated backend type
            backend_config = session.state.backend_config.with_backend(backend_name)

            # Create new session state with updated backend config
            # Create new session state with updated backend config
            from src.core.domain.configuration.backend_config import BackendConfiguration
            from src.core.domain.session import SessionState, SessionStateAdapter
            from src.core.interfaces.domain_entities import ISessionState

            updated_state: ISessionState
            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state
                new_state = old_state.with_backend_config(
                    cast(BackendConfiguration, backend_config)
                )
                updated_state = SessionStateAdapter(new_state)
            elif isinstance(session.state, SessionState):
                # Working with SessionState directly
                new_state = session.state.with_backend_config(
                    cast(BackendConfiguration, backend_config)
                )
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

            session.update_state(updated_state)

            session.update_state(updated_state)

            return CommandResult(
                success=True,
                message=f"Backend changed to {backend_name}",
                data={"name": self.name, "backend": backend_name},
            )
        except Exception as e:
            logger.error(f"Error setting backend: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting backend: {e}",
                data={"name": self.name},
            )


class ModelCommandHandler(ILegacyCommandHandler):
    """Command handler for setting model-related configuration."""

    aliases = []

    @property
    def name(self) -> str:
        return "model"

    @property
    def description(self) -> str:
        return "Change the active model for LLM requests"

    @property
    def usage(self) -> str:
        return "model([name=model-name])"

    async def execute(
        self,
        args: dict[str, str],
        session: Session,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Set the model name.

        Args:
            args: Command arguments with model name
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        model_name = args.get("name")
        if not model_name:
            return CommandResult(
                success=False,
                message="Model name must be specified",
                data={"name": self.name},
            )

        try:
            # Create new backend config with updated model name
            backend_config = session.state.backend_config.with_model(model_name)

            # Create new session state with updated backend config
            from src.core.domain.configuration.backend_config import BackendConfiguration
            from src.core.domain.session import SessionState, SessionStateAdapter
            from src.core.interfaces.domain_entities import ISessionState

            # Cast to concrete type
            concrete_backend_config = cast(BackendConfiguration, backend_config)

            updated_state: ISessionState
            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state
                new_state = old_state.with_backend_config(concrete_backend_config)
                updated_state = SessionStateAdapter(new_state)
            elif isinstance(session.state, SessionState):
                # Working with SessionState directly
                new_state = session.state.with_backend_config(concrete_backend_config)
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

            session.update_state(updated_state)

            return CommandResult(
                name=self.name,
                success=True,
                message=f"Model changed to {model_name}",
                data={"model": model_name},
            )
        except Exception as e:
            logger.error(f"Error setting model: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting model: {e}",
                data={"name": self.name},
            )


class TemperatureCommandHandler(ILegacyCommandHandler):
    """Command handler for setting temperature configuration."""

    aliases = []

    @property
    def name(self) -> str:
        return "temperature"

    @property
    def description(self) -> str:
        return "Change the temperature setting for LLM requests"

    @property
    def usage(self) -> str:
        return "temperature([value=0.0-1.0])"

    async def execute(
        self,
        args: dict[str, str],
        session: Session,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Set the temperature value.

        Args:
            args: Command arguments with temperature value
            session: Current session
            context: Additional context data

        Returns:
            CommandResult indicating success or failure
        """
        temp_value = args.get("value")
        if not temp_value:
            return CommandResult(
                success=False,
                message="Temperature value must be specified",
                data={"name": self.name},
            )

        try:
            # Convert to float and validate range
            temp_float = float(temp_value)
            if temp_float < 0 or temp_float > 1:
                return CommandResult(
                    success=False,
                    message="Temperature must be between 0.0 and 1.0",
                    data={"name": self.name},
                )

            # Create new reasoning config with updated temperature
            reasoning_config = session.state.reasoning_config.with_temperature(
                temp_float
            )

            # Create new session state with updated reasoning config
            from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
            from src.core.domain.session import SessionState, SessionStateAdapter
            from src.core.interfaces.domain_entities import ISessionState

            # Cast to concrete type
            concrete_reasoning_config = cast(ReasoningConfiguration, reasoning_config)

            updated_state: ISessionState
            if isinstance(session.state, SessionStateAdapter):
                # Working with SessionStateAdapter - get the underlying state
                old_state = session.state._state
                new_state = old_state.with_reasoning_config(concrete_reasoning_config)
                updated_state = SessionStateAdapter(new_state)
            elif isinstance(session.state, SessionState):
                # Working with SessionState directly
                new_state = session.state.with_reasoning_config(concrete_reasoning_config)
                updated_state = SessionStateAdapter(new_state)
            else:
                # Fallback for other implementations
                updated_state = session.state

            session.update_state(updated_state)

            return CommandResult(
                success=True,
                message=f"Temperature set to {temp_float}",
                data={"name": self.name, "temperature": temp_float},
            )
        except ValueError:
            return CommandResult(
                success=False,
                message="Temperature must be a valid number",
                data={"name": self.name},
            )
        except Exception as e:
            logger.error(f"Error setting temperature: {e}")
            return CommandResult(
                success=False,
                message=f"Error setting temperature: {e}",
                data={"name": self.name},
            )


class HelpCommandHandler(ILegacyCommandHandler):
    """Command handler for providing help information."""

    def __init__(
        self, command_registry: dict[str, ILegacyCommandHandler] | None = None
    ):
        """Initialize the help command handler.

        Args:
            command_registry: Registry of available commands
        """
        self._registry = command_registry or {}

    @property
    def name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "Display help information for available commands"

    @property
    def usage(self) -> str:
        return "help([command=command-name])"

    def set_registry(self, registry: dict[str, ILegacyCommandHandler]) -> None:
        """Set the command registry.

        Args:
            registry: Dictionary of command name to handler
        """
        self._registry = registry

    async def execute(
        self,
        args: dict[str, str],
        session: Session,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """Provide help information.

        Args:
            args: Command arguments with optional command name
            session: Current session
            context: Additional context data

        Returns:
            CommandResult with help information
        """
        # Support both new format (command=name) and legacy format (just the command name as key)
        command_name = args.get("command")
        if not command_name and args:
            # Legacy format: get the first argument key (e.g., {"set": True} -> "set")
            command_name = next(iter(args.keys()))

        if command_name:
            # Help for specific command
            handler = self._registry.get(command_name)
            if handler:
                # Handle both new command handlers and legacy _ExecuteAdapter objects
                if hasattr(handler, "description") and hasattr(handler, "usage"):
                    # New command handler with description/usage attributes
                    description = handler.description
                    usage = handler.usage
                elif hasattr(handler, "_inner"):
                    # Legacy _ExecuteAdapter - try to get description/format/examples from inner object
                    inner = handler._inner
                    description = getattr(
                        inner, "description", "No description available"
                    )
                    format_attr = getattr(inner, "format", None)
                    usage = format_attr if format_attr else f"{command_name}([args])"
                    examples = getattr(inner, "examples", None)

                    # Include examples in the help message if available
                    if examples and isinstance(examples, list):
                        examples_text = "\n".join(examples[:3])  # Show first 3 examples
                        help_message = f"Help for {command_name}: {description}\nUsage: {usage}\nExamples:\n{examples_text}"
                    else:
                        help_message = (
                            f"Help for {command_name}: {description}\nUsage: {usage}"
                        )

                    return CommandResult(
                        success=True,
                        message=help_message,
                        data={
                            "name": self.name,
                            "command": command_name,
                            "description": description,
                            "usage": usage,
                            "examples": examples or [],
                        },
                    )
                else:
                    # Fallback for unknown handler types
                    description = "No description available"
                    usage = f"{command_name}([args])"

                return CommandResult(
                    success=True,
                    message=f"Help for {command_name}: {description}\nUsage: {usage}",
                    data={
                        "name": self.name,
                        "command": command_name,
                        "description": description,
                        "usage": usage,
                    },
                )
            else:
                return CommandResult(
                    success=False,
                    message=f"Command {command_name} not found",
                    data={"name": self.name},
                )
        else:
            # General help
            command_list = ", ".join(sorted(self._registry.keys()))

            return CommandResult(
                name=self.name,
                success=True,
                message=(
                    "Available commands:\n"
                    f"{command_list}\n\n"
                    "Use help(command=command-name) for detailed help on a specific command."
                ),
                data={"commands": sorted(self._registry.keys())},
            )
