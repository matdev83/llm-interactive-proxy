from unittest.mock import AsyncMock, patch

import pytest
from src.core.config.models.misc import ModelRegistryConfig
from src.core.services.model_catalog_service import ModelCatalogService
from src.core.services.model_catalog_updater import ModelCatalogUpdater


@pytest.mark.asyncio
async def test_model_catalog_updater_closes_client_on_stop():
    """Test that the internal HTTP client is closed when the updater stops."""
    config = ModelRegistryConfig(
        download_enabled=True,
        url="http://test.com",
        bootstrap_path="test",
        cache_path="test"
    )
    
    # We don't really need a functional service for this test
    catalog_service = AsyncMock(spec=ModelCatalogService)
    
    # Create our own mock HTTP client to verify it gets closed
    mock_client = AsyncMock()
    
    updater = ModelCatalogUpdater(config, catalog_service, http_client=mock_client)
    
    # Start and stop to trigger the closure
    # We patch update_now to avoid any network logic running during start
    with patch.object(updater, "update_now", new_callable=AsyncMock):
        await updater.start()
        await updater.stop()
        
    # Verify the client was closed
    mock_client.aclose.assert_called_once()
