"""Integration test for DatabaseEngine disposal during full application shutdown.

This test verifies that the DatabaseEngine is properly disposed when the
application lifecycle shutdown is triggered, preventing connection termination
errors.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.lifecycle import AppLifecycle
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.di.container import ServiceCollection


class TestDatabaseDisposalOnAppShutdown:
    """Integration tests for database disposal during application shutdown."""

    async def test_database_engine_disposed_during_app_shutdown(self) -> None:
        """Test that DatabaseEngine is disposed when AppLifecycle.shutdown() is called.

        This simulates the real application shutdown flow where the lifecycle
        shutdown should dispose the service provider, which should then dispose
        the DatabaseEngine, preventing connection termination errors.
        """
        # Setup: Create a mock FastAPI app with service provider
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Create ServiceCollection and register DatabaseEngine
        services = ServiceCollection()
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")

        def database_engine_factory(provider) -> DatabaseEngine:
            return DatabaseEngine(config)

        services.add_singleton(
            DatabaseEngine, implementation_factory=database_engine_factory
        )

        # Build service provider
        provider = services.build_service_provider()
        mock_app.state.service_provider = provider

        # Get and initialize the database engine
        db_engine = provider.get_service(DatabaseEngine)
        await db_engine.initialize()

        # Verify engine is initialized
        assert db_engine._initialized is True
        assert db_engine._engine is not None

        # Create lifecycle and trigger shutdown
        lifecycle = AppLifecycle(mock_app, config={})

        # Mock out other shutdown operations to isolate database disposal
        lifecycle._stop_eos_subscribers = AsyncMock()
        lifecycle._stop_memory_services = AsyncMock()
        lifecycle._stop_usage_tracking_services = AsyncMock()
        lifecycle._stop_model_catalog_updater = AsyncMock()
        lifecycle._stop_background_tasks = AsyncMock()
        lifecycle._close_connections = AsyncMock()

        # Trigger shutdown
        await lifecycle.shutdown()

        # Verify database engine was properly disposed
        assert db_engine._engine is None, "Engine should be None after shutdown"
        assert (
            db_engine._session_factory is None
        ), "Session factory should be None after shutdown"
        assert (
            db_engine._initialized is False
        ), "Initialized flag should be False after shutdown"

    async def test_dispose_service_provider_logs_success(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that _dispose_service_provider logs success message."""
        # Setup
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        services = ServiceCollection()
        provider = services.build_service_provider()
        mock_app.state.service_provider = provider

        lifecycle = AppLifecycle(mock_app, config={})

        # Enable INFO logging
        with caplog.at_level(logging.INFO):
            await lifecycle._dispose_service_provider()

        # Verify success message was logged
        assert any(
            "Service provider disposed successfully" in record.message
            for record in caplog.records
        )

    async def test_dispose_service_provider_handles_missing_provider(
        self,
    ) -> None:
        """Test that _dispose_service_provider handles missing provider gracefully."""
        # Setup with no provider
        mock_app = MagicMock()
        mock_app.state = MagicMock(spec=[])  # No service_provider attribute

        lifecycle = AppLifecycle(mock_app, config={})

        # Should not raise error
        await lifecycle._dispose_service_provider()

    async def test_dispose_service_provider_handles_dispose_error(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that _dispose_service_provider logs error if dispose fails."""
        # Setup
        mock_app = MagicMock()
        mock_app.state = MagicMock()

        # Create a mock provider that raises error on dispose
        mock_provider = MagicMock()
        mock_provider.dispose = AsyncMock(side_effect=RuntimeError("Dispose failed"))
        mock_app.state.service_provider = mock_provider

        lifecycle = AppLifecycle(mock_app, config={})

        # Enable WARNING logging
        with caplog.at_level(logging.WARNING):
            # Should not raise error, but log warning
            await lifecycle._dispose_service_provider()

        # Verify warning was logged
        assert any(
            "Error disposing service provider" in record.message
            for record in caplog.records
        )
