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
        logger.info("Initializing command services...")

        # Register command registry
        self._register_command_registry(services)

        # Register command settings service
        self._register_command_settings_service(services, config)

        # Register command service
        self._register_command_service(services)

        # Register domain commands
        self._register_domain_commands(services)

        logger.info("Command services initialized successfully")

    def _register_command_registry(self, services: ServiceCollection) -> None:
        """Register command registry as singleton."""
        try:
            from src.core.services.command_service import CommandRegistry

            # Register as singleton (no dependencies)
            services.add_singleton(CommandRegistry)

            logger.debug("Registered command registry")
        except ImportError as e:
            logger.warning(f"Could not register command registry: {e}")

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
            from typing import cast

            services.add_instance(cast(type, ICommandSettingsService), cmd_settings)

            logger.debug("Registered command settings service")
        except ImportError as e:
            logger.warning(f"Could not register command settings service: {e}")

    def _register_command_service(self, services: ServiceCollection) -> None:
        """Register command service with dependencies."""
        try:
            from src.core.interfaces.command_service_interface import ICommandService
            from src.core.interfaces.session_service_interface import ISessionService
            from src.core.services.command_service import CommandService

            def command_service_factory(provider: IServiceProvider) -> CommandService:
                """Factory function for creating CommandService with dependencies."""
                from typing import cast

                from src.core.services.command_service import CommandRegistry

                registry = provider.get_required_service(CommandRegistry)
                session_service: ISessionService = provider.get_required_service(
                    cast(type, ISessionService)
                )
                return CommandService(registry, session_service)

            # Register concrete implementation
            services.add_singleton(
                CommandService, implementation_factory=command_service_factory
            )

            # Register interface binding
            from typing import cast

            services.add_singleton(
                cast(type, ICommandService),
                implementation_factory=command_service_factory,
            )

            logger.debug("Registered command service with dependencies")
        except ImportError as e:
            logger.warning(f"Could not register command service: {e}")

    def _register_domain_commands(self, services: ServiceCollection) -> None:
        """Register domain command implementations with the registry."""
        try:
            # Register a factory that will register commands with the registry after it's built
            def register_commands_factory(
                provider: IServiceProvider,
            ) -> _CommandRegistrationMarker:
                """Factory function that registers domain commands during service provider build."""
                try:
                    # Get the command registry from the service provider
                    from src.core.services.command_service import CommandRegistry

                    registry = provider.get_required_service(CommandRegistry)

                    # Register domain command implementations
                    from src.core.commands.set_command import SetCommand
                    from src.core.commands.unset_command import UnsetCommand

                    registry.register(SetCommand())
                    registry.register(UnsetCommand())

                    logger.debug("Registered domain commands")
                except Exception as e:
                    logger.warning(f"Could not register domain commands: {e}")

                return (
                    _CommandRegistrationMarker()
                )  # Return an instance of the marker class

            # Register the factory to run during service provider build
            # We use a dummy type since this factory doesn't return a service
            class _CommandRegistrationMarker:
                pass

            services.add_singleton(
                _CommandRegistrationMarker,
                implementation_factory=register_commands_factory,
            )

        except ImportError as e:
            logger.warning(f"Could not register domain commands: {e}")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that command services can be registered."""
        try:
            # Check that required modules are available

            # Validate config has command settings
            if not hasattr(config, "command_prefix"):
                logger.warning("Config missing command_prefix")

            return True
        except ImportError as e:
            logger.error(f"Command services validation failed: {e}")
            return False
