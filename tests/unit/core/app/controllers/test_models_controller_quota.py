import pytest
from unittest.mock import MagicMock, AsyncMock
from fastapi import Response
from src.core.app.controllers.models_controller import list_models
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.configuration_interface import IConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.quota_status_service import get_quota_status_service

@pytest.mark.asyncio
async def test_list_models_propagates_quota_headers(monkeypatch):
    # Mock dependencies
    backend_service = MagicMock(spec=IBackendService)
    config = MagicMock(spec=IConfig)
    backend_factory = MagicMock(spec=BackendFactory)
    
    # Mock backend instance
    mock_backend = MagicMock()
    mock_backend.backend_type = "openai"
    mock_backend.initialize = AsyncMock()
    mock_backend.get_available_models = MagicMock(return_value=["gpt-4"])
    mock_backend.last_quota_headers = {"x-codex-primary-used-percent": "75.5"}
    
    backend_factory.create_backend.return_value = mock_backend
    
    # Mock backend registry
    from src.core.services.backend_registry import BackendRegistry
    mock_registry = MagicMock(spec=BackendRegistry)
    mock_registry.get_registered_backends.return_value = ["openai"]
    
    # Mock config to include functional_backends
    config.backends = MagicMock()
    config.backends.functional_backends = ["openai"]
    config.backends.openai = MagicMock()
    
    # Patch _check_backend_credentials to return True for our mock config
    monkeypatch.setattr("src.core.app.controllers.models_controller._check_backend_credentials", lambda x: True)
    
    # Patch backend_registry in models_controller
    monkeypatch.setattr("src.core.app.controllers.models_controller.backend_registry", mock_registry)
    
    # Global Quota Status Service setup
    quota_service = get_quota_status_service()
    quota_service.update_quota("openai", {"x-codex-secondary-used-percent": "10.0"})

    response = Response()
    result = await list_models(
        backend_service=backend_service,
        config=config,
        backend_factory=backend_factory,
        response=response
    )
    
    # Verify results
    assert result.data[0].id == "gpt-4"
    assert response.headers["x-codex-primary-used-percent"] == "75.5"
    assert response.headers["x-codex-secondary-used-percent"] == "10.0"
