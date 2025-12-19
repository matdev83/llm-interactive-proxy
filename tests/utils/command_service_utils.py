from __future__ import annotations

from src.core.commands.parser import CommandParser
from src.core.commands.service import NewCommandService
from src.core.config.app_config import AppConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.command_policy_service import CommandPolicyService
from src.core.services.command_state_service import CommandStateService


def build_new_command_service(
    session_service: ISessionService,
    command_parser: CommandParser,
    *,
    app_state: IApplicationState | None = None,
    strict_command_detection: bool = False,
    config: AppConfig | None = None,
) -> NewCommandService:
    """Construct a NewCommandService with default policy/state services for tests."""

    effective_config = config or AppConfig()
    state_service = CommandStateService(session_service)
    policy_service = CommandPolicyService(effective_config, app_state=app_state)

    return NewCommandService(
        session_service,
        command_parser,
        strict_command_detection=strict_command_detection,
        app_state=app_state,
        command_state_service=state_service,
        command_policy_service=policy_service,
        config=effective_config,
    )
