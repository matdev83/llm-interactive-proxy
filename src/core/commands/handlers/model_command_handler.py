"""Command handler for the interactive ``!/model`` command."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.model_command import ModelCommand
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


@command("model")
class ModelCommandHandler(ICommandHandler):
    """Interactive handler that delegates to the domain ``ModelCommand``."""

    def __init__(
        self,
        command_service: "ICommandService | None" = None,
        model_command: ModelCommand | None = None,
    ) -> None:
        super().__init__(command_service)
        self._model_command = model_command or ModelCommand()

    @property
    def command_name(self) -> str:
        return "model"

    @property
    def description(self) -> str:
        return "Set or unset the active model (optionally with backend)"

    @property
    def format(self) -> str:
        return "model(name=<backend:>model)"

    @property
    def examples(self) -> list[str]:
        return ["!/model(name=gpt-4)", "!/model(name=openrouter:claude-3-opus)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        args: Mapping[str, Any] = command.args
        result = await self._model_command.execute(args, session)
        if not result.success:
            return result

        if self._command_service is not None:
            return CommandResult(
                name=result.name,
                success=True,
                message="Model command executed",
                data=getattr(result, "data", None),
                new_state=getattr(result, "new_state", None),
            )
        return result
