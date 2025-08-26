"""
Tests for Base Stage.

This module provides comprehensive test coverage for the testing base stage
that prevents coroutine warning issues through validation.
"""

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.session_service_interface import ISessionService
from src.core.testing.base_stage import (
    BackendServiceTestStage,
    GuardedMockCreationMixin,
    SessionServiceTestStage,
    ValidatedTestStage,
)


class TestValidatedTestStage:
    """Tests for ValidatedTestStage class."""

    class ConcreteValidatedTestStage(ValidatedTestStage):
        """Concrete implementation of ValidatedTestStage for testing."""

        @property
        def name(self) -> str:
            return "test_validated_stage"

        def get_dependencies(self) -> list[str]:
            return []

        def get_description(self) -> str:
            return "Test validated stage for unit testing"

        async def _register_services(
            self, services: ServiceCollection, config: AppConfig
        ) -> None:
            """Empty implementation for testing."""

    @pytest.fixture
    def stage(self) -> ConcreteValidatedTestStage:
        """Create a ConcreteValidatedTestStage instance."""
        return self.ConcreteValidatedTestStage()

    @pytest.fixture
    def services(self) -> ServiceCollection:
        """Create a ServiceCollection instance."""
        return ServiceCollection()

    @pytest.fixture
    def config(self) -> AppConfig:
        """Create a test AppConfig instance."""
        from src.core.config.app_config import (
            AppConfig,
            AuthConfig,
            BackendConfig,
            BackendSettings,
        )

        return AppConfig(
            host="localhost",
            port=9000,
            backends=BackendSettings(
                default_backend="openai", openai=BackendConfig(api_key=["test_key"])
            ),
            auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
        )

    def test_initialization(self, stage: ConcreteValidatedTestStage) -> None:
        """Test ValidatedTestStage initialization."""
        assert stage._registered_services == {}
        assert hasattr(stage, "_register_services")

    def test_name_property_implemented(self, stage: ConcreteValidatedTestStage) -> None:
        """Test that name property returns the correct value."""
        assert stage.name == "test_validated_stage"

    def test_get_dependencies_default(self, stage: ConcreteValidatedTestStage) -> None:
        """Test default get_dependencies implementation."""
        assert stage.get_dependencies() == []

    def test_get_description_implemented(
        self, stage: ConcreteValidatedTestStage
    ) -> None:
        """Test that get_description returns the correct value."""
        assert stage.get_description() == "Test validated stage for unit testing"

    @pytest.mark.asyncio
    async def test_execute_with_implemented_register_services(
        self,
        stage: ConcreteValidatedTestStage,
        services: ServiceCollection,
        config: AppConfig,
    ) -> None:
        """Test execute with implemented _register_services method."""
        # Should not raise any exception since _register_services is implemented
        await stage.execute(services, config)

        # Should have logged the execution
        # (We can't easily test log output in this context, but we can verify no exception was raised)

    def test_safe_register_instance_basic(
        self, stage: ConcreteValidatedTestStage, services: ServiceCollection
    ) -> None:
        """Test safe_register_instance with basic service."""
        mock_service = MagicMock()

        # Should not raise any exception
        stage.safe_register_instance(services, object, mock_service)

        # Service should be registered
        assert object in stage._registered_services
        assert stage._registered_services[object] == mock_service

    def test_safe_register_instance_with_validation_disabled(
        self, stage: ConcreteValidatedTestStage, services: ServiceCollection
    ) -> None:
        """Test safe_register_instance with validation disabled."""
        mock_service = MagicMock()

        stage.safe_register_instance(services, object, mock_service, validate=False)

        # Service should still be registered
        assert object in stage._registered_services

    def test_safe_register_singleton_with_factory(
        self, stage: ConcreteValidatedTestStage, services: ServiceCollection
    ) -> None:
        """Test safe_register_singleton with factory function."""

        def factory() -> object:
            return object()

        stage.safe_register_singleton(services, object, implementation_factory=factory)

        # Should not raise any exception
        assert True

    def test_safe_register_singleton_with_type(
        self, stage: ConcreteValidatedTestStage, services: ServiceCollection
    ) -> None:
        """Test safe_register_singleton with implementation type."""
        stage.safe_register_singleton(services, object, implementation_type=object)

        # Should not raise any exception
        assert True

    def test_safe_register_singleton_no_args(
        self, stage: ConcreteValidatedTestStage, services: ServiceCollection
    ) -> None:
        """Test safe_register_singleton with no additional args."""
        stage.safe_register_singleton(services, object)

        # Should not raise any exception
        assert True

    def test_create_safe_session_service_mock(
        self, stage: ConcreteValidatedTestStage
    ) -> None:
        """Test create_safe_session_service_mock method."""
        mock_service = stage.create_safe_session_service_mock()

        assert mock_service is not None
        assert hasattr(mock_service, "get_session")

    def test_create_safe_backend_service_mock(
        self, stage: ConcreteValidatedTestStage
    ) -> None:
        """Test create_safe_backend_service_mock method."""
        mock_service = stage.create_safe_backend_service_mock()

        assert mock_service is not None
        assert hasattr(mock_service, "call_completion")

    def test_validate_service_instance_with_session_service(
        self, stage: ConcreteValidatedTestStage, caplog
    ) -> None:
        """Test _validate_service_instance with session service."""
        mock_service = stage.create_safe_session_service_mock()

        # Should not raise exception and should not log errors
        with caplog.at_level(logging.ERROR):
            stage._validate_service_instance(ISessionService, mock_service)

        # Should not have any error logs
        assert not any("ERROR" in record.message for record in caplog.records)

    def test_validate_service_instance_with_async_mock_session_service(
        self, stage: ConcreteValidatedTestStage, caplog
    ) -> None:
        """Test _validate_service_instance with problematic session service."""
        mock_service = AsyncMock(spec=ISessionService)

        with caplog.at_level(logging.ERROR):
            stage._validate_service_instance(ISessionService, mock_service)

        # Should log error about AsyncMock
        assert any("AsyncMock" in record.message for record in caplog.records)

    def test_validate_service_instance_with_async_mock_sync_method(
        self, stage: ConcreteValidatedTestStage, caplog
    ) -> None:
        """Test _validate_service_instance with AsyncMock sync method."""
        mock_service = MagicMock()
        mock_service.get_session = AsyncMock()  # This is problematic

        with caplog.at_level(logging.ERROR):
            stage._validate_service_instance(object, mock_service)

        # Should log error about AsyncMock method
        assert any("AsyncMock" in record.message for record in caplog.records)


class TestSessionServiceTestStage:
    """Tests for SessionServiceTestStage class."""

    @pytest.fixture
    def stage(self) -> SessionServiceTestStage:
        """Create a SessionServiceTestStage instance."""
        return SessionServiceTestStage()

    def test_properties(self, stage: SessionServiceTestStage) -> None:
        """Test stage properties."""
        assert stage.name == "safe_session_services"
        assert stage.get_dependencies() == ["core_services"]
        assert "session services" in stage.get_description().lower()

    @pytest.mark.asyncio
    async def test_register_services(self, stage: SessionServiceTestStage) -> None:
        """Test _register_services method."""
        services = ServiceCollection()
        from src.core.config.app_config import (
            AppConfig,
            AuthConfig,
            BackendConfig,
            BackendSettings,
        )

        config = AppConfig(
            host="localhost",
            port=9000,
            backends=BackendSettings(
                default_backend="openai", openai=BackendConfig(api_key=["test_key"])
            ),
            auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
        )

        await stage._register_services(services, config)

        # Should have registered session service
        assert ISessionService in stage._registered_services
        mock_service = stage._registered_services[ISessionService]
        assert mock_service is not None

        # Should be able to get session
        session = mock_service.get_session("test_id")
        assert session.session_id == "test_id"


class TestBackendServiceTestStage:
    """Tests for BackendServiceTestStage class."""

    @pytest.fixture
    def stage(self) -> BackendServiceTestStage:
        """Create a BackendServiceTestStage instance."""
        return BackendServiceTestStage()

    def test_properties(self, stage: BackendServiceTestStage) -> None:
        """Test stage properties."""
        assert stage.name == "safe_backend_services"
        assert stage.get_dependencies() == ["infrastructure"]
        assert "backend services" in stage.get_description().lower()

    @pytest.mark.asyncio
    async def test_register_services(self, stage: BackendServiceTestStage) -> None:
        """Test _register_services method."""
        services = ServiceCollection()
        from src.core.config.app_config import (
            AppConfig,
            AuthConfig,
            BackendConfig,
            BackendSettings,
        )

        config = AppConfig(
            host="localhost",
            port=9000,
            backends=BackendSettings(
                default_backend="openai", openai=BackendConfig(api_key=["test_key"])
            ),
            auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
        )

        await stage._register_services(services, config)

        # Should have registered backend service
        from src.core.interfaces.backend_service_interface import IBackendService

        assert IBackendService in stage._registered_services
        mock_service = stage._registered_services[IBackendService]
        assert mock_service is not None

        # Should have async methods
        assert hasattr(mock_service, "call_completion")


class TestGuardedMockCreationMixin:
    """Tests for GuardedMockCreationMixin class."""

    class TestClass(GuardedMockCreationMixin):
        """Test class that uses the mixin."""

    @pytest.fixture
    def test_instance(self) -> TestClass:
        """Create a test instance."""
        return self.TestClass()

    def test_create_mock_basic(self, test_instance: TestClass) -> None:
        """Test create_mock with basic parameters."""
        mock = test_instance.create_mock()

        assert mock is not None
        assert isinstance(mock, MagicMock)

    def test_create_mock_with_spec(self, test_instance: TestClass) -> None:
        """Test create_mock with spec."""
        mock = test_instance.create_mock(spec=object)

        assert mock is not None
        assert isinstance(mock, MagicMock)

    def test_create_mock_with_kwargs(self, test_instance: TestClass) -> None:
        """Test create_mock with additional kwargs."""
        mock = test_instance.create_mock(return_value="test")

        assert mock() == "test"

    def test_create_async_mock_basic(self, test_instance: TestClass) -> None:
        """Test create_async_mock with basic parameters."""
        mock = test_instance.create_async_mock()

        assert mock is not None
        assert isinstance(mock, AsyncMock)

    def test_create_async_mock_with_spec(self, test_instance: TestClass) -> None:
        """Test create_async_mock with spec."""
        mock = test_instance.create_async_mock(spec=object)

        assert mock is not None
        assert isinstance(mock, AsyncMock)

    def test_create_async_mock_with_kwargs(self, test_instance: TestClass) -> None:
        """Test create_async_mock with additional kwargs."""
        mock = test_instance.create_async_mock(return_value="async_test")

        import asyncio

        result = asyncio.run(mock())
        assert result == "async_test"

    def test_create_mock_with_session_spec_warning(
        self, test_instance: TestClass, caplog
    ) -> None:
        """Test create_mock with session spec generates warning."""
        with caplog.at_level(logging.WARNING):
            mock = test_instance.create_mock(spec=ISessionService)

        assert mock is not None
        # Should log warning about session service
        assert any("Session" in record.message for record in caplog.records)

    def test_create_async_mock_logs_info(
        self, test_instance: TestClass, caplog
    ) -> None:
        """Test create_async_mock logs info message."""
        with caplog.at_level(logging.INFO):
            mock = test_instance.create_async_mock(spec=object)

        assert mock is not None
        # Should log info about AsyncMock creation
        assert any("Created AsyncMock" in record.message for record in caplog.records)


class TestBaseStageIntegration:
    """Integration tests for base stage functionality."""

    @pytest.mark.asyncio
    async def test_complete_stage_execution_workflow(self) -> None:
        """Test complete stage execution workflow."""
        stage = SessionServiceTestStage()
        services = ServiceCollection()
        from src.core.config.app_config import (
            AppConfig,
            AuthConfig,
            BackendConfig,
            BackendSettings,
        )

        config = AppConfig(
            host="localhost",
            port=9000,
            backends=BackendSettings(
                default_backend="openai", openai=BackendConfig(api_key=["test_key"])
            ),
            auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
        )

        # Execute the stage
        await stage.execute(services, config)

        # Verify services were registered
        assert ISessionService in stage._registered_services

        # Verify the mock works correctly
        mock_service = stage._registered_services[ISessionService]
        session = mock_service.get_session("test_id")
        assert session.session_id == "test_id"

    @pytest.mark.asyncio
    async def test_multiple_stages_execution(self) -> None:
        """Test executing multiple stages."""
        session_stage = SessionServiceTestStage()
        backend_stage = BackendServiceTestStage()
        services = ServiceCollection()
        from src.core.config.app_config import (
            AppConfig,
            AuthConfig,
            BackendConfig,
            BackendSettings,
        )

        config = AppConfig(
            host="localhost",
            port=9000,
            backends=BackendSettings(
                default_backend="openai", openai=BackendConfig(api_key=["test_key"])
            ),
            auth=AuthConfig(disable_auth=True, api_keys=["test-key"]),
        )

        # Execute both stages
        await session_stage.execute(services, config)
        await backend_stage.execute(services, config)

        # Verify both services were registered
        assert ISessionService in session_stage._registered_services
        from src.core.interfaces.backend_service_interface import IBackendService

        assert IBackendService in backend_stage._registered_services

    def test_stage_inheritance_validation(self) -> None:
        """Test that stages properly inherit from ValidatedTestStage."""
        session_stage = SessionServiceTestStage()
        backend_stage = BackendServiceTestStage()

        assert isinstance(session_stage, ValidatedTestStage)
        assert isinstance(backend_stage, ValidatedTestStage)
        assert isinstance(session_stage, InitializationStage)
        assert isinstance(backend_stage, InitializationStage)

    def test_mixin_inheritance(self) -> None:
        """Test that mixin provides expected functionality."""

        class TestWithMixin(GuardedMockCreationMixin):
            pass

        instance = TestWithMixin()

        # Should have the mixin methods
        assert hasattr(instance, "create_mock")
        assert hasattr(instance, "create_async_mock")

        # Should work correctly
        mock = instance.create_mock()
        async_mock = instance.create_async_mock()

        assert isinstance(mock, MagicMock)
        assert isinstance(async_mock, AsyncMock)
