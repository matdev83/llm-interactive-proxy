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

        logger.info("Command services initialized successfully")

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

    def _register_command_registry(self, services: ServiceCollection) -> None:
        """Register the CommandRegistry service for backward compatibility."""
        try:
            from src.core.services.command_service import CommandRegistry

            # Register CommandRegistry as singleton
            services.add_singleton(CommandRegistry)
            logger.debug("Registered CommandRegistry service")
        except ImportError as e:
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
            from typing import cast

            services.add_instance(cast(type, ICommandSettingsService), cmd_settings)

            logger.debug("Registered command settings service")
        except ImportError as e:
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
                return NewCommandService(session_service, command_parser)

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

            logger.debug("Registered new command service and parser with dependencies")
        except Exception as e:
            logger.warning(f"Could not register command service or parser: {e}")
