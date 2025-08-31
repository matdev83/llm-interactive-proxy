"""Mock command implementations for unit tests."""

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.session import Session


@command("set")
class MockSetCommandHandler(ICommandHandler):
    """Mock implementation of the set command for tests."""

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
        message = "Settings updated"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )


@command("unset")
class MockUnsetCommandHandler(ICommandHandler):
    """Mock implementation of the unset command for tests."""

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
        message = "Settings unset"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )


@command("help")
class MockHelpCommandHandler(ICommandHandler):
    """Mock implementation of the help command for tests."""

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
        message = "Mock help information"
        return CommandResult(
            success=True,
            message=message,
        )


@command("hello")
class MockHelloCommandHandler(ICommandHandler):
    """Mock implementation of the hello command for tests."""

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
        return CommandResult(
            success=True,
            message="Another mock command executed.",
            new_state=session.state,
        )


@command("model")
class MockModelCommandHandler(ICommandHandler):
    """Mock implementation of the model command for tests."""

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
        message = "Model command executed"
        return CommandResult(
            success=True,
            message=message,
            new_state=session.state,
        )
