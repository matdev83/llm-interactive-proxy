from __future__ import annotations

from src.core.commands.handler import ICommandHandler
from src.core.commands.models import Command
from src.core.commands.registry import command
from src.core.commands.session_state_adapter import SessionStateAdapter
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.secure_base_command import create_secure_command
from src.core.domain.commands.unset_command import UnsetCommand
from src.core.domain.session import Session


@command("unset")
class UnsetCommandHandler(ICommandHandler):
    """Handler for the 'unset' command."""

    @property
    def command_name(self) -> str:
        return "unset"

    @property
    def description(self) -> str:
        return "Unset a session value."

    @property
    def format(self) -> str:
        return "!/unset(key)"

    @property
    def examples(self) -> list[str]:
        return ["!/unset(model)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        if not command.args:
            return CommandResult(
                success=False,
                message="No arguments provided.",
                name=self.command_name,
            )

        adapter = SessionStateAdapter(session)
        domain_command = create_secure_command(
            UnsetCommand, state_reader=adapter, state_modifier=adapter
        )
        result = await domain_command.execute(command.args, session)

        if result.new_state is not None:
            session.state = result.new_state

        if result.success:
            return CommandResult(
                success=True,
                message="Settings unset",
                name=self.command_name,
                data=result.data,
                new_state=session.state,
            )

        if result.message == "unset: nothing to do":
            return CommandResult(
                success=True,
                message="Settings unset",
                name=self.command_name,
                data=result.data,
                new_state=session.state,
            )

        return CommandResult(
            success=False,
            message=result.message,
            name=self.command_name,
            data=result.data,
        )
