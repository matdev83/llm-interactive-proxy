"""
Command services initialization stage.

This stage registers command-related services:
- Command settings service
- Command policy/state helpers
- Command service
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
    - Command settings service (command configuration)
    - Command policy/state helpers
    - Command service (main command processing interface)
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

        # Register command settings service
        self._register_command_settings_service(services, config)

        # Register supporting policy/state services for commands
        self._register_command_support_services(services)

        # Register command service
        self._register_command_service(services)

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
            logger.error(f"Command services validation failed: {e}")
            return False

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

            logger.debug("Registered command settings service")
        except ImportError as e:
            logger.warning(f"Could not register command settings service: {e}")

    def _register_command_support_services(self, services: ServiceCollection) -> None:
        """Register policy, state, and pipeline helpers used by command execution."""
        from typing import cast

        try:
            from src.core.commands.pipeline import (
                CommandMatchFilter,
                CommandTailExtractor,
            )
            from src.core.interfaces.command_policy_service_interface import (
                ICommandPolicyService,
            )
            from src.core.interfaces.command_state_service_interface import (
                ICommandStateService,
            )
            from src.core.services.command_policy_service import CommandPolicyService
            from src.core.services.command_state_service import CommandStateService
            from src.core.services.session_service_impl import SessionService

            services.add_singleton(CommandTailExtractor)
            services.add_singleton(CommandMatchFilter)

            services.add_singleton(
                CommandStateService,
                implementation_factory=lambda provider: CommandStateService(
                    provider.get_required_service(SessionService)
                ),
            )
            services.add_singleton(
                cast(type, ICommandStateService),
                implementation_factory=lambda provider: provider.get_required_service(
                    CommandStateService
                ),
            )  # type: ignore[type-abstract]

            services.add_singleton(
                CommandPolicyService,
                implementation_factory=lambda provider: CommandPolicyService(
                    provider.get_required_service(AppConfig),
                    provider.get_service(cast(type, IApplicationState)),
                ),
            )
            services.add_singleton(
                cast(type, ICommandPolicyService),
                implementation_factory=lambda provider: provider.get_required_service(
                    CommandPolicyService
                ),
            )  # type: ignore[type-abstract]

            logger.debug("Registered command policy/state services")
        except Exception as exc:
            logger.warning("Could not register command support services: %s", exc)

    def _register_command_service(self, services: ServiceCollection) -> None:
        """Register command service with dependencies."""
        try:
            from typing import cast

            from src.core.commands.parser import CommandParser
            from src.core.commands.pipeline import (
                CommandMatchFilter,
                CommandTailExtractor,
            )
            from src.core.commands.service import NewCommandService
            from src.core.interfaces.command_parser_interface import ICommandParser
            from src.core.interfaces.command_policy_service_interface import (
                ICommandPolicyService,
            )
            from src.core.interfaces.command_service_interface import ICommandService
            from src.core.interfaces.command_state_service_interface import (
                ICommandStateService,
            )

            def command_service_factory(
                provider: IServiceProvider,
            ) -> NewCommandService:
                """Factory function for creating CommandService with dependencies."""
                from src.core.services.session_service_impl import SessionService

                session_service = provider.get_required_service(SessionService)
                command_parser = provider.get_required_service(CommandParser)
                app_config = provider.get_required_service(AppConfig)
                state_service: ICommandStateService = provider.get_required_service(
                    cast(type, ICommandStateService)
                )
                policy_service: ICommandPolicyService = provider.get_required_service(
                    cast(type, ICommandPolicyService)
                )
                tail_extractor = provider.get_required_service(CommandTailExtractor)
                match_filter = provider.get_required_service(CommandMatchFilter)
                app_state = provider.get_service(cast(type, IApplicationState))
                return NewCommandService(
                    session_service,
                    command_parser,
                    strict_command_detection=app_config.strict_command_detection,
                    app_state=app_state,
                    tail_extractor=tail_extractor,
                    match_filter=match_filter,
                    command_state_service=state_service,
                    command_policy_service=policy_service,
                    config=app_config,
                )

            services.add_singleton(
                NewCommandService, implementation_factory=command_service_factory
            )
            services.add_singleton(
                cast(type, ICommandService),
                implementation_factory=lambda sp: sp.get_required_service(
                    NewCommandService
                ),
            )

            services.add_singleton(CommandParser)
            services.add_singleton(cast(type, ICommandParser), CommandParser)

            logger.debug("Registered new command service and parser with dependencies")
        except Exception as e:
            logger.warning(f"Could not register command service or parser: {e}")
