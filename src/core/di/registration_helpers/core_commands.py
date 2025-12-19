"""
Core command pipeline registration helper.

Registers command pipeline services:
- CommandParser
- CommandService
- CommandProcessor
- CommandStateService
- CommandPolicyService
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import cast

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import (
    register_singleton_if_absent,
)
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_command_pipeline_services(services: ServiceCollection) -> None:
    """Register command pipeline services."""
    from src.core.commands.parser import CommandParser
    from src.core.commands.service import NewCommandService
    from src.core.commands.tool_call_command_processor import (
        ToolCallCommandProcessor,
    )
    from src.core.interfaces.command_parser_interface import ICommandParser
    from src.core.interfaces.command_policy_service_interface import (
        ICommandPolicyService,
    )
    from src.core.interfaces.command_processor_interface import ICommandProcessor
    from src.core.interfaces.command_service_interface import ICommandService
    from src.core.interfaces.command_state_service_interface import (
        ICommandStateService,
    )
    from src.core.services.command_policy_service import CommandPolicyService
    from src.core.services.command_processor import CommandProcessor
    from src.core.services.command_state_service import CommandStateService
    from src.core.services.delegating_command_processor import (
        DelegatingCommandProcessor,
    )
    from src.core.services.session_service_impl import SessionService

    # Ensure command handlers are imported so their @command decorators register them
    try:
        package_name = "src.core.commands.handlers"
        package = importlib.import_module(package_name)
        for m in pkgutil.iter_modules(package.__path__):  # type: ignore[attr-defined]
            importlib.import_module(f"{package_name}.{m.name}")
    except Exception:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(
                "Failed to import command handlers for registration", exc_info=True
            )

    # Register CommandParser
    register_singleton_if_absent(
        services, cast(type, ICommandParser), implementation_type=CommandParser  # type: ignore[type-abstract]
    )
    register_singleton_if_absent(
        services, CommandParser, implementation_type=CommandParser
    )

    # Register CommandStateService
    def _command_state_service_factory(
        provider: IServiceProvider,
    ) -> CommandStateService:
        session = provider.get_required_service(SessionService)
        return CommandStateService(session)

    register_singleton_if_absent(
        services,
        CommandStateService,
        implementation_factory=_command_state_service_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, ICommandStateService),
            implementation_factory=lambda provider: provider.get_required_service(
                CommandStateService
            ),  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandStateService interface: {e}")

    # Register CommandPolicyService
    def _command_policy_service_factory(
        provider: IServiceProvider,
    ) -> CommandPolicyService:
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.application_state_interface import IApplicationState

        cfg = provider.get_required_service(AppConfig)
        app_state = provider.get_service(cast(type, IApplicationState))
        return CommandPolicyService(cfg, app_state)

    register_singleton_if_absent(
        services,
        CommandPolicyService,
        implementation_factory=_command_policy_service_factory,
    )
    try:
        register_singleton_if_absent(
            services,
            cast(type, ICommandPolicyService),
            implementation_factory=lambda provider: provider.get_required_service(
                CommandPolicyService
            ),  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandPolicyService interface: {e}")

    # Register CommandService
    def _command_service_factory(provider: IServiceProvider) -> ICommandService:
        from src.core.config.app_config import AppConfig
        from src.core.interfaces.application_state_interface import IApplicationState

        session_service = provider.get_required_service(SessionService)
        command_parser = provider.get_required_service(CommandParser)
        config = provider.get_required_service(AppConfig)
        app_state = provider.get_service(cast(type, IApplicationState))
        state_service = provider.get_required_service(CommandStateService)
        policy_service = provider.get_required_service(CommandPolicyService)
        return NewCommandService(
            session_service,
            command_parser,
            strict_command_detection=config.strict_command_detection,
            app_state=app_state,
            command_state_service=state_service,
            command_policy_service=policy_service,
            config=config,
        )

    register_singleton_if_absent(
        services,
        cast(type, ICommandService),
        implementation_factory=_command_service_factory,  # type: ignore[type-abstract]
    )

    # Register CommandProcessor
    def _command_processor_factory(provider: IServiceProvider) -> ICommandProcessor:
        command_service: ICommandService = provider.get_required_service(
            cast(type, ICommandService)
        )
        text_command_processor = CommandProcessor(command_service)
        tool_call_command_processor = ToolCallCommandProcessor(command_service)
        return DelegatingCommandProcessor(
            tool_call_command_processor=tool_call_command_processor,
            text_command_processor=text_command_processor,
        )

    try:
        register_singleton_if_absent(
            services,
            cast(type, ICommandProcessor),
            implementation_factory=_command_processor_factory,  # type: ignore[type-abstract]
        )
    except Exception as e:
        if logger.isEnabledFor(logging.WARNING):
            logger.warning(f"Failed to register ICommandProcessor interface: {e}")
