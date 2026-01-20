"""Regression test for Antigravity OAuth HTTP client leak fix.

This test verifies that AntigravityOAuthConnector properly cleans up
custom HTTP clients during shutdown.
"""

import contextlib

import httpx
import pytest
from src.connectors.antigravity_oauth import AntigravityOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.config.models import BackendSettings
from src.core.services.translation_service import TranslationService


class TestAntigravityOAuthClientLeakRegression:
    """Regression tests for Antigravity OAuth HTTP client leak fix."""

    @pytest.mark.asyncio
    async def test_shutdown_closes_custom_clients(self) -> None:
        """Test that shutdown() properly closes custom HTTP clients."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))
        translation_service = TranslationService()

        connectors_created = []
        clients_created = []

        try:
            # Create multiple connectors to simulate multiple backend instances
            for _i in range(3):
                # Create a shared HTTP client (simulating DI container)
                shared_client = httpx.AsyncClient(
                    http2=False,
                    timeout=httpx.Timeout(
                        connect=10.0, read=60.0, write=60.0, pool=60.0
                    ),
                    limits=httpx.Limits(
                        max_connections=100, max_keepalive_connections=20
                    ),
                    trust_env=False,
                )

                connector = AntigravityOAuthConnector(
                    client=shared_client,
                    config=app_config,
                    translation_service=translation_service,
                )

                # Initialize connector (may create custom client)
                with contextlib.suppress(Exception):
                    await connector.initialize()

                connectors_created.append(connector)

                # Track custom clients if they exist
                if (
                    hasattr(connector, "client")
                    and connector.client is not None
                    and hasattr(connector, "_owns_custom_client")
                    and connector._owns_custom_client
                ):
                    clients_created.append(connector.client)

            # Verify shutdown method exists
            assert hasattr(
                connectors_created[0], "shutdown"
            ), "shutdown() method is missing - this would cause a memory leak!"

            # Test shutdown
            for connector in connectors_created:
                if hasattr(connector, "shutdown"):
                    await connector.shutdown()

            # Verify all custom clients are closed
            closed_count = sum(1 for c in clients_created if c.is_closed)
            assert closed_count == len(clients_created), (
                f"Not all custom HTTP clients were closed. "
                f"Expected {len(clients_created)} closed, got {closed_count}. "
                "This indicates a memory leak."
            )

        finally:
            # Manual cleanup for any remaining clients
            for connector in connectors_created:
                if hasattr(connector, "shutdown"):
                    with contextlib.suppress(Exception):
                        await connector.shutdown()

            # Also close shared clients
            for connector in connectors_created:
                if (
                    hasattr(connector, "client")
                    and connector.client is not None
                    and not connector.client.is_closed
                ):
                    with contextlib.suppress(Exception):
                        await connector.client.aclose()

    @pytest.mark.asyncio
    async def test_shutdown_method_exists(self) -> None:
        """Test that shutdown() method exists on connector."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))
        translation_service = TranslationService()

        shared_client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )

        connector = AntigravityOAuthConnector(
            client=shared_client,
            config=app_config,
            translation_service=translation_service,
        )

        try:
            # Verify shutdown method exists
            assert hasattr(
                connector, "shutdown"
            ), "shutdown() method is missing - this would cause a memory leak!"
            assert callable(connector.shutdown), "shutdown() is not callable"

            # Verify shutdown can be called without error
            await connector.shutdown()
        finally:
            if not shared_client.is_closed:
                await shared_client.aclose()

    @pytest.mark.asyncio
    async def test_initialize_does_not_close_shared_client(self) -> None:
        """Ensure initialize keeps the shared client open."""
        app_config = AppConfig(backends=BackendSettings(default_backend=""))
        translation_service = TranslationService()

        shared_client = httpx.AsyncClient(
            http2=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=60.0, pool=60.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
            trust_env=False,
        )

        connector = AntigravityOAuthConnector(
            client=shared_client,
            config=app_config,
            translation_service=translation_service,
        )

        try:
            with contextlib.suppress(Exception):
                await connector.initialize()
            assert not shared_client.is_closed
        finally:
            with contextlib.suppress(Exception):
                await connector.shutdown()
            if not shared_client.is_closed:
                await shared_client.aclose()
