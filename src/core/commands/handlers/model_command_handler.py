"""Command handler for the interactive ``!/model`` command."""

from collections.abc import Mapping
from typing import Any

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.model_command import ModelCommand
from src.core.domain.session import Session


@command("model")
class ModelCommandHandler(ICommandHandler):
    """Interactive handler that delegates to the domain ``ModelCommand``."""

    def __init__(self, model_command: ModelCommand | None = None) -> None:
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
        return await self._model_command.execute(args, session)
