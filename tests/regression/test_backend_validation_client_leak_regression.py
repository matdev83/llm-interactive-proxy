"""Regression test for BackendStage validation HTTP client leak fix.

This test verifies that HTTP clients created during backend validation
are properly tracked and cleaned up, even when app startup fails.
"""

import contextlib

import httpx
import pytest
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig
from src.core.config.models import BackendSettings
from src.core.di.container import ServiceCollection


class TestBackendValidationClientLeakRegression:
    """Regression tests for BackendStage validation HTTP client leak fix."""

    def test_validation_client_registered_in_di(self) -> None:
        """Test that validation HTTP client is registered in DI container."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))

        services = ServiceCollection()
        services.add_instance(AppConfig, app_config)

        stage = BackendStage()

        # Register validation client
        stage._register_validation_http_client(services)

        # Get the client from DI
        provider = services.build_service_provider()
        client = provider.get_service(httpx.AsyncClient)

        # Client should be registered
        assert (
            client is not None
        ), "Validation HTTP client was not registered in DI container"
        assert isinstance(
            client, httpx.AsyncClient
        ), f"Expected httpx.AsyncClient, got {type(client)}"

    @pytest.mark.asyncio
    async def test_validation_client_reuses_existing(self) -> None:
        """Test that validation client reuses existing client if already registered."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))

        services = ServiceCollection()
        services.add_instance(AppConfig, app_config)

        # Pre-register a client
        existing_client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )
        services.add_instance(httpx.AsyncClient, existing_client)

        stage = BackendStage()

        # Register validation client (should reuse existing)
        stage._register_validation_http_client(services)

        # Get the client from DI
        provider = services.build_service_provider()
        client = provider.get_service(httpx.AsyncClient)

        # Should be the same instance
        assert (
            client is existing_client
        ), "Validation client should reuse existing client instead of creating new one"

        # Cleanup
        await existing_client.aclose()

    @pytest.mark.asyncio
    async def test_validation_client_tracked_for_cleanup(self) -> None:
        """Test that validation client is tracked for cleanup on stage failure."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))

        clients_created = []

        try:
            # Simulate scenario: validation runs but app startup fails
            for _i in range(3):
                services = ServiceCollection()
                services.add_instance(AppConfig, app_config)

                stage = BackendStage()

                # Register validation client
                stage._register_validation_http_client(services)

                # Get the client from DI
                provider = services.build_service_provider()
                client = provider.get_service(httpx.AsyncClient)

                if client is not None:
                    clients_created.append(client)

                # Verify client is tracked in stage
                assert hasattr(
                    stage, "_validation_client"
                ), "Stage should track validation client for cleanup"
                assert (
                    stage._validation_client is client
                ), "Stage should track the same client instance"

            # Verify clients were created
            assert len(clients_created) > 0, "No validation clients were created"

            # Verify clients are not closed yet (simulating startup failure)
            closed_count = sum(1 for c in clients_created if c.is_closed)
            assert (
                closed_count == 0
            ), "Clients should not be closed yet (simulating startup failure scenario)"

        finally:
            # Manual cleanup
            for client in clients_created:
                if not client.is_closed:
                    with contextlib.suppress(Exception):
                        await client.aclose()
