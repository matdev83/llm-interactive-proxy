"""
Command handler for setting/unsetting the active model (and optional backend).
"""

from src.core.commands.command import Command, CommandResult
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.domain.session import Session


@command("model")
class ModelCommandHandler(ICommandHandler):
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
        name = command.args.get("name")
        if name is None or (isinstance(name, str) and not name.strip()):
            # Unset
            new_state = session.state.with_backend_config(
                session.state.backend_config.with_model(None)
            )
            return CommandResult(
                success=True, message="Model command executed", new_state=new_state
            )

        # Set
        backend_type = None
        model = name
        if ":" in name:
            backend_type, model = name.split(":", 1)
        new_backend_cfg = session.state.backend_config.with_model(model)
        if backend_type:
            new_backend_cfg = new_backend_cfg.with_backend(backend_type)
        new_state = session.state.with_backend_config(new_backend_cfg)
        return CommandResult(
            success=True, message="Model command executed", new_state=new_state
        )
