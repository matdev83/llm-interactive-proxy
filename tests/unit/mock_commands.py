"""Mock command implementations for unit tests."""

from typing import Any

from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session


@command("set")
class MockSetCommandHandler(ICommandHandler):
    """Mock implementation of the set command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "set(param=value)"

    @property
    def examples(self) -> list[str]:
        return ["!/set(model=gpt-4)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        message = "Settings updated"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )


@command("unset")
class MockUnsetCommandHandler(ICommandHandler):
    """Mock implementation of the unset command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "unset"

    @property
    def description(self) -> str:
        return "Unset session parameters (MOCK)"

    @property
    def format(self) -> str:
        return "unset(param)"

    @property
    def examples(self) -> list[str]:
        return ["!/unset(model)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        message = "Settings unset"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )


@command("help")
class MockHelpCommandHandler(ICommandHandler):
    """Mock implementation of the help command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "help"

    @property
    def description(self) -> str:
        return "Show help information (MOCK)"

    @property
    def format(self) -> str:
        return "help"

    @property
    def examples(self) -> list[str]:
        return ["!/help"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        message = "Mock help information"
        return CommandResult(
            success=True,
            message=message,
        )


@command("hello")
class MockHelloCommandHandler(ICommandHandler):
    """Mock implementation of the hello command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "hello"

    @property
    def description(self) -> str:
        return "Say hello (MOCK)"

    @property
    def format(self) -> str:
        return "hello"

    @property
    def examples(self) -> list[str]:
        return ["!/hello"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        session.state = session.state.with_hello_requested(True)

        result = CommandResult(
            success=True,
            message="Hello! I'm the mock command handler.",
            new_state=session.state,
        )
        return result


@command("anothercmd")
class MockAnotherCommandHandler(ICommandHandler):
    """Mock implementation of another command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "anothercmd"

    @property
    def description(self) -> str:
        return "Another mock command (MOCK)"

    @property
    def format(self) -> str:
        return "anothercmd"

    @property
    def examples(self) -> list[str]:
        return ["!/anothercmd"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        return CommandResult(
            success=True,
            message="Another mock command executed.",
            new_state=session.state,
        )


@command("model")
class MockModelCommandHandler(ICommandHandler):
    """Mock implementation of the model command for tests."""

    def __init__(self, service: Any = None) -> None:
        self.service = service
        self.called = False

    def reset_mock_state(self) -> None:
        self.called = False

    @property
    def command_name(self) -> str:
        return "model"

    @property
    def description(self) -> str:
        return "Set or unset the model (MOCK)"

    @property
    def format(self) -> str:
        return "model(name=value)"

    @property
    def examples(self) -> list[str]:
        return ["!/model(name=gpt-4)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        self.called = True
        message = "Model command executed"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )
