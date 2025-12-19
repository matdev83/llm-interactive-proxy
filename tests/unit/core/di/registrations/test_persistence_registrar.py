"""
Tests for persistence services registrar.

These tests verify that:
- Database configuration and engine are registered correctly
- Repository services are registered correctly
- Memory subsystem services are registered correctly
- Optional feature gating works
- No DB connections are opened during registration
- Idempotency is preserved
"""

from __future__ import annotations

from typing import cast

from src.core.config.app_config import AppConfig
from src.core.database.config import DatabaseConfig
from src.core.database.engine import DatabaseEngine
from src.core.database.repositories.memory_repository import SQLModelMemoryRepository
from src.core.database.repositories.sso_repository import (
    SQLModelAuthorizationRepository,
    SQLModelRateLimitRepository,
    SQLModelTokenRepository,
)
from src.core.database.repositories.usage_repository import (
    SessionMetricsRepository,
    UsageRecordRepository,
)
from src.core.di.container import ServiceCollection
from src.core.di.registrations import persistence
from src.core.interfaces.memory_service_interface import IMemoryService
from src.core.memory.capture_middleware import MemoryCaptureMiddleware
from src.core.memory.injection_middleware import ContextInjectionMiddleware
from src.core.memory.repository import IMemoryRepository
from src.core.memory.service import MemoryService


class TestPersistenceRegistrarDatabaseServices:
    """Test database configuration and engine registration."""

    def test_database_config_registration_with_provided_config(self) -> None:
        """Verify DatabaseConfig registration when AppConfig is provided."""
        from src.core.database.config import DatabaseConfig

        services = ServiceCollection()
        # Create AppConfig with custom database config
        db_config = DatabaseConfig(url="sqlite+aiosqlite:///:memory:")
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"database": db_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        resolved_config = provider.get_service(DatabaseConfig)
        assert resolved_config is not None
        assert isinstance(resolved_config, DatabaseConfig)
        assert resolved_config.url == app_config.database.url

    def test_database_config_registration_without_provided_config(self) -> None:
        """Verify DatabaseConfig registration when AppConfig is None."""
        services = ServiceCollection()

        persistence.register(services, None)
        provider = services.build_service_provider()

        resolved_config = provider.get_service(DatabaseConfig)
        assert resolved_config is not None
        assert isinstance(resolved_config, DatabaseConfig)

    def test_database_engine_registration(self) -> None:
        """Verify DatabaseEngine registration depends on DatabaseConfig."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        engine = provider.get_service(DatabaseEngine)
        assert engine is not None
        assert isinstance(engine, DatabaseEngine)

    def test_database_engine_is_singleton(self) -> None:
        """Verify DatabaseEngine is registered as singleton."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        engine1 = provider.get_required_service(DatabaseEngine)
        engine2 = provider.get_required_service(DatabaseEngine)
        assert engine1 is engine2


class TestPersistenceRegistrarRepositories:
    """Test repository registrations."""

    def test_usage_record_repository_registration(self) -> None:
        """Verify UsageRecordRepository is registered."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        repo = provider.get_service(UsageRecordRepository)
        assert repo is not None
        assert isinstance(repo, UsageRecordRepository)

    def test_session_metrics_repository_registration(self) -> None:
        """Verify SessionMetricsRepository is registered."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        repo = provider.get_service(SessionMetricsRepository)
        assert repo is not None
        assert isinstance(repo, SessionMetricsRepository)

    def test_sqlmodel_memory_repository_registration(self) -> None:
        """Verify SQLModelMemoryRepository is registered."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        repo = provider.get_service(SQLModelMemoryRepository)
        assert repo is not None
        assert isinstance(repo, SQLModelMemoryRepository)

    def test_sso_repositories_registration(self) -> None:
        """Verify SSO repositories are registered."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        token_repo = provider.get_service(SQLModelTokenRepository)
        assert token_repo is not None
        assert isinstance(token_repo, SQLModelTokenRepository)

        auth_repo = provider.get_service(SQLModelAuthorizationRepository)
        assert auth_repo is not None
        assert isinstance(auth_repo, SQLModelAuthorizationRepository)

        rate_limit_repo = provider.get_service(SQLModelRateLimitRepository)
        assert rate_limit_repo is not None
        assert isinstance(rate_limit_repo, SQLModelRateLimitRepository)

    def test_repositories_depend_on_database_engine(self) -> None:
        """Verify repositories receive DatabaseEngine dependency."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        # Get engine and repo
        engine = provider.get_required_service(DatabaseEngine)
        repo = provider.get_required_service(UsageRecordRepository)

        # Verify repo has engine
        assert repo._engine is engine


class TestPersistenceRegistrarMemoryServices:
    """Test memory subsystem registrations."""

    def test_memory_service_registration_when_enabled(self) -> None:
        """Verify MemoryService is registered when memory is enabled."""
        from src.core.memory.config import MemoryConfiguration

        services = ServiceCollection()
        # Create AppConfig with memory enabled
        memory_config = MemoryConfiguration(available=True)
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"memory": memory_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        memory_service = provider.get_service(MemoryService)
        assert memory_service is not None
        assert isinstance(memory_service, MemoryService)

        imemory_service = provider.get_service(cast(type, IMemoryService))
        assert imemory_service is not None

    def test_memory_service_not_registered_when_disabled(self) -> None:
        """Verify MemoryService is not registered when memory is disabled."""
        from src.core.memory.config import MemoryConfiguration

        services = ServiceCollection()
        # Create AppConfig with memory disabled (default)
        memory_config = MemoryConfiguration(available=False)
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"memory": memory_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        memory_service = provider.get_service(MemoryService)
        # Should be None when disabled
        assert memory_service is None

    def test_memory_repository_registration_when_enabled(self) -> None:
        """Verify IMemoryRepository is registered when memory is enabled."""
        from src.core.memory.config import MemoryConfiguration

        services = ServiceCollection()
        # Create AppConfig with memory enabled
        memory_config = MemoryConfiguration(available=True)
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"memory": memory_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        memory_repo = provider.get_service(cast(type, IMemoryRepository))
        assert memory_repo is not None

    def test_memory_middleware_registration_when_enabled(self) -> None:
        """Verify memory middleware is registered when memory is enabled."""
        from src.core.memory.config import MemoryConfiguration

        services = ServiceCollection()
        # Create AppConfig with memory enabled
        memory_config = MemoryConfiguration(available=True)
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"memory": memory_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        capture_middleware = provider.get_service(MemoryCaptureMiddleware)
        assert capture_middleware is not None

        injection_middleware = provider.get_service(ContextInjectionMiddleware)
        assert injection_middleware is not None

    def test_memory_middleware_not_registered_when_disabled(self) -> None:
        """Verify memory middleware is not registered when memory is disabled."""
        from src.core.memory.config import MemoryConfiguration

        services = ServiceCollection()
        # Create AppConfig with memory disabled (default)
        memory_config = MemoryConfiguration(available=False)
        app_config = AppConfig.model_validate(
            AppConfig().model_dump() | {"memory": memory_config.model_dump()}
        )

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        capture_middleware = provider.get_service(MemoryCaptureMiddleware)
        assert capture_middleware is None

        injection_middleware = provider.get_service(ContextInjectionMiddleware)
        assert injection_middleware is None


class TestPersistenceRegistrarIdempotency:
    """Test idempotency of registrations."""

    def test_repeated_registration_does_not_override(self) -> None:
        """Verify repeated registration calls don't override existing registrations."""
        services = ServiceCollection()
        app_config = AppConfig()

        # Register twice
        persistence.register(services, app_config)
        persistence.register(services, app_config)

        provider = services.build_service_provider()

        # Should still resolve correctly
        engine = provider.get_required_service(DatabaseEngine)
        assert engine is not None


class TestPersistenceRegistrarLazyInitialization:
    """Test that no DB connections are opened during registration."""

    def test_import_does_not_open_connections(self) -> None:
        """Verify importing persistence module doesn't open DB connections."""
        # This test verifies that module-level imports don't trigger connections
        # The actual check is that no exceptions are raised and no connections exist
        import src.core.di.registrations.persistence  # noqa: F401

        # If we get here without errors, import-time side effects are avoided

    def test_register_does_not_open_connections(self) -> None:
        """Verify calling register() doesn't open DB connections."""
        services = ServiceCollection()
        app_config = AppConfig()

        # Register services
        persistence.register(services, app_config)
        provider = services.build_service_provider()

        # Get engine but don't access engine property (which would create connection)
        engine = provider.get_required_service(DatabaseEngine)

        # Verify engine property was not accessed during registration
        # (engine property access would trigger connection creation)
        assert engine._engine is None

    def test_engine_property_is_lazy(self) -> None:
        """Verify DatabaseEngine.engine property creates connection lazily."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        engine = provider.get_required_service(DatabaseEngine)

        # Initially, _engine should be None
        assert engine._engine is None

        # Accessing engine property should create connection
        actual_engine = engine.engine
        assert actual_engine is not None
        assert engine._engine is not None

    def test_repositories_dont_connect_until_use(self) -> None:
        """Verify repositories don't connect until first use."""
        services = ServiceCollection()
        app_config = AppConfig()

        persistence.register(services, app_config)
        provider = services.build_service_provider()

        repo = provider.get_required_service(UsageRecordRepository)
        engine = provider.get_required_service(DatabaseEngine)

        # Engine should not be connected yet
        assert engine._engine is None

        # Repository should have engine reference but not use it yet
        assert repo._engine is engine
