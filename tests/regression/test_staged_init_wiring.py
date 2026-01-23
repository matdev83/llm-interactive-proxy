"""
Regression tests for staged initialization wiring.

This test verifies that the ApplicationBuilder correctly wires services together,
ensuring that:
1. ApplicationStateService is initialized with the correct default backend.
2. ModelReplacementService is registered and available when enabled.
3. RequestIDMiddleware is present in the middleware stack.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from src.core.app.application_builder import ApplicationBuilder
from src.core.config.app_config import AppConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.model_replacement_service_interface import IModelReplacementService
from src.core.services.application_state_service import ApplicationStateService


@pytest.mark.asyncio
async def test_application_state_initialization_wiring():
    """
    Verify that ApplicationStateService is initialized with the default backend
    during the staged build process.
    """
    # 1. Setup config with a specific default backend
    config_dict = {
        "backends": {
            "default_backend": "test-backend-123"
        }
    }
    config = AppConfig.model_validate(config_dict)
    
    # 2. Build the application
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    
    # 3. Resolve the state service from the container
    service_provider = app.state.service_provider
    app_state = service_provider.get_required_service(IApplicationState)
    
    # 4. Verify it was initialized correctly
    assert app_state.get_backend_type() == "test-backend-123"
    
    # 5. Verify it's the same instance as the concrete type registration
    concrete_state = service_provider.get_required_service(ApplicationStateService)
    assert app_state is concrete_state


@pytest.mark.asyncio
async def test_model_replacement_registration_wiring():
    """
    Verify that ModelReplacementService is registered only when enabled.
    """
    # Test case 1: Enabled
    config_enabled = AppConfig.model_validate({
        "replacement": {
            "enabled": True,
            "backend_model": "openai:gpt-4",
            "probability": 1.0
        }
    })
    
    # We need to register openai so validation passes
    from src.core.services.backend_registry import backend_registry
    if "openai" not in backend_registry.get_registered_backends():
        backend_registry.register_backend("openai", None)

    builder_enabled = ApplicationBuilder().add_default_stages()
    app_enabled = await builder_enabled.build(config_enabled)
    
    replacement_service = app_enabled.state.service_provider.get_service(IModelReplacementService)
    assert replacement_service is not None
    
    # Test case 2: Disabled
    config_disabled = AppConfig.model_validate({
        "replacement": {
            "enabled": False
        }
    })
    builder_disabled = ApplicationBuilder().add_default_stages()
    app_disabled = await builder_disabled.build(config_disabled)
    
    replacement_service_none = app_disabled.state.service_provider.get_service(IModelReplacementService)
    assert replacement_service_none is None


@pytest.mark.asyncio
async def test_middleware_stack_contains_request_id():
    """
    Verify that the RequestIDMiddleware is present in the application's middleware stack.
    """
    from src.core.app.middleware.request_id_middleware import RequestIDMiddleware
    
    config = AppConfig.model_validate({})
    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(config)
    
    # Check middleware list
    # In FastAPI/Starlette, middlewares are stored in app.user_middleware
    middleware_types = [m.cls for m in app.user_middleware]
    assert RequestIDMiddleware in middleware_types
