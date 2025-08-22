"""Mock command implementations for unit tests."""

import re
from collections.abc import Mapping
from typing import Any, cast

from src.core.domain.chat import ChatMessage
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter
from src.core.domain.configuration.backend_config import BackendConfiguration


async def process_commands_in_messages_test(
    messages: list[ChatMessage],
    session_state: SessionStateAdapter,
    command_prefix: str = "!/",
    strip_commands: bool = True,
    preserve_unknown: bool = False,
    **kwargs: Any,  # Accept any additional kwargs to avoid breaking tests
) -> tuple[list[ChatMessage], list[str]]:
    """Mock function for processing commands in messages for tests.

    This implementation detects commands using regex and processes them accordingly.

    Args:
        messages: List of chat messages to process
        session_state: The session state
        command_prefix: The command prefix to use
        strip_commands: Whether to strip commands from messages
        preserve_unknown: Whether to preserve unknown commands
        **kwargs: Additional arguments that are ignored

    Returns:
        A tuple of (processed_messages, commands_found)
    """
    # Command pattern to match commands like !/set(model=value) or !/hello
    command_pattern = re.compile(rf"{re.escape(command_prefix)}(\w+)(?:\((.*?)\))?")

    # List to collect found commands
    commands_found = []

    # Process each message
    processed_messages = []
    for message in messages:
        content = message.content

        # Find all commands in the message
        matches = list(command_pattern.finditer(content))

        if matches:
            # Extract command names
            command_names = [match.group(1) for match in matches]
            commands_found.extend(command_names)

            # Execute commands to update session state
            for match in matches:
                command_name = match.group(1)
                args_str = match.group(2) or ""

                # Execute the command based on its type
                if command_name == "set":
                    await _execute_set_command(session_state, args_str)
                elif command_name == "unset":
                    await _execute_unset_command(session_state, args_str)
                elif command_name == "hello":
                    await _execute_hello_command(session_state)

            # If strip_commands is True, replace content with empty string
            if strip_commands:
                processed_message = ChatMessage(
                    role=message.role,
                    content="",  # Empty content as required by tests
                    name=message.name,
                    tool_calls=message.tool_calls,
                    tool_call_id=message.tool_call_id
                )
            else:
                processed_message = message
        else:
            # No commands found, keep the original message
            processed_message = message

        processed_messages.append(processed_message)

    return processed_messages, commands_found


async def _execute_set_command(session_state: SessionStateAdapter, args_str: str) -> None:
    """Execute a set command to update session state."""
    # Parse arguments like "model=gpt-4-turbo" or "project='abc def'" or "backend=gemini"
    arg_pairs = re.findall(r'(\w+)=["\']?([^"\']+)["\']?', args_str)

    for param, value in arg_pairs:
        if param == "model":
            # Handle model with backend prefix like "openrouter:gpt-4-turbo"
            if ":" in value:
                backend, model = value.split(":", 1)
                # Update both backend and model
                new_backend_config = session_state.backend_config.with_backend(backend).with_model(model)
            else:
                # Update just the model
                new_backend_config = session_state.backend_config.with_model(value)

            session_state._state = session_state._state.with_backend_config(
                cast(BackendConfiguration, new_backend_config)
            )
        elif param == "project":
            # Update the project
            session_state._state = session_state._state.with_project(value)
        elif param == "backend":
            # Update the backend type
            new_backend_config = session_state.backend_config.with_backend(value)
            session_state._state = session_state._state.with_backend_config(
                cast(BackendConfiguration, new_backend_config)
            )
        elif param == "interactive-mode":
            # Update interactive mode
            session_state._state = session_state._state.with_interactive_just_enabled(value.upper() == "ON")


async def _execute_unset_command(session_state: SessionStateAdapter, args_str: str) -> None:
    """Execute an unset command to clear session state values."""
    # Parse arguments like "model", "project", "model, project"
    params = [param.strip() for param in args_str.split(",")]

    for param in params:
        if param == "model":
            # Clear the model
            new_backend_config = session_state.backend_config.with_model(None)
            session_state._state = session_state._state.with_backend_config(
                cast(BackendConfiguration, new_backend_config)
            )
        elif param == "project":
            # Clear the project
            session_state._state = session_state._state.with_project(None)
        elif param == "backend":
            # Clear the backend type
            new_backend_config = session_state.backend_config.with_backend(None)
            session_state._state = session_state._state.with_backend_config(
                cast(BackendConfiguration, new_backend_config)
            )
        elif param == "interactive":
            # Clear interactive mode
            session_state._state = session_state._state.with_interactive_just_enabled(False)


async def _execute_hello_command(session_state: SessionStateAdapter) -> None:
    """Execute a hello command to set the hello_requested flag."""
    session_state._state = session_state._state.with_hello_requested(True)


def setup_test_command_registry_for_unit_tests() -> Any:
    """Mock function for setting up test command registry.

    Returns:
        A CommandRegistry instance with mock commands registered
    """
    from src.core.services.command_service import CommandRegistry

    # Create a command registry with mock commands
    registry = CommandRegistry()
    for _, command in get_mock_commands().items():
        registry.register(command)  # Use register instead of register_command

    return registry


class MockSetCommand(BaseCommand):
    """Mock implementation of the set command for tests."""

    @property
    def name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "set(param=value)"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command and return success."""
        # Return empty string to simulate command stripping
        result = CommandResult(
            success=True,
            message="",
            name=self.name,
            new_state=session,  # Use new_state instead of modified_session
            data={"processed_content": ""},  # Add processed_content to data
        )
        return result

    def _validate_di_usage(self) -> None:
        """Mock validation method to satisfy BaseCommand requirements."""


class MockUnsetCommand(BaseCommand):
    """Mock implementation of the unset command for tests."""

    @property
    def name(self) -> str:
        return "unset"

    @property
    def description(self) -> str:
        return "Unset session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "unset(param)"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command and return success."""
        # Return empty string to simulate command stripping
        result = CommandResult(
            success=True,
            message="",
            name=self.name,
            new_state=session,  # Use new_state instead of modified_session
            data={"processed_content": ""},  # Add processed_content to data
        )
        return result

    def _validate_di_usage(self) -> None:
        """Mock validation method to satisfy BaseCommand requirements."""


class MockHelpCommand(BaseCommand):
    """Mock implementation of the help command for tests."""

    @property
    def name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "Show help information (MOCK)"

    @property
    def format(self) -> str:
        return "help"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command and return success."""
        # Return empty string to simulate command stripping
        result = CommandResult(
            success=True,
            message="Mock help information",
            name=self.name,
            data={"processed_content": ""},  # Add processed_content to data
        )
        return result

    def _validate_di_usage(self) -> None:
        """Mock validation method to satisfy BaseCommand requirements."""


class MockHelloCommand(BaseCommand):
    """Mock implementation of the hello command for tests."""

    @property
    def name(self) -> str:
        return "hello"

    @property
    def description(self) -> str:
        return "Say hello (MOCK)"

    @property
    def format(self) -> str:
        return "hello"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        """Execute the command and return success."""
        # Mark the session as having received a hello command
        session.state = session.state.with_hello_requested(True)

        # Return empty string to simulate command stripping
        result = CommandResult(
            success=True,
            message="Hello!",
            name=self.name,
            new_state=session,  # Use new_state instead of modified_session
            data={"processed_content": ""},  # Add processed_content to data
        )
        return result

    def _validate_di_usage(self) -> None:
        """Mock validation method to satisfy BaseCommand requirements."""


def get_mock_commands() -> dict[str, BaseCommand]:
    """Get a dictionary of mock commands for testing.

    Returns:
        Dictionary mapping command names to command instances
    """
    commands = {
        "set": MockSetCommand(),
        "unset": MockUnsetCommand(),
        "help": MockHelpCommand(),
        "hello": MockHelloCommand(),
    }
    return commands
