"""Mock command implementations for unit tests."""

from collections.abc import Mapping
from typing import Any

from src.core.domain.command_results import CommandResult
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.session import Session

from tests.unit.core.test_doubles import MockSuccessCommand


def setup_test_command_registry_for_unit_tests() -> Any:
    """Mock function for setting up test command registry.

    Returns:
        A CommandRegistry instance with mock commands registered
    """
    from src.core.services.command_service import CommandRegistry

    # Create a command registry with mock commands
    registry = CommandRegistry()
    for _, command in get_mock_commands().items():
        registry.register(command)
    return registry


class MockSetCommand(MockSuccessCommand):
    """Mock implementation of the set command for tests."""

    def __init__(self) -> None:
        super().__init__("set")

    @property
    def description(self) -> str:
        return "Set session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "set(param=value)"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        message = "Settings updated"
        return CommandResult(
            success=True,
            message=message,
            name=self.name,
            new_state=session,
            data={"processed_content": ""},
        )


class MockUnsetCommand(MockSuccessCommand):
    """Mock implementation of the unset command for tests."""

    def __init__(self) -> None:
        super().__init__("unset")

    @property
    def description(self) -> str:
        return "Unset session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "unset(param)"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        message = "Settings unset"
        return CommandResult(
            success=True,
            message=message,
            name=self.name,
            new_state=session,
            data={"processed_content": ""},
        )


class MockHelpCommand(MockSuccessCommand):
    """Mock implementation of the help command for tests."""

    def __init__(self) -> None:
        super().__init__("help")

    @property
    def description(self) -> str:
        return "Show help information (MOCK)"

    @property
    def format(self) -> str:
        return "help"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        message = "Mock help information"
        return CommandResult(
            success=True,
            message=message,
            name=self.name,
            data={"processed_content": ""},
        )


class MockHelloCommand(MockSuccessCommand):
    """Mock implementation of the hello command for tests."""

    def __init__(self) -> None:
        super().__init__("hello")

    @property
    def description(self) -> str:
        return "Say hello (MOCK)"

    @property
    def format(self) -> str:
        return "hello"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        session.state = session.state.with_hello_requested(True)

        result = CommandResult(
            success=True,
            message="Hello! I'm the mock command handler.",
            name=self.name,
            new_state=session,
            data={"processed_content": ""},
        )
        return result


class MockAnotherCommand(MockSuccessCommand):
    """Mock implementation of another command for tests."""

    def __init__(self) -> None:
        super().__init__("anothercmd")

    @property
    def description(self) -> str:
        return "Another mock command (MOCK)"

    @property
    def format(self) -> str:
        return "anothercmd"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        return CommandResult(
            success=True,
            message="Another mock command executed.",
            name=self.name,
            new_state=session,
            data={"processed_content": ""},
        )


class MockModelCommand(MockSuccessCommand):
    """Mock implementation of the model command for tests."""

    def __init__(self) -> None:
        super().__init__("model")

    @property
    def description(self) -> str:
        return "Set or unset the model (MOCK)"

    @property
    def format(self) -> str:
        return "model(name=value)"

    async def execute(
        self, args: Mapping[str, Any], session: Session, context: Any = None
    ) -> CommandResult:
        self._called = True
        self._called_with_args = dict(args)
        message = "Model command executed"
        return CommandResult(
            success=True,
            message=message,
            name=self.name,
            new_state=session,
            data={"processed_content": ""},
        )


def get_mock_commands() -> dict[str, BaseCommand]:
    """Get a dictionary of mock commands for testing.

    Returns:
        Dictionary mapping command names to command instances
    """
    commands: dict[str, BaseCommand] = {
        "set": MockSetCommand(),
        "unset": MockUnsetCommand(),
        "help": MockHelpCommand(),
        "hello": MockHelloCommand(),
        "anothercmd": MockAnotherCommand(),
        "model": MockModelCommand(),
    }
    return commands
