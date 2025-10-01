import time

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.services.tool_call_reactor_middleware import ToolCallReactorMiddleware


@pytest.mark.asyncio
async def test_tool_call_reactor_handlers_are_wired_up():
    """
    Integration test to ensure that all default tool call reactor handlers
    are correctly registered in the dependency injection container.
    """
    # Arrange
    config = AppConfig()
    builder = ApplicationBuilder().add_default_stages()

    # Act
    app = await builder.build(config)
    time.sleep(0.1)  # Allow time for handlers to register
    service_provider = app.state.service_provider
    reactor_middleware = service_provider.get_required_service(
        ToolCallReactorMiddleware
    )

    registered_handlers = reactor_middleware.get_registered_handlers()

    # Assert
    assert "config_steering_handler" in registered_handlers
    assert "dangerous_command_handler" in registered_handlers
    assert "pytest_compression_handler" in registered_handlers

    # Also test the service directly
    from src.core.services.tool_call_reactor_service import ToolCallReactorService

    reactor_service = service_provider.get_required_service(ToolCallReactorService)
    service_handlers = reactor_service.get_registered_handlers()
    assert "config_steering_handler" in service_handlers
    assert "dangerous_command_handler" in service_handlers
    assert "pytest_compression_handler" in service_handlers
