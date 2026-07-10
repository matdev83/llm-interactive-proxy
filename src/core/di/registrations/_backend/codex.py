"""Codex connector component registration.

Registers Codex connector component services for dependency injection.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import httpx

from src.core.di.container import ServiceCollection
from src.core.di.registrations._shared import register_singleton_if_absent
from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def register_codex_services(services: ServiceCollection) -> None:
    """Register Codex connector component services.

    This function registers:
    - Component service interfaces and implementations
    - CodexConnectorDependencies factory

    Args:
        services: The service collection to register into
    """
    from src.connectors.openai_codex.catalog.interfaces import ICodexModelCatalog
    from src.connectors.openai_codex.contracts import CodexConnectorDependencies
    from src.connectors.openai_codex.credentials import CredentialManager
    from src.connectors.openai_codex.interfaces import (
        ICredentialManager,
        ISettingsLoader,
        IToolExecutionService,
    )
    from src.connectors.openai_codex.settings import SettingsLoader
    from src.connectors.openai_codex.tools import ToolExecutionService
    from src.core.interfaces.notification_service_interface import (
        INotificationService,
    )

    # Register SettingsLoader
    register_singleton_if_absent(services, SettingsLoader)
    register_singleton_if_absent(
        services,
        ISettingsLoader,
        implementation_factory=lambda p: p.get_required_service(SettingsLoader),
    )

    # Register CredentialManager (requires httpx.AsyncClient)
    def _credential_manager_factory(
        provider: IServiceProvider,
    ) -> CredentialManager:
        http_client = provider.get_required_service(httpx.AsyncClient)
        notification_service = cast(
            INotificationService | None,
            provider.get_service(cast(type[Any], INotificationService)),
        )
        return CredentialManager(
            http_client,
            notification_service=notification_service,
        )

    register_singleton_if_absent(
        services,
        CredentialManager,
        implementation_factory=_credential_manager_factory,
    )
    register_singleton_if_absent(
        services,
        ICredentialManager,
        implementation_factory=lambda p: p.get_required_service(CredentialManager),
    )

    # Register ToolExecutionService
    register_singleton_if_absent(services, ToolExecutionService)
    register_singleton_if_absent(
        services,
        IToolExecutionService,
        implementation_factory=lambda p: p.get_required_service(ToolExecutionService),
    )

    # Register CodexConnectorDependencies factory
    # Note: PayloadBuilder, ResponseExecutor, and CompatibilityLayer
    # require connector reference, so they are created per-connector instance
    # The factory provides None for these, allowing connector to create them
    def _codex_dependencies_factory(
        provider: IServiceProvider,
    ) -> CodexConnectorDependencies:
        """Factory for CodexConnectorDependencies bundle.

        Returns a bundle with components that don't require connector reference.
        Components that need connector reference (PayloadBuilder, ResponseExecutor,
        CompatibilityLayer) are set to None and will be created by the connector.
        """
        settings_loader = cast(
            ISettingsLoader | None,
            provider.get_service(cast(type[Any], ISettingsLoader)),
        )
        credential_manager = cast(
            ICredentialManager | None,
            provider.get_service(cast(type[Any], ICredentialManager)),
        )
        tool_execution_service = cast(
            IToolExecutionService | None,
            provider.get_service(cast(type[Any], IToolExecutionService)),
        )
        model_catalog = cast(
            "ICodexModelCatalog | None",
            provider.get_service(cast(type[Any], ICodexModelCatalog)),
        )

        return CodexConnectorDependencies(
            settings_loader=settings_loader,
            credential_manager=credential_manager,
            payload_builder=None,  # Created by connector instance
            response_executor=None,  # Created by connector instance
            compatibility_layer=None,  # Created by connector instance
            tool_execution_service=tool_execution_service,
            model_catalog=model_catalog,
        )

    register_singleton_if_absent(
        services,
        CodexConnectorDependencies,
        implementation_factory=_codex_dependencies_factory,
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Registered Codex connector component services")
