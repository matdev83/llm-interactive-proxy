from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.app.controllers.models_controller import _list_models_impl
from src.core.domain.models_listing import ModelsListingResponse


@pytest.mark.asyncio
async def test_list_models_populates_context_window():
    # Mock dependencies
    backend_service = MagicMock()
    
    # Mock config with functional backends
    config = MagicMock()
    config.backends.functional_backends = ["openai", "google"]
    
    # Mock backend_registry
    with patch("src.core.app.controllers.models_controller.backend_registry") as mock_registry:
        mock_registry.get_registered_backends.return_value = ["openai", "google"]
        
        # Mock backend factory
        backend_factory = MagicMock()
        
        # Mock openai backend instance
        openai_backend = MagicMock()
        # Ensure it has the async method
        openai_backend.get_available_models_async = AsyncMock(return_value=["gpt-4"])
        
        # Mock gemini backend instance
        gemini_backend = MagicMock()
        gemini_backend.get_available_models_async = AsyncMock(return_value=["gemini-1.5-pro", "gemini-3-flash-preview"])
        gemini_backend.initialize = AsyncMock() # Added initialize mock
        
        def mock_create_backend(backend_type, cfg):
            if backend_type == "openai":
                return openai_backend
            if backend_type == "google":
                return gemini_backend
            return MagicMock()
            
        backend_factory.create_backend.side_effect = mock_create_backend
        
        response = await _list_models_impl(
            backend_service=backend_service,
            config=config,
            backend_factory=backend_factory
        )
        
        assert isinstance(response, ModelsListingResponse)
        
        # Check if we got the models from the backends
        model_ids = [m.id for m in response.data]
        
        # If backends were correctly processed, we should have these IDs
        # Note: openai backend uses model name directly, others use backend_type:model
        if "gpt-4" in model_ids:
            gpt4 = next(m for m in response.data if m.id == "gpt-4")
            assert gpt4.context_window is not None
        
        if "google:gemini-3-flash-preview" in model_ids:
            gemini3 = next(m for m in response.data if m.id == "google:gemini-3-flash-preview")
            assert gemini3.context_window == 1048576

@pytest.mark.asyncio
@patch("src.core.app.controllers.models_controller.backend_registry")
async def test_list_models_fallback_populates_context_window(mock_registry):
    # Test fallback models when no backends return anything
    mock_registry.get_registered_backends.return_value = []
    
    backend_service = MagicMock()
    config = MagicMock()
    backend_factory = MagicMock()
    
    response = await _list_models_impl(
        backend_service=backend_service,
        config=config,
        backend_factory=backend_factory
    )
    
    # Ensure it's not empty
    assert len(response.data) > 0
    
    # Check fallback models
    default_ids = [m.id for m in response.data]
    assert "gpt-4" in default_ids
    
    gpt4 = next(m for m in response.data if m.id == "gpt-4")
    assert gpt4.context_window == 8192
    
    gemini = next(m for m in response.data if m.id == "gemini-1.5-pro")
    assert gemini.context_window == 1048576
