"""
Unit tests for backend startup validation logic.

Tests the enhanced backend stage validation that checks if backends are functional
and fails startup when no functional backends exist.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.di.container import ServiceCollection
from src.core.services.backend_registry import BackendRegistry


class TestBackendStartupValidation:
    """Test backend startup validation functionality."""

    @pytest.fixture
    def backend_stage(self) -> BackendStage:
        """Create a BackendStage instance for testing."""
        return BackendStage()

    @pytest.fixture
    def services(self) -> ServiceCollection:
        """Create a mock ServiceCollection."""
        return Mock(spec=ServiceCollection)

    @pytest.fixture
    def app_config_with_qwen_oauth(self) -> AppConfig:
        """Create AppConfig with qwen-oauth as the only backend."""
        config = AppConfig()
        config.backends = BackendSettings(
            default_backend="qwen-oauth",
            qwen_oauth=BackendConfig(api_key=["dummy_key"]),
        )
        return config

    @pytest.fixture
    def app_config_with_multiple_backends(self) -> AppConfig:
        """Create AppConfig with multiple backends configured."""
        config = AppConfig()
        config.backends = BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["openai_key"]),
            anthropic=BackendConfig(api_key=["anthropic_key"]),
            qwen_oauth=BackendConfig(api_key=["qwen_key"]),
        )
        return config

    @pytest.fixture
    def app_config_no_backends(self) -> AppConfig:
        """Create AppConfig with no backends configured."""
        config = AppConfig()
        # Create a BackendSettings with empty default_backend to avoid detection
        config.backends = BackendSettings(default_backend="")
        return config

    @pytest.fixture
    def mock_backend_registry(self) -> Mock:
        """Create a mock backend registry."""
        registry = Mock(spec=BackendRegistry)
        registry.get_registered_backends.return_value = [
            "openai",
            "anthropic",
            "qwen-oauth",
            "gemini",
        ]
        return registry


class TestBackendValidationLogic(TestBackendStartupValidation):
    """Test the core backend validation logic."""

    @pytest.mark.asyncio
    async def test_validate_no_registered_backends(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_no_backends: AppConfig,
    ):
        """Test validation passes when no backends are registered (for testing environments)."""
        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = []

            result = await backend_stage.validate(services, app_config_no_backends)

            assert result is True

    @pytest.mark.asyncio
    async def test_validate_no_functional_backends_fails_startup(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test validation fails when no functional backends are found."""
        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

            # Mock _validate_backend_functionality to return empty list (no functional backends)
            with patch.object(
                backend_stage, "_validate_backend_functionality", return_value=[]
            ):
                result = await backend_stage.validate(
                    services, app_config_with_qwen_oauth
                )

                assert result is False

    @pytest.mark.asyncio
    async def test_validate_with_functional_backends_passes(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test validation passes when functional backends are found."""
        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

            # Mock _validate_backend_functionality to return functional backends
            with patch.object(
                backend_stage,
                "_validate_backend_functionality",
                return_value=["qwen-oauth"],
            ):
                result = await backend_stage.validate(
                    services, app_config_with_qwen_oauth
                )

                assert result is True


class TestBackendFunctionalityValidation(TestBackendStartupValidation):
    """Test the detailed backend functionality validation."""

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_no_configured_backends(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_no_backends: AppConfig,
    ):
        """Test functionality validation with no configured backends."""
        functional_backends = await backend_stage._validate_backend_functionality(
            services, app_config_no_backends
        )

        assert functional_backends == []

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_backend_not_registered(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test functionality validation when configured backend is not registered."""
        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = [
                "openai"
            ]  # qwen-oauth not registered

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == []

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_functional_backend(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test functionality validation with a functional backend."""
        # Mock backend that is functional
        mock_backend = Mock()
        mock_backend.is_backend_functional.return_value = True
        mock_backend.initialize = AsyncMock()

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == ["qwen-oauth"]
            mock_backend.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_non_functional_backend(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test functionality validation with a non-functional backend."""
        # Mock backend that is not functional
        mock_backend = Mock()
        mock_backend.is_backend_functional.return_value = False
        mock_backend.get_validation_errors.return_value = [
            "Token expired",
            "Invalid credentials",
        ]
        mock_backend.initialize = AsyncMock()

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == []
            mock_backend.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_legacy_backend_without_enhanced_methods(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test functionality validation with legacy backend without enhanced validation methods."""
        # Mock legacy backend without is_backend_functional method
        mock_backend = Mock()
        # Remove the enhanced methods to simulate legacy backend
        del mock_backend.is_backend_functional
        del mock_backend.get_validation_errors
        mock_backend.is_functional = True  # Legacy property
        mock_backend.initialize = AsyncMock()

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == [
                "qwen-oauth"
            ]  # Should use legacy is_functional property

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_initialization_exception(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_qwen_oauth: AppConfig,
    ):
        """Test functionality validation when backend initialization raises exception."""
        # Mock backend that raises exception during initialization
        mock_backend = Mock()
        mock_backend.initialize = AsyncMock(
            side_effect=Exception("Initialization failed")
        )

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == []

    @pytest.mark.asyncio
    async def test_validate_backend_functionality_multiple_backends_mixed_results(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config_with_multiple_backends: AppConfig,
    ):
        """Test functionality validation with multiple backends having mixed results."""
        # Mock functional backend
        functional_backend = Mock()
        functional_backend.is_backend_functional.return_value = True
        functional_backend.initialize = AsyncMock()

        # Mock non-functional backend
        non_functional_backend = Mock()
        non_functional_backend.is_backend_functional.return_value = False
        non_functional_backend.get_validation_errors.return_value = ["Some error"]
        non_functional_backend.initialize = AsyncMock()

        # Mock backend that throws exception
        exception_backend = Mock()
        exception_backend.initialize = AsyncMock(side_effect=Exception("Init failed"))

        def mock_backend_factory(client, config, translation_service=None):
            # Return different backends based on some logic
            # This is a simplified approach for testing
            if hasattr(mock_backend_factory, "call_count"):
                mock_backend_factory.call_count += 1
            else:
                mock_backend_factory.call_count = 1

            if mock_backend_factory.call_count == 1:
                return functional_backend
            elif mock_backend_factory.call_count == 2:
                return non_functional_backend
            else:
                return exception_backend

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = [
                "openai",
                "anthropic",
                "qwen-oauth",
            ]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_multiple_backends
            )

            # Only the first backend should be functional
            assert len(functional_backends) == 1


class TestConfiguredBackendDetection(TestBackendStartupValidation):
    """Test detection of configured backends from app config."""

    @pytest.mark.asyncio
    async def test_configured_backends_detection_default_backend(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test that default backend is detected as configured."""
        config = AppConfig()
        config.backends = BackendSettings(default_backend="openai")

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai"]

            # Mock a functional backend
            mock_backend = Mock()
            mock_backend.is_backend_functional.return_value = True
            mock_backend.initialize = AsyncMock()
            mock_backend_factory = Mock(return_value=mock_backend)
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, config
            )

            assert "openai" in functional_backends

    @pytest.mark.asyncio
    async def test_configured_backends_detection_with_api_keys(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test that backends with API keys are detected as configured."""
        config = AppConfig()
        config.backends = BackendSettings(
            openai=BackendConfig(api_key=["openai_key"]),
            anthropic=BackendConfig(api_key=["anthropic_key"]),
        )

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai", "anthropic"]

            # Mock functional backends
            mock_backend = Mock()
            mock_backend.is_backend_functional.return_value = True
            mock_backend.initialize = AsyncMock()
            mock_backend_factory = Mock(return_value=mock_backend)
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, config
            )

            assert len(functional_backends) == 2
            assert "openai" in functional_backends
            assert "anthropic" in functional_backends

    @pytest.mark.asyncio
    async def test_configured_backends_detection_ignores_empty_api_keys(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test that backends with empty API keys are not considered configured."""
        config = AppConfig()
        config.backends = BackendSettings(
            openai=BackendConfig(api_key=["openai_key"]),  # Has key
            anthropic=BackendConfig(api_key=[]),  # Empty key list
        )

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai", "anthropic"]

            # Mock functional backend
            mock_backend = Mock()
            mock_backend.is_backend_functional.return_value = True
            mock_backend.initialize = AsyncMock()
            mock_backend_factory = Mock(return_value=mock_backend)
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            functional_backends = await backend_stage._validate_backend_functionality(
                services, config
            )

            # Only openai should be considered configured and validated
            assert functional_backends == ["openai"]


class TestIntegrationScenarios(TestBackendStartupValidation):
    """Test complete integration scenarios for startup validation."""

    @pytest.mark.asyncio
    async def test_startup_failure_scenario_only_qwen_oauth_expired(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test complete scenario: only qwen-oauth configured, but it's non-functional -> startup fails."""
        config = AppConfig()
        config.backends = BackendSettings(
            default_backend="qwen-oauth",
            qwen_oauth=BackendConfig(api_key=["dummy_key"]),
        )

        # Mock non-functional qwen-oauth backend
        mock_backend = Mock()
        mock_backend.is_backend_functional.return_value = False
        mock_backend.get_validation_errors.return_value = [
            "Token expired at ... (current time: ...)"
        ]
        mock_backend.initialize = AsyncMock()

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            # This should fail validation
            result = await backend_stage.validate(services, config)

            assert result is False

    @pytest.mark.asyncio
    async def test_startup_success_scenario_qwen_oauth_functional(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test complete scenario: only qwen-oauth configured and it's functional -> startup succeeds."""
        config = AppConfig()
        config.backends = BackendSettings(
            default_backend="qwen-oauth",
            qwen_oauth=BackendConfig(api_key=["dummy_key"]),
        )

        # Mock functional qwen-oauth backend
        mock_backend = Mock()
        mock_backend.is_backend_functional.return_value = True
        mock_backend.initialize = AsyncMock()

        mock_backend_factory = Mock(return_value=mock_backend)

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            # This should pass validation
            result = await backend_stage.validate(services, config)

            assert result is True

    @pytest.mark.asyncio
    async def test_startup_success_scenario_mixed_backends_some_functional(
        self, backend_stage: BackendStage, services: ServiceCollection
    ):
        """Test scenario: multiple backends, some functional, some not -> startup succeeds if at least one works."""
        config = AppConfig()
        config.backends = BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["openai_key"]),
            qwen_oauth=BackendConfig(api_key=["qwen_key"]),
        )

        # Mock one functional backend and one non-functional
        functional_backend = Mock()
        functional_backend.is_backend_functional.return_value = True
        functional_backend.initialize = AsyncMock()

        non_functional_backend = Mock()
        non_functional_backend.is_backend_functional.return_value = False
        non_functional_backend.get_validation_errors.return_value = ["Token expired"]
        non_functional_backend.initialize = AsyncMock()

        def mock_backend_factory(client, config, translation_service=None):
            # Return functional backend for openai, non-functional for qwen-oauth
            if hasattr(mock_backend_factory, "call_count"):
                mock_backend_factory.call_count += 1
            else:
                mock_backend_factory.call_count = 1

            return (
                functional_backend
                if mock_backend_factory.call_count == 1
                else non_functional_backend
            )

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = [
                "openai",
                "qwen-oauth",
            ]
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            # This should pass validation because openai is functional
            result = await backend_stage.validate(services, config)

            assert result is True
