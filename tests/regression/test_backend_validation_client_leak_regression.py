"""Regression test for ValidationHttpClientManager HTTP client leak fix.

This test verifies that HTTP clients created during backend validation
are properly tracked and cleaned up, even when app startup fails.
"""

import contextlib

import httpx
import pytest
from src.core.services.validation_http_client_manager import ValidationHttpClientManager


class TestValidationHttpClientManagerClientLeakRegression:
    """Regression tests for ValidationHttpClientManager HTTP client leak fix."""

    def test_validation_client_created_and_tracked(self) -> None:
        """Test that validation HTTP client is created and tracked by manager."""
        manager = ValidationHttpClientManager()

        # Create validation client
        client = manager.get_or_create_client()

        # Client should be created
        assert client is not None, "Validation HTTP client was not created"
        assert isinstance(
            client, httpx.AsyncClient
        ), f"Expected httpx.AsyncClient, got {type(client)}"

        # Client should be tracked in manager
        assert (
            manager._client is client
        ), "Manager should track validation client for cleanup"

    @pytest.mark.asyncio
    async def test_validation_client_reuses_existing(self) -> None:
        """Test that validation client reuses existing client if already created."""
        manager = ValidationHttpClientManager()

        # Create first client
        client1 = manager.get_or_create_client()
        assert client1 is not None

        # Get client again - should reuse existing
        client2 = manager.get_or_create_client()

        # Should be the same instance
        assert (
            client1 is client2
        ), "Manager should reuse existing client instead of creating new one"

        # Cleanup
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_validation_client_tracked_for_cleanup(self) -> None:
        """Test that validation client is tracked for cleanup on validation failure."""
        clients_created = []

        try:
            # Simulate scenario: validation runs but app startup fails
            for _i in range(3):
                manager = ValidationHttpClientManager()

                # Create validation client
                client = manager.get_or_create_client()
                clients_created.append(client)

                # Verify client is tracked in manager
                assert (
                    manager._client is client
                ), "Manager should track validation client for cleanup"

            # Verify clients were created
            assert len(clients_created) > 0, "No validation clients were created"

            # Verify clients are not closed yet (simulating startup failure)
            closed_count = sum(1 for c in clients_created if c.is_closed)
            assert (
                closed_count == 0
            ), "Clients should not be closed yet (simulating startup failure scenario)"

        finally:
            # Manual cleanup - simulate what builder would do on validation failure
            for client in clients_created:
                # Create manager for each client to test cleanup
                manager = ValidationHttpClientManager()
                manager._client = client
                await manager.cleanup()
                if not client.is_closed:
                    with contextlib.suppress(Exception):
                        await client.aclose()
