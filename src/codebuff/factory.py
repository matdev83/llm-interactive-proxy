"""
Factory for creating Codebuff WebSocket server instances.

This module provides factory functions to create and configure the Codebuff
WebSocket server with all its dependencies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.codebuff.connection_manager import ConnectionManager
from src.codebuff.format_converter import FormatConverter
from src.codebuff.handlers.init_handler import InitHandler
from src.codebuff.handlers.prompt_handler import PromptHandler
from src.codebuff.handlers.subscription_handler import SubscriptionHandler
from src.codebuff.message_router import MessageRouter
from src.codebuff.server import CodebuffWebSocketServer

if TYPE_CHECKING:
    from src.core.config.app_config import AppConfig
    from src.core.interfaces.di_interface import IServiceProvider

logger = logging.getLogger(__name__)


def create_codebuff_server(
    config: AppConfig, service_provider: IServiceProvider
) -> CodebuffWebSocketServer:
    """Create a Codebuff WebSocket server instance.

    This factory function creates and wires up all the components needed for
    the Codebuff WebSocket server, including:
    - Connection manager
    - Format converter
    - Message router
    - Action handlers (prompt, init, subscription)
    - WebSocket server

    Args:
        config: Application configuration
        service_provider: Service provider for resolving dependencies

    Returns:
        Configured CodebuffWebSocketServer instance
    """

    if logger.isEnabledFor(logging.INFO):

        logger.info("Creating Codebuff WebSocket server")
    # Create connection manager
    connection_manager = ConnectionManager(
        heartbeat_timeout_seconds=config.codebuff.heartbeat_timeout_seconds
    )

    # Create format converter
    format_converter = FormatConverter()

    # Get backend service from service provider (routes through shared orchestrator)
    from src.core.services.backend_service import BackendService

    backend_service = service_provider.get_required_service(BackendService)

    # Create handlers
    prompt_handler = PromptHandler(
        backend_service=backend_service,
        format_converter=format_converter,
        connection_manager=connection_manager,
    )

    init_handler = InitHandler(connection_manager=connection_manager)

    subscription_handler = SubscriptionHandler(connection_manager=connection_manager)

    # Create message router
    message_router = MessageRouter()

    # Get optional services for session metrics and termination reporting
    from src.core.interfaces.client_end_of_session_service_interface import (
        IClientEndOfSessionService,
    )
    from src.core.interfaces.session_metrics_initializer_interface import (
        ISessionMetricsInitializer,
    )

    metrics_initializer = None
    try:
        metrics_initializer = service_provider.get_service(ISessionMetricsInitializer)  # type: ignore[type-abstract]
    except (KeyError, AttributeError, TypeError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Session metrics initializer not available in DI: %s", e, exc_info=True
            )

    client_eos_service = None
    try:
        client_eos_service = service_provider.get_service(IClientEndOfSessionService)  # type: ignore[type-abstract]
    except (KeyError, AttributeError, TypeError) as e:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Client end-of-session service not available in DI: %s",
                e,
                exc_info=True,
            )

    # Create WebSocket server
    server = CodebuffWebSocketServer(
        connection_manager=connection_manager,
        message_router=message_router,
        prompt_handler=prompt_handler,
        init_handler=init_handler,
        subscription_handler=subscription_handler,
        config=config.codebuff,
        metrics_initializer=metrics_initializer,
        client_eos_service=client_eos_service,
    )

    if logger.isEnabledFor(logging.INFO):

        logger.info("Codebuff WebSocket server created successfully")
    return server
