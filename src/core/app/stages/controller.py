"""
Controller services initialization stage.

This stage registers FastAPI controller services:
- Chat controller
- Anthropic controller
- Models controller
- Usage controller
"""

from __future__ import annotations

import logging

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider

from .base import InitializationStage

logger = logging.getLogger(__name__)


class ControllerStage(InitializationStage):
    """
    Stage for registering FastAPI controller services.

    This stage registers:
    - Chat controller (main chat completions endpoint)
    - Anthropic controller (Anthropic-compatible endpoints)
    - Models controller (model listing endpoints)
    - Usage controller (usage tracking endpoints)
    """

    @property
    def name(self) -> str:
        return "controllers"

    def get_dependencies(self) -> list[str]:
        return ["processors"]

    def get_description(self) -> str:
        return "Register FastAPI controller services"

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Register controller services."""
        if logger.isEnabledFor(logging.INFO):
            logger.info("Initializing controller services...")

        # Register chat controller
        self._register_chat_controller(services)

        # Register anthropic controller
        self._register_anthropic_controller(services)

        # Register models controller
        self._register_models_controller(services)

        # Register usage controller
        self._register_usage_controller(services)

        # Register responses controller
        self._register_responses_controller(services)

        if logger.isEnabledFor(logging.INFO):
            logger.info("Controller services initialized successfully")

    def _register_chat_controller(self, services: ServiceCollection) -> None:
        """Register chat controller with request processor dependency."""
        from src.core.app.controllers.chat_controller import ChatController
        from src.core.interfaces.request_processor_interface import IRequestProcessor

        def chat_controller_factory(provider: IServiceProvider) -> ChatController:
            """Factory function for creating ChatController."""
            from typing import cast

            request_processor: IRequestProcessor = provider.get_required_service(
                cast(type, IRequestProcessor)
            )
            translation_service = (
                ChatController._resolve_translation_service_from_provider(provider)
            )
            return ChatController(
                request_processor,
                translation_service=translation_service,
            )

        # Register as singleton
        services.add_singleton(
            ChatController, implementation_factory=chat_controller_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered chat controller")

    def _register_anthropic_controller(self, services: ServiceCollection) -> None:
        """Register anthropic controller with request processor dependency."""
        from src.core.app.controllers.anthropic_controller import AnthropicController
        from src.core.interfaces.request_processor_interface import IRequestProcessor

        def anthropic_controller_factory(
            provider: IServiceProvider,
        ) -> AnthropicController:
            """Factory function for creating AnthropicController."""
            from typing import cast

            request_processor: IRequestProcessor = provider.get_required_service(
                cast(type, IRequestProcessor)
            )
            return AnthropicController(request_processor)

        # Register as singleton
        services.add_singleton(
            AnthropicController, implementation_factory=anthropic_controller_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered anthropic controller")

    def _register_models_controller(self, services: ServiceCollection) -> None:
        """Register models controller with backend service dependency."""
        from src.core.app.controllers.models_controller import ModelsController
        from src.core.interfaces.backend_service_interface import IBackendService

        def models_controller_factory(provider: IServiceProvider) -> ModelsController:
            """Factory function for creating ModelsController."""
            from typing import cast

            backend_service: IBackendService = provider.get_required_service(
                cast(type, IBackendService)
            )
            return ModelsController(backend_service)

        # Register as singleton
        services.add_singleton(
            ModelsController, implementation_factory=models_controller_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered models controller")

    def _register_usage_controller(self, services: ServiceCollection) -> None:
        """Register usage controller with usage tracking dependency."""
        from src.core.app.controllers.usage_controller import UsageController
        from src.core.interfaces.usage_tracking_interface import IUsageTrackingService

        def usage_controller_factory(provider: IServiceProvider) -> UsageController:
            """Factory function for creating UsageController."""
            from typing import cast

            # Usage tracking service is optional
            usage_service: IUsageTrackingService | None = provider.get_service(
                cast(type, IUsageTrackingService)
            )
            return UsageController(usage_service)

        # Register as singleton
        services.add_singleton(
            UsageController, implementation_factory=usage_controller_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered usage controller")

    def _register_responses_controller(self, services: ServiceCollection) -> None:
        """Register responses controller with request processor dependency."""
        from src.core.app.controllers.responses_controller import ResponsesController
        from src.core.interfaces.request_processor_interface import IRequestProcessor

        def responses_controller_factory(
            provider: IServiceProvider,
        ) -> ResponsesController:
            """Factory function for creating ResponsesController."""
            from typing import cast

            from src.core.interfaces.translation_service_interface import (
                ITranslationService,
            )
            from src.core.services.translation_service import TranslationService

            request_processor: IRequestProcessor = provider.get_required_service(
                cast(type, IRequestProcessor)
            )
            translation_service = provider.get_service(cast(type, ITranslationService))
            if translation_service is None:
                translation_service = provider.get_service(TranslationService)
            if translation_service is None:
                from src.core.common.exceptions import InitializationError

                raise InitializationError(
                    "TranslationService is not registered in the service provider"
                )

            return ResponsesController(
                request_processor,
                translation_service=translation_service,
            )

        # Register as singleton
        services.add_singleton(
            ResponsesController, implementation_factory=responses_controller_factory
        )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered responses controller")

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Validate that controller services can be registered."""
        try:
            # Check that required modules are available

            # Models and usage controllers are optional
            try:
                from src.core.app.controllers.models_controller import ModelsController
                from src.core.app.controllers.usage_controller import UsageController

                # Use the imports to avoid unused import warnings
                _ = ModelsController
                _ = UsageController
            except ImportError:
                if logger.isEnabledFor(logging.INFO):
                    logger.info("Optional controllers (models, usage) not available")

            return True
        except ImportError as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Controller services validation failed: {e}")
            return False
