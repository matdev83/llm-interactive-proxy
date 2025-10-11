"""
Command services initialization stage.

This stage registers command-related services:
- Command registry
- Command service
- Command settings service
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.di_interface import IServiceProvider

from .base import InitializationStage

logger = logging.getLogger(__name__)


class CommandStage(InitializationStage):
    """
    Stage for registering command-related services.

    This stage registers:
    - Command registry (for registering available commands)
    - Command service (main command processing interface)
    - Command settings service (command configuration)
    """

    @property
    def name(self) -> str:
        return "commands"

    def get_dependencies(self) -> list[str]:
        return ["core_services"]

    def get_description(self) -> str:
        return "Register command services (registry, service, settings)"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register command services."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing command services...")

        # Register command registry
        self._register_command_registry(services)

        # Register command settings service
        self._register_command_settings_service(services, config)

        # Register command service
        self._register_command_service(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Command services initialized successfully")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that command services can be registered."""
        try:
            # Check that required modules are available

            # Validate config has command settings
            if not hasattr(config, "command_prefix") and logger.isEnabledFor(
                logging.WARNING
            ):
                logger.warning("Config missing command_prefix")

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Command services validation failed: {e}")
            return False

    def _register_command_registry(self, services: ServiceCollection) -> None:
        """Register the CommandRegistry service for backward compatibility."""
        try:
            from src.core.services.command_utils import CommandRegistry

            # Register CommandRegistry as singleton
            services.add_singleton(CommandRegistry)
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered CommandRegistry service")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register CommandRegistry: {e}")

    def _register_command_settings_service(
        self, services: ServiceCollection, config: AppConfig
    ) -> None:
        """Register command settings service with configuration."""
        try:
            from src.core.interfaces.command_settings_interface import (
                ICommandSettingsService,
            )
            from src.core.services.command_settings_service import (
                CommandSettingsService,
            )

            # Create instance with config values
            cmd_settings = CommandSettingsService(
                default_command_prefix=config.command_prefix,
                default_api_key_redaction=config.auth.redact_api_keys_in_prompts,
            )

            # Register as singleton instance
            services.add_instance(CommandSettingsService, cmd_settings)
            services.add_instance(ICommandSettingsService, cmd_settings)  # type: ignore[type-abstract] # Mypy incorrectly flags interface as abstract for instance registration

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered command settings service")
        except ImportError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register command settings service: {e}")

    def _register_command_service(self, services: ServiceCollection) -> None:
        """Register command service with dependencies."""
        try:
            from src.core.commands.parser import CommandParser
            from src.core.commands.service import NewCommandService
            from src.core.interfaces.command_parser_interface import ICommandParser
            from src.core.interfaces.command_service_interface import ICommandService

            def command_service_factory(
                provider: IServiceProvider,
            ) -> NewCommandService:
                """Factory function for creating CommandService with dependencies."""
                from src.core.services.session_service_impl import SessionService

                session_service = provider.get_required_service(SessionService)
                command_parser = provider.get_required_service(CommandParser)
                from typing import cast

                app_state = provider.get_service(cast(type, IApplicationState))
                return NewCommandService(
                    session_service,
                    command_parser,
                    app_state=app_state,
                )

            services.add_singleton(
                NewCommandService, implementation_factory=command_service_factory
            )
            services.add_singleton(
                ICommandService,
                implementation_factory=lambda sp: sp.get_required_service(
                    NewCommandService
                ),
            )

            services.add_singleton(CommandParser)
            services.add_singleton(ICommandParser, CommandParser)

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Registered new command service and parser with dependencies"
                )
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(f"Could not register command service or parser: {e}")

    def _register_default_commands(self, services: ServiceCollection) -> None:
        """Register default commands using auto-discovery from domain command registry."""
        try:
            # Register a factory that will populate the command registry with auto-discovered commands
            def populate_commands_factory(provider: IServiceProvider) -> None:
                """Factory to populate the command registry with auto-discovered commands."""
                try:
                    # Import domain commands to trigger auto-discovery
                    import src.core.domain.commands  # noqa: F401
                    from src.core.domain.commands.command_registry import (
                        domain_command_registry,
                    )
                    from src.core.interfaces.command_settings_interface import (
                        ICommandSettingsService,
                    )
                    from src.core.interfaces.state_provider_interface import (
                        ISecureStateAccess,
                        ISecureStateModification,
                    )
                    from src.core.services.command_utils import CommandRegistry

                    registry = provider.get_required_service(CommandRegistry)
                    settings_service = provider.get_required_service(
                        ICommandSettingsService  # type: ignore[type-abstract]
                    )

                    # Create a simple state service for commands
                    class DefaultStateService(
                        ISecureStateAccess, ISecureStateModification
                    ):
                        def __init__(self, settings_service):
                            self._settings = settings_service
                            self._routes = []

                        def get_command_prefix(self):
                            return self._settings.get_command_prefix()

                        def get_failover_routes(self):
                            return self._routes

                        def update_failover_routes(self, routes):
                            self._routes = routes

                        def get_api_key_redaction_enabled(self):
                            return self._settings.get_api_key_redaction_enabled()

                        def get_disable_interactive_commands(self):
                            return self._settings.get_disable_interactive_commands()

                        def update_command_prefix(self, prefix: str) -> None:
                            self._settings.command_prefix = prefix

                        def update_api_key_redaction(self, enabled: bool) -> None:
                            self._settings.api_key_redaction_enabled = enabled

                        def update_interactive_commands(self, enabled: bool) -> None:
                            pass

                    state_service = DefaultStateService(settings_service)

                    # Auto-register all commands from the domain command registry
                    for (
                        command_name
                    ) in domain_command_registry.get_registered_commands():
                        try:
                            command_factory = (
                                domain_command_registry.get_command_factory(
                                    command_name
                                )
                            )
                            # Instantiate the command with state services
                            command_instance = command_factory(
                                state_service, state_service
                            )
                            registry.register(command_instance)
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    f"Auto-registered domain command: {command_name}"
                                )
                        except Exception as e:
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    f"Could not register command '{command_name}': {e}"
                                )

                    if logger.isEnabledFor(logging.INFO):
                        logger.info(
                            f"Auto-registered {len(domain_command_registry.get_registered_commands())} domain commands"
                        )

                except Exception as e:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(f"Could not register domain commands: {e}")

                return None

            # Register the factory as a singleton that gets called during service provider build
            services.add_singleton(
                type(None), implementation_factory=populate_commands_factory
            )

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Registered domain commands auto-discovery factory")
        except Exception as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Could not register domain commands auto-discovery factory: {e}"
                )
