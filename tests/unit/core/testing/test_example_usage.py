"""
Tests for Example Usage.

This module provides comprehensive test coverage for the example usage patterns
that demonstrate proper testing framework usage.
"""

import tempfile
from pathlib import Path

import pytest
from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.interfaces.session_service_interface import ISessionService
from src.core.testing.base_stage import BackendServiceTestStage, ValidatedTestStage
from src.core.testing.example_usage import (
    ProblematicTestStage,
    SafeTestStage,
    SomeComplexService,
    create_test_config,
    create_validated_test_app,
    migrate_existing_test_stage,
)


class TestProblematicTestStage:
    """Tests for ProblematicTestStage class."""

    def test_problematic_stage_creation(self) -> None:
        """Test that problematic stage can be created (but shouldn't be used)."""
        stage = ProblematicTestStage()

        assert isinstance(stage, InitializationStage)
        assert not isinstance(stage, ValidatedTestStage)

    def test_problematic_stage_properties(self) -> None:
        """Test problematic stage properties."""
        stage = ProblematicTestStage()

        assert stage.name == "problematic_stage"
        assert stage.get_dependencies() == ["core_services"]
        assert "warnings" in stage.get_description().lower()

    @pytest.mark.asyncio
    async def test_problematic_stage_execution(self) -> None:
        """Test problematic stage execution (should work but create issues)."""
        stage = ProblematicTestStage()
        services = ServiceCollection()
        config = create_test_config()

        # Should execute without raising exceptions
        await stage.execute(services, config)

        # Should not raise any exceptions despite being problematic
        assert True


class TestSafeTestStage:
    """Tests for SafeTestStage class."""

    def test_safe_stage_creation(self) -> None:
        """Test that safe stage can be created."""
        stage = SafeTestStage()

        assert isinstance(stage, ValidatedTestStage)
        assert isinstance(stage, InitializationStage)

    def test_safe_stage_properties(self) -> None:
        """Test safe stage properties."""
        stage = SafeTestStage()

        assert stage.name == "safe_stage"
        assert stage.get_dependencies() == []  # No dependencies for testing
        assert "validation" in stage.get_description().lower()

    @pytest.mark.asyncio
    async def test_safe_stage_execution(self) -> None:
        """Test safe stage execution."""
        stage = SafeTestStage()
        services = ServiceCollection()
        config = create_test_config()

        # Should execute without raising exceptions
        await stage.execute(services, config)

        # Should have registered services safely
        assert IBackendService in stage._registered_services
        assert ISessionService in stage._registered_services


class TestBackendServiceTestStage:
    """Tests for BackendServiceTestStage class."""

    def test_backend_stage_creation(self) -> None:
        """Test that backend service stage can be created."""
        stage = BackendServiceTestStage()

        assert isinstance(stage, ValidatedTestStage)
        assert isinstance(stage, InitializationStage)

    def test_backend_stage_properties(self) -> None:
        """Test backend service stage properties."""
        stage = BackendServiceTestStage()

        assert stage.name == "safe_backend_services"
        assert stage.get_dependencies() == ["infrastructure"]
        assert "backend services" in stage.get_description().lower()

    @pytest.mark.asyncio
    async def test_backend_stage_execution(self) -> None:
        """Test backend service stage execution."""
        stage = BackendServiceTestStage()
        services = ServiceCollection()
        config = create_test_config()

        await stage.execute(services, config)

        # Should have registered backend service safely
        assert IBackendService in stage._registered_services

        # Should be able to use the mock
        mock_service = stage._registered_services[IBackendService]
        assert hasattr(mock_service, "call_completion")


class TestSomeComplexService:
    """Tests for SomeComplexService class."""

    def test_complex_service_creation(self) -> None:
        """Test complex service creation."""
        service = SomeComplexService()

        assert service is not None

    def test_sync_method(self) -> None:
        """Test sync method functionality."""
        service = SomeComplexService()

        result = service.get_config()
        assert result == {"key": "value"}

    def test_is_enabled_method(self) -> None:
        """Test is_enabled method functionality."""
        service = SomeComplexService()

        result = service.is_enabled()
        assert result is True

    @pytest.mark.asyncio
    async def test_async_method(self) -> None:
        """Test async method functionality."""
        service = SomeComplexService()

        result = await service.async_method()
        assert result == "async_result"


class TestCreateTestConfig:
    """Tests for create_test_config function."""

    def test_create_test_config(self) -> None:
        """Test creating test configuration."""
        config = create_test_config()

        assert isinstance(config, AppConfig)
        assert config.host == "localhost"
        assert config.port == 9000
        assert config.backends.default_backend == "openai"
        assert config.auth.disable_auth is True

    def test_create_test_config_has_openai_backend(self) -> None:
        """Test that config has OpenAI backend configured."""
        config = create_test_config()

        assert config.backends.openai is not None
        assert len(config.backends.openai.api_key) == 1
        assert config.backends.openai.api_key[0] == "test_key"


class TestCreateValidatedTestApp:
    """Tests for create_validated_test_app function."""

    def test_create_validated_test_app(self) -> None:
        """Test creating validated test app."""
        app = create_validated_test_app()

        assert app is not None
        assert hasattr(app, "state")

    def test_create_validated_test_app_with_service_provider(self) -> None:
        """Test that app has service provider."""
        app = create_validated_test_app()

        assert hasattr(app.state, "service_provider")
        assert app.state.service_provider is not None


class TestMigrateExistingTestStage:
    """Tests for migrate_existing_test_stage function."""

    def test_migrate_existing_test_stage(self) -> None:
        """Test migrating existing test stage."""
        migrated_stage = migrate_existing_test_stage()

        assert migrated_stage is not None
        assert isinstance(migrated_stage, ValidatedTestStage)
        assert not isinstance(migrated_stage, InitializationStage) or isinstance(
            migrated_stage, ValidatedTestStage
        )

    def test_migrated_stage_properties(self) -> None:
        """Test migrated stage properties."""
        migrated_stage = migrate_existing_test_stage()

        assert migrated_stage.name == "migrated_stage"
        assert migrated_stage.get_dependencies() == ["core_services"]
        assert "migrated" in migrated_stage.get_description().lower()


class TestExampleUsageIntegration:
    """Integration tests for example usage patterns."""

    @pytest.mark.asyncio
    async def test_complete_problematic_vs_safe_comparison(self) -> None:
        """Test complete comparison between problematic and safe stages."""
        # Problematic stage (should work but create warnings)
        problematic_stage = ProblematicTestStage()
        safe_stage = SafeTestStage()

        services1 = ServiceCollection()
        services2 = ServiceCollection()
        config = create_test_config()

        # Both should execute without exceptions
        await problematic_stage.execute(services1, config)
        await safe_stage.execute(services2, config)

        # Safe stage should have validation tracking
        assert len(safe_stage._registered_services) > 0

        # Problematic stage won't have the same validation
        # (This is the point - to show the difference)

    def test_safe_mock_creation_patterns(self) -> None:
        """Test safe mock creation patterns from examples."""
        from src.core.testing.interfaces import EnforcedMockFactory

        # Create safe mocks as shown in examples
        session_service = EnforcedMockFactory.create_session_service_mock()
        backend_service = EnforcedMockFactory.create_backend_service_mock()

        # Test session service mock
        session = session_service.get_session("test_id")
        assert session.session_id == "test_id"

        # Test backend service mock
        assert hasattr(backend_service, "call_completion")
        assert hasattr(backend_service, "validate_backend")

    def test_mixed_async_sync_service_pattern(self) -> None:
        """Test mixed async/sync service pattern from examples."""
        from src.core.testing.interfaces import SafeAsyncMockWrapper

        # Create wrapper as shown in examples
        wrapper = SafeAsyncMockWrapper(spec=SomeComplexService)

        # Mark sync methods
        wrapper.mark_method_as_sync("get_config", return_value={"configured": True})
        wrapper.mark_method_as_sync("is_enabled", return_value=False)

        # Test sync methods
        config = wrapper.get_config()
        assert config == {"configured": True}

        enabled = wrapper.is_enabled()
        assert enabled is False

    def test_stage_inheritance_patterns(self) -> None:
        """Test stage inheritance patterns from examples."""
        # Safe stage should inherit from ValidatedTestStage
        safe_stage = SafeTestStage()
        assert isinstance(safe_stage, ValidatedTestStage)

        # Backend stage should also inherit from ValidatedTestStage
        backend_stage = BackendServiceTestStage()
        assert isinstance(backend_stage, ValidatedTestStage)

        # Both should have the safe registration methods
        assert hasattr(safe_stage, "create_safe_session_service_mock")
        assert hasattr(safe_stage, "create_safe_backend_service_mock")
        assert hasattr(backend_stage, "create_safe_session_service_mock")
        assert hasattr(backend_stage, "create_safe_backend_service_mock")

    @pytest.mark.asyncio
    async def test_app_creation_and_validation_workflow(self) -> None:
        """Test complete app creation and validation workflow."""
        # Create validated app
        app = create_validated_test_app()

        assert app is not None
        assert hasattr(app, "state")
        assert hasattr(app.state, "service_provider")

        # Test that we can create the app without errors
        # (The actual validation would happen during test execution)

    def test_migration_workflow(self) -> None:
        """Test the migration workflow from problematic to safe patterns."""
        # Old way (just for reference - we don't actually create it)
        # new_stage = migrate_existing_test_stage()

        migrated_stage = migrate_existing_test_stage()

        # The migrated stage should use safe patterns
        assert isinstance(migrated_stage, ValidatedTestStage)

        # Should have the same interface as the old stage
        assert hasattr(migrated_stage, "name")
        assert hasattr(migrated_stage, "get_dependencies")
        assert hasattr(migrated_stage, "get_description")

    def test_file_based_example_patterns(self) -> None:
        """Test file-based example patterns from the module."""
        # This tests that the patterns shown in the file actually work

        # Test that the problematic pattern can be identified
        problematic_code = """
from unittest.mock import AsyncMock
from src.core.interfaces.session_service_interface import ISessionService

def test_problem():
    mock = AsyncMock(spec=ISessionService)
    services.add_instance(ISessionService, mock)
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(problematic_code)
            temp_path = Path(f.name)

        try:
            from src.core.testing.type_checker import AsyncSyncPatternChecker

            checker = AsyncSyncPatternChecker()
            issues = checker.check_file(temp_path)

            # Should find issues with this problematic pattern
            assert len(issues) > 0
            assert any("AsyncMock" in issue for issue in issues)
        finally:
            temp_path.unlink()

    def test_safe_patterns_in_file(self) -> None:
        """Test that safe patterns work correctly."""
        safe_code = """
from src.core.testing.interfaces import EnforcedMockFactory
from src.core.testing.base_stage import ValidatedTestStage

class SafeTestStage(ValidatedTestStage):
    async def _register_services(self, services, config):
        mock = self.create_safe_session_service_mock()
        self.safe_register_instance(services, ISessionService, mock)
"""

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(safe_code)
            temp_path = Path(f.name)

        try:
            from src.core.testing.type_checker import AsyncSyncPatternChecker

            checker = AsyncSyncPatternChecker()
            issues = checker.check_file(temp_path)

            # Should not find issues with safe patterns
            safe_issues = [
                issue
                for issue in issues
                if "should inherit from ValidatedTestStage" not in issue
            ]
            assert len(safe_issues) == 0
        finally:
            temp_path.unlink()
