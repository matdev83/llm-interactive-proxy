"""
Tests for ServiceCollection resource lifecycle management.

Verifies that:
- add_instance does NOT prematurely close httpx.AsyncClient instances when overwriting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from src.core.di.container import ServiceCollection


@pytest.mark.asyncio
async def test_add_instance_does_not_close_replaced_client() -> None:
    """Test that replacing an AsyncClient registration does not close the old client."""
    collection = ServiceCollection()
    
    # Mock clients
    client1 = MagicMock(spec=httpx.AsyncClient)
    client1.aclose = AsyncMock()
    
    client2 = MagicMock(spec=httpx.AsyncClient)
    client2.aclose = AsyncMock()

    # 1. Register client1 as instance
    collection.add_instance(httpx.AsyncClient, client1)
    
    # 2. Register client2 as instance (overwriting client1)
    collection.add_instance(httpx.AsyncClient, client2)
    
    # Verify client1 was NOT closed
    client1.aclose.assert_not_called()
    
    # Verify client2 is the current descriptor
    provider = collection.build_service_provider(run_post_build_hooks=False)
    resolved = provider.get_required_service(httpx.AsyncClient)
    assert resolved is client2

    # Cleanup
    await collection.dispose()
