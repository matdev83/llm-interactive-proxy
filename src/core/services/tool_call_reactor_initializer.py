"""
Tool Call Reactor Initializer.

This module initializes the tool call reactor with default handlers.
"""

from __future__ import annotations

import logging

from src.core.di.services import get_service_provider
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.tool_call_reactor_service import ToolCallReactorService

logger = logging.getLogger(__name__)


async def initialize_tool_call_reactor(
    provider: IServiceProvider | None = None,
) -> None:
    """Initialize the tool call reactor with default handlers.

    Args:
        provider: Optional service provider. If None, gets the global provider.
    """
    if provider is None:
        provider = get_service_provider()

    try:
        # Touch the reactor service to ensure it's constructed
        _ = provider.get_required_service(ToolCallReactorService)

        # Handlers are registered during DI setup. Nothing to do here.
        logger.info("Tool call reactor is available")

    except Exception as e:
        logger.error(f"Failed to initialize tool call reactor: {e}", exc_info=True)
        raise


def initialize_tool_call_reactor_sync(provider: IServiceProvider | None = None) -> None:
    """Synchronous wrapper for initializing the tool call reactor.

    Args:
        provider: Optional service provider. If None, gets the global provider.
    """
    import asyncio

    try:
        # Try to get the current event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If loop is running, schedule as task
            _ = loop.create_task(initialize_tool_call_reactor(provider))  # noqa: RUF006
        else:
            # Prefer asyncio.run to ensure loop is closed after execution
            asyncio.run(initialize_tool_call_reactor(provider))
    except RuntimeError:
        # No event loop, create and close a new one with asyncio.run
        asyncio.run(initialize_tool_call_reactor(provider))
