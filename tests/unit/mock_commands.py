"""Mock command implementations for unit tests."""

from collections.abc import Mapping
from typing import Any

from src.core.domain.chat import ChatMessage
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session, SessionStateAdapter


async def process_commands_in_messages_test(
    messages: list[ChatMessage],
    session_state: SessionStateAdapter,
    command_prefix: str = "!/",
    strip_commands: bool = True,
    preserve_unknown: bool = False,
    **kwargs: Any,  # Accept any additional kwargs to avoid breaking tests
) -> tuple[list[ChatMessage], list[str]]:
    """Mock function for processing commands in messages for tests.

    This implementation accepts and ignores any additional parameters that might be passed.

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
    # Return the messages unchanged and an empty list of commands
    return messages, []


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
