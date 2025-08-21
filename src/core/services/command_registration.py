"""Command registration utilities for the DI container."""

import logging
from typing import TypeVar

from src.core.di.container import ServiceCollection
from src.core.domain.commands.base_command import BaseCommand
from src.core.domain.commands.command_factory import CommandFactory
from src.core.domain.commands.failover_commands import (
    CreateFailoverRouteCommand,
    DeleteFailoverRouteCommand,
    ListFailoverRoutesCommand,
    RouteAppendCommand,
    RouteClearCommand,
    RoutePrependCommand,
)
from src.core.domain.commands.hello_command import HelloCommand
from src.core.domain.commands.help_command import HelpCommand
from src.core.domain.commands.loop_detection_commands.loop_detection_command import (
    LoopDetectionCommand,
)
from src.core.domain.commands.loop_detection_commands.tool_loop_detection_command import (
    ToolLoopDetectionCommand,
)
from src.core.domain.commands.loop_detection_commands.tool_loop_max_repeats_command import (
    ToolLoopMaxRepeatsCommand,
)
from src.core.domain.commands.loop_detection_commands.tool_loop_mode_command import (
    ToolLoopModeCommand,
)
from src.core.domain.commands.loop_detection_commands.tool_loop_ttl_command import (
    ToolLoopTTLCommand,
)
from src.core.domain.commands.model_command import ModelCommand
from src.core.domain.commands.oneoff_command import OneoffCommand
from src.core.domain.commands.openai_url_command import OpenAIUrlCommand
from src.core.domain.commands.project_command import ProjectCommand
from src.core.domain.commands.pwd_command import PwdCommand
from src.core.domain.commands.set_command import SetCommand
from src.core.domain.commands.temperature_command import TemperatureCommand
from src.core.domain.commands.unset_command import UnsetCommand
from src.core.interfaces.state_provider_interface import (
    ISecureStateAccess,
    ISecureStateModification,
)
from src.core.services.command_service import CommandRegistry

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseCommand)


def register_all_commands(
    services: ServiceCollection,
    registry: CommandRegistry,
) -> None:
    """Register all commands in the DI container.

    This function registers all known commands in the DI container, making them
    available for injection. It also registers them in the command registry for
    lookup by name.

    Args:
        services: The service collection to register commands with
        registry: The command registry to register commands with
    """
    # Register the command factory first
    CommandFactory.register_factory(services)
    # Register stateless commands (no dependencies)
    _register_stateless_command(services, registry, HelpCommand)
    _register_stateless_command(services, registry, HelloCommand)
    _register_stateless_command(services, registry, ModelCommand)
    _register_stateless_command(services, registry, OneoffCommand)
    _register_stateless_command(services, registry, ProjectCommand)
    _register_stateless_command(services, registry, PwdCommand)
    _register_stateless_command(services, registry, TemperatureCommand)
    _register_stateless_command(services, registry, LoopDetectionCommand)
    _register_stateless_command(services, registry, ToolLoopDetectionCommand)
    _register_stateless_command(services, registry, ToolLoopMaxRepeatsCommand)
    _register_stateless_command(services, registry, ToolLoopModeCommand)
    _register_stateless_command(services, registry, ToolLoopTTLCommand)

    # Register stateful commands (require dependencies)
    # Each needs a factory method that creates the command with dependencies
    services.add_singleton_factory(
        SetCommand,
        lambda provider: SetCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        UnsetCommand,
        lambda provider: UnsetCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        CreateFailoverRouteCommand,
        lambda provider: CreateFailoverRouteCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        DeleteFailoverRouteCommand,
        lambda provider: DeleteFailoverRouteCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        ListFailoverRoutesCommand,
        lambda provider: ListFailoverRoutesCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        RouteAppendCommand,
        lambda provider: RouteAppendCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        RouteClearCommand,
        lambda provider: RouteClearCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        RoutePrependCommand,
        lambda provider: RoutePrependCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )
    services.add_singleton_factory(
        OpenAIUrlCommand,
        lambda provider: OpenAIUrlCommand(
            provider.get_service(ISecureStateAccess),
            provider.get_service(ISecureStateModification),
        ),
    )

    # Register all commands in the registry for lookup by name
    _register_all_commands_in_registry(services, registry)


def _register_stateless_command(
    services: ServiceCollection,
    registry: CommandRegistry,
    command_type: type[T],
) -> None:
    """Register a stateless command in the DI container.

    Args:
        services: The service collection to register with
        registry: The command registry to register with
        command_type: The command class to register
    """
    services.add_singleton_factory(
        command_type,
        lambda _: command_type(),
    )


def _register_all_commands_in_registry(
    services: ServiceCollection,
    registry: CommandRegistry,
) -> None:
    """Register all commands from the DI container in the command registry.

    This ensures that the registry contains all commands that are available
    through the DI container.

    Args:
        services: The service collection containing the commands
        registry: The command registry to register commands with
    """
    # We need to resolve all command types from the DI container
    # and register them in the registry
    from src.core.di.services import build_service_provider

    provider = build_service_provider(services)

    # Get the command factory
    command_factory = provider.get_service(CommandFactory)
    if command_factory is None:
        logger.error("CommandFactory not registered in DI container")
        raise RuntimeError("CommandFactory not registered in DI container")

    # Get all registered command types
    command_types: list[type[BaseCommand]] = [
        # Stateless commands
        HelpCommand,
        HelloCommand,
        ModelCommand,
        OneoffCommand,
        ProjectCommand,
        PwdCommand,
        TemperatureCommand,
        LoopDetectionCommand,
        ToolLoopDetectionCommand,
        ToolLoopMaxRepeatsCommand,
        ToolLoopModeCommand,
        ToolLoopTTLCommand,
        # Stateful commands
        SetCommand,
        UnsetCommand,
        CreateFailoverRouteCommand,
        DeleteFailoverRouteCommand,
        ListFailoverRoutesCommand,
        RouteAppendCommand,
        RouteClearCommand,
        RoutePrependCommand,
        OpenAIUrlCommand,
    ]

    # Register each command in the registry using the command factory
    for command_type in command_types:
        try:
            # Use the command factory to create the command
            command = command_factory.create(command_type)
            registry.register(command)
        except Exception as e:
            logger.error(f"Failed to register command {command_type.__name__}: {e}")
