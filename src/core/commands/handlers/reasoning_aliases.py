from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.core.commands.command import Command
from src.core.commands.handler import ICommandHandler
from src.core.commands.registry import command
from src.core.common.utils import wildcard_match
from src.core.domain.command_results import CommandResult
from src.core.domain.configuration.reasoning_aliases_config import (
    ModelReasoningAliases,
    ReasoningMode,
)
from src.core.domain.session import Session

if TYPE_CHECKING:
    from src.core.interfaces.command_service_interface import ICommandService


class ReasoningAliasCommandHandler(ICommandHandler):
    """
    Base class for reasoning alias command handlers.
    """

    def __init__(
        self,
        command_service: ICommandService | None = None,
        secure_state_access: Any = None,
        secure_state_modification: Any = None,
    ) -> None:
        super().__init__(
            command_service, secure_state_access, secure_state_modification
        )
        self.aliases: list[str] = []

    @property
    def description(self) -> str:
        return f"Activates the {self.command_name} reasoning mode."

    @property
    def format(self) -> str:
        return f"!/{self.command_name}"

    @property
    def examples(self) -> list[str]:
        return [f"!/{self.command_name}"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        config = self._secure_state_access.get_config()
        model_id = session.get_model()

        if not config or not config.reasoning_aliases:
            return CommandResult(False, "Reasoning aliases are not configured.")

        if model_id:
            for model_aliases in config.reasoning_aliases.reasoning_alias_settings:
                if wildcard_match(model_aliases.model, model_id):
                    mode = self.get_reasoning_mode(model_aliases)
                    if mode:
                        session.set_reasoning_mode(mode)
                        return CommandResult(
                            True, f"Reasoning mode set to {self.command_name}."
                        )

        return CommandResult(
            False, f"No reasoning settings found for model {model_id}."
        )

    def get_reasoning_mode(
        self, model_aliases: ModelReasoningAliases
    ) -> ReasoningMode | None:
        raise NotImplementedError


@command("max")
class MaxReasoningHandler(ReasoningAliasCommandHandler):
    @property
    def command_name(self) -> str:
        return "max"

    def get_reasoning_mode(
        self, model_aliases: ModelReasoningAliases
    ) -> ReasoningMode | None:
        return model_aliases.modes.get("high")


@command("medium")
class MediumReasoningHandler(ReasoningAliasCommandHandler):
    @property
    def command_name(self) -> str:
        return "medium"

    def get_reasoning_mode(
        self, model_aliases: ModelReasoningAliases
    ) -> ReasoningMode | None:
        return model_aliases.modes.get("medium")


@command("low")
class LowReasoningHandler(ReasoningAliasCommandHandler):
    @property
    def command_name(self) -> str:
        return "low"

    def get_reasoning_mode(
        self, model_aliases: ModelReasoningAliases
    ) -> ReasoningMode | None:
        return model_aliases.modes.get("low")


@command("no-think")
class NoThinkReasoningHandler(ReasoningAliasCommandHandler):
    def __init__(
        self,
        command_service: ICommandService | None = None,
        secure_state_access: Any = None,
        secure_state_modification: Any = None,
    ) -> None:
        super().__init__(
            command_service, secure_state_access, secure_state_modification
        )
        self.aliases = [
            "no-thinking",
            "no-reasoning",
            "disable-thinking",
            "disable-reasoning",
        ]

    @property
    def command_name(self) -> str:
        return "no-think"

    def get_reasoning_mode(
        self, model_aliases: ModelReasoningAliases
    ) -> ReasoningMode | None:
        return model_aliases.modes.get("none")


@command("provider")
class SetProviderCommandHandler(ICommandHandler):
    """
    Sets the provider for the current session.
    """

    @property
    def command_name(self) -> str:
        return "provider"

    @property
    def description(self) -> str:
        return "Sets the provider for the current session."

    @property
    def format(self) -> str:
        return "!/provider <provider_name>"

    @property
    def examples(self) -> list[str]:
        return [
            "!/provider anthropic",
            "!/provider openai",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        if not command.args or "provider_name" not in command.args:
            return CommandResult(False, "Provider name is required.")

        provider_name = str(command.args["provider_name"])
        session.set_provider(provider_name)

        return CommandResult(True, f"Provider set to {provider_name}.")


@command("mode")
class SetModeCommandHandler(ICommandHandler):
    """
    Sets the reasoning mode for the current session.
    """

    @property
    def command_name(self) -> str:
        return "mode"

    @property
    def description(self) -> str:
        return "Sets the reasoning mode for the current session."

    @property
    def format(self) -> str:
        return "!/mode <mode_name>"

    @property
    def examples(self) -> list[str]:
        return [
            "!/mode max",
            "!/mode low",
        ]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        if not command.args or "mode_name" not in command.args:
            return CommandResult(False, "Mode name is required.")

        mode_name = str(command.args["mode_name"])
        config = self._secure_state_access.get_config()
        model_id = session.get_model()

        if not config or not config.reasoning_aliases:
            return CommandResult(False, "Reasoning aliases are not configured.")

        if model_id:
            for model_aliases in config.reasoning_aliases.reasoning_alias_settings:
                if wildcard_match(model_aliases.model, model_id):
                    mode = model_aliases.modes.get(mode_name)
                    if mode:
                        session.set_reasoning_mode(mode)
                        return CommandResult(
                            True, f"Reasoning mode set to {mode_name}."
                        )

        return CommandResult(
            False, f"No reasoning settings found for model {model_id}."
        )
