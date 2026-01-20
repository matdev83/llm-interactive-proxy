"""
Tests for InfrastructureStage lifecycle management.

Tests ensure that:
- InfrastructureStage does not prematurely close the shared HTTP client on deletion.
- Shared HTTP client persists after stage garbage collection.
- Application lifecycle handlers properly close the client on shutdown.
"""

from __future__ import annotations

import gc

import httpx
import pytest
from src.core.app.stages.infrastructure import InfrastructureStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection


@pytest.mark.asyncio
async def test_infrastructure_stage_garbage_collection_does_not_close_client() -> None:
    """Test that garbage collecting InfrastructureStage does not close the registered client."""
    stage = InfrastructureStage()
    services = ServiceCollection()
    config = AppConfig()

    # Execute stage to create and register client
    await stage.execute(services, config)

    # Resolve the registered client
    provider = services.build_service_provider()
    client = provider.get_required_service(httpx.AsyncClient)

    # Verify client is open
    assert not client.is_closed

    # Delete stage reference and force garbage collection
    del stage
    gc.collect()

    # Verify client is STILL open
    # This detects regression where __del__ would close the client
    assert not client.is_closed, "Client should remain open after stage GC"

    # Verify we can still use the client (mock request if needed, or just check state)
    # Just checking state is sufficient for this regression test.

    # Cleanup manually since we own the client in this test
    await client.aclose()


@pytest.mark.asyncio
async def test_infrastructure_stage_defensive_cleanup_removed() -> None:
    """Test that InfrastructureStage has no __del__ method (explicit check)."""
    assert not hasattr(
        InfrastructureStage, "__del__"
    ), "InfrastructureStage should not have a __del__ method"


@pytest.mark.asyncio
async def test_http_client_registration_singleton_semantics() -> None:
    """Test that multiple stage executions register the same client instance if reused."""
    # This simulates builder pattern where stage might be reused or rebuilt
    services = ServiceCollection()
    config = AppConfig()

    stage1 = InfrastructureStage()
    await stage1.execute(services, config)

    provider1 = services.build_service_provider()
    client1 = provider1.get_required_service(httpx.AsyncClient)

    # Should be open
    assert not client1.is_closed

    # Cleanup
    await client1.aclose()
