"""Integration test for DatabaseEngine disposal during ServiceCollection cleanup.

This test verifies that DatabaseEngine.dispose() is properly called by the
DI container during shutdown, preventing connection termination errors.
"""

from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.di.container import ServiceCollection


class TestDatabaseEngineDisposal:
    """Integration tests for DatabaseEngine disposal."""

    async def test_database_engine_disposed_during_service_collection_cleanup(
        self,
    ) -> None:
        """Test that DatabaseEngine is disposed when ServiceCollection is disposed.

        This test verifies the fix for the SQLAlchemy connection termination error
        that occurred when database connections were not properly closed during
        application shutdown.
        """
        # Setup: Create ServiceCollection and register DatabaseEngine
        services = ServiceCollection()

        # Create in-memory database config
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")

        # Factory to create DatabaseEngine
        def database_engine_factory(provider) -> DatabaseEngine:
            return DatabaseEngine(config)

        # Register as singleton
        services.add_singleton(
            DatabaseEngine, implementation_factory=database_engine_factory
        )

        # Build service provider and get DatabaseEngine instance
        provider = services.build_service_provider()
        db_engine = provider.get_service(DatabaseEngine)

        # Verify engine was created
        assert db_engine is not None
        assert isinstance(db_engine, DatabaseEngine)

        # Initialize the database (creates the engine)
        await db_engine.initialize()

        # Verify engine is initialized
        assert db_engine._initialized is True
        assert db_engine._engine is not None

        # Dispose the ServiceProvider (simulates application shutdown)
        await provider.dispose()

        # Verify database engine was properly disposed
        assert db_engine._engine is None, "Engine should be None after dispose"
        assert db_engine._session_factory is None, "Session factory should be None"
        assert db_engine._initialized is False, "Initialized flag should be False"

    async def test_multiple_dispose_calls_are_safe(self) -> None:
        """Test that DatabaseEngine can be disposed multiple times safely."""
        services = ServiceCollection()
        config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")

        def database_engine_factory(provider) -> DatabaseEngine:
            return DatabaseEngine(config)

        services.add_singleton(
            DatabaseEngine, implementation_factory=database_engine_factory
        )

        provider = services.build_service_provider()
        db_engine = provider.get_service(DatabaseEngine)
        await db_engine.initialize()

        # Call dispose multiple times on provider - should not raise errors
        await provider.dispose()
        await provider.dispose()
        await provider.dispose()

        # Engine should still be in disposed state
        assert db_engine._engine is None
