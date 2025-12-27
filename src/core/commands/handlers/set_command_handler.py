from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.core.commands.handler import ICommandHandler
from src.core.commands.handlers.base_handler import BaseCommandHandler
from src.core.commands.models import Command
from src.core.commands.registry import command
from src.core.commands.session_state_adapter import SessionStateAdapter
from src.core.commands.set_parameter_registry import build_set_parameter_handlers
from src.core.domain.command_results import CommandResult
from src.core.domain.commands.secure_base_command import create_secure_command
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.session import Session

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.core.interfaces.command_policy_service_interface import (
        ICommandPolicyService,
    )
    from src.core.interfaces.command_service_interface import ICommandService


@command("set")
class SetCommandHandler(ICommandHandler):
    """Adapter that delegates to the domain SetCommand implementation."""

    def __init__(
        self,
        command_service: ICommandService | None = None,
        policy_service: ICommandPolicyService | None = None,
    ) -> None:
        super().__init__(command_service=command_service, policy_service=policy_service)
        self._policy_service = policy_service

    @property
    def command_name(self) -> str:
        return "set"

    @property
    def description(self) -> str:
        return "Set a session value."

    @property
    def format(self) -> str:
        return "!/set(key=value)"

    @property
    def examples(self) -> list[str]:
        return ["!/set(model=anthropic/claude-3-opus-20240229)"]

    async def handle(self, command: Command, session: Session) -> CommandResult:
        if not command.args:
            return CommandResult(
                success=False,
                message="No arguments provided.",
                name=self.command_name,
            )

        adapter = SessionStateAdapter(session)
        domain_command = create_secure_command(
            SetCommand,
            state_reader=adapter,
            state_modifier=adapter,
            policy_service=self._policy_service,
        )
        result = await domain_command.execute(command.args, session)

        if result.new_state is not None:
            session.state = result.new_state

        if result.success:
            return CommandResult(
                success=True,
                message="Settings updated",
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

    def _build_parameter_handlers(self) -> dict[str, BaseCommandHandler]:
        """Retained for backward-compatibility in tests that patch this method."""
        return build_set_parameter_handlers()

    def _is_static_routing_enabled(self) -> bool:
        """Legacy helper preserved for unit tests."""
        if self._policy_service is not None:
            try:
                result = self._policy_service.is_static_route_enforced()
                return bool(result)
            except Exception as e:
                # Log the error for debugging but fall back to env var check
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Policy service error checking static route enforcement: %s. "
                        "Falling back to STATIC_ROUTE environment variable.",
                        e,
                        exc_info=True,
                    )

        import os

        static_route = os.environ.get("STATIC_ROUTE")
        return static_route is not None and static_route.strip() != ""
