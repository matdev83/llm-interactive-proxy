"""Mock command implementations for unit tests."""

from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session


def process_commands_in_messages_test():
    """Mock function for processing commands in messages for tests."""
    return []


def setup_test_command_registry_for_unit_tests():
    """Mock function for setting up test command registry."""
    return []


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
        return CommandResult(
            success=True,
            message="",
            name=self.name,
            modified_session=session,
            # This is important - it tells the command processor to replace the command with empty string
            processed_content="",
        )


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
        return CommandResult(
            success=True,
            message="",
            name=self.name,
            modified_session=session,
            # This is important - it tells the command processor to replace the command with empty string
            processed_content="",
        )


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
        return CommandResult(
            success=True,
            message="Mock help information",
            name=self.name,
            # This is important - it tells the command processor to replace the command with empty string
            processed_content="",
        )


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
        return CommandResult(
            success=True,
            message="Hello!",
            name=self.name,
            modified_session=session,
            # This is important - it tells the command processor to replace the command with empty string
            processed_content="",
        )


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