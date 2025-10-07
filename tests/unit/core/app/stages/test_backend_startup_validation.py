"""
Unit tests for backend startup validation logic.

Tests the enhanced backend stage validation that checks if backends are functional
and fails startup when no functional backends exist.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
        # Clear backend configs to ensure no backends are considered configured
        # This prevents environment variables from being detected as configured backends
        for backend_name in [
            "openai",
            "anthropic",
            "gemini",
            "openrouter",
            "qwen_oauth",
        ]:
            if hasattr(config.backends, backend_name):
                delattr(config.backends, backend_name)
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
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test validation fails when no functional backends are found in non-test environment."""
        # Remove test environment markers to test production behavior
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

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
        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = []

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

        # Mock backend factory service
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(return_value=mock_backend)

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == ["qwen-oauth"]

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

        # Mock backend factory service
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(return_value=mock_backend)

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

            functional_backends = await backend_stage._validate_backend_functionality(
                services, app_config_with_qwen_oauth
            )

            assert functional_backends == []

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
        # Remove the is_backend_functional attribute entirely to simulate legacy backend
        del mock_backend.is_backend_functional
        mock_backend.is_functional = True
        mock_backend.initialize = AsyncMock()

        # Mock backend factory service
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(return_value=mock_backend)

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

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
        # Mock backend factory service that raises exception
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(
            side_effect=Exception("Initialization failed")
        )

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

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

        # Mock non-functional backend
        non_functional_backend = Mock()
        non_functional_backend.is_backend_functional.return_value = False
        non_functional_backend.get_validation_errors.return_value = ["Some error"]

        # Mock backend factory service with counter
        call_count = {"count": 0}

        async def ensure_backend_mock(backend_type, app_config, backend_config):
            call_count["count"] += 1
            if call_count["count"] == 1:
                return functional_backend
            elif call_count["count"] == 2:
                return non_functional_backend
            else:
                raise Exception("Init failed")

        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = ensure_backend_mock

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = [
                "openai",
                "anthropic",
                "qwen-oauth",
            ]

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
        config.backends = BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key=["test_openai_key"]),
        )

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai"]

            mock_backend = AsyncMock()
            mock_backend.is_backend_functional.return_value = True

            backend_factory_service = Mock()
            backend_factory_service.ensure_backend = AsyncMock(
                return_value=mock_backend
            )

            service_provider = Mock()
            service_provider.get_service.return_value = backend_factory_service
            services.build_service_provider.return_value = service_provider

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

            mock_backend = AsyncMock()
            mock_backend.is_backend_functional.return_value = True

            backend_factory_service = Mock()
            backend_factory_service.ensure_backend = AsyncMock(
                return_value=mock_backend
            )

            service_provider = Mock()
            service_provider.get_service.return_value = backend_factory_service
            services.build_service_provider.return_value = service_provider

            functional_backends = await backend_stage._validate_backend_functionality(
                services, config
            )

            assert len(functional_backends) == 2
            assert "openai" in functional_backends
            assert "anthropic" in functional_backends

    @pytest.mark.asyncio
    async def test_configured_backends_detection_ignores_empty_api_keys(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test that backends with empty API keys are not considered configured."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        config = AppConfig()
        config.backends = BackendSettings(
            openai=BackendConfig(api_key=["openai_key"]),  # Has key
            anthropic=BackendConfig(api_key=[]),  # Empty key list
        )

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["openai", "anthropic"]

            # Mock functional backend
            mock_backend = AsyncMock()
            mock_backend.is_backend_functional.return_value = True
            mock_backend.initialize = AsyncMock()
            mock_backend_factory = AsyncMock(return_value=mock_backend)
            mock_registry.get_backend_factory.return_value = mock_backend_factory

            service_provider = Mock()
            service_provider.get_service.return_value = mock_backend_factory
            services.build_service_provider.return_value = service_provider

            functional_backends = await backend_stage._validate_backend_functionality(
                services, config
            )

            # Only openai should be considered configured and validated
            assert functional_backends == ["openai"]


class TestIntegrationScenarios(TestBackendStartupValidation):
    """Test complete integration scenarios for startup validation."""

    @pytest.mark.asyncio
    async def test_startup_failure_scenario_only_qwen_oauth_expired(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Test complete scenario: only qwen-oauth configured, but it's non-functional -> startup fails in non-test environment."""
        # Remove test environment markers to test production behavior
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

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

        # Mock backend factory service
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(return_value=mock_backend)

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

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

        # Mock backend factory service
        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = AsyncMock(return_value=mock_backend)

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = ["qwen-oauth"]

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

        non_functional_backend = Mock()
        non_functional_backend.is_backend_functional.return_value = False
        non_functional_backend.get_validation_errors.return_value = ["Token expired"]

        # Mock backend factory service with counter
        call_count = {"count": 0}

        async def ensure_backend_mock(backend_type, app_config, backend_config):
            call_count["count"] += 1
            return (
                functional_backend
                if call_count["count"] == 1
                else non_functional_backend
            )

        backend_factory_service = Mock()
        backend_factory_service.ensure_backend = ensure_backend_mock

        # Mock service provider
        service_provider = Mock()
        service_provider.get_service.return_value = backend_factory_service
        services.build_service_provider.return_value = service_provider

        with patch("src.core.app.stages.backend.backend_registry") as mock_registry:
            mock_registry.get_registered_backends.return_value = [
                "openai",
                "qwen-oauth",
            ]

            # This should pass validation because openai is functional
            result = await backend_stage.validate(services, config)

            assert result is True


def test_backend_service_interface_shares_concrete_singleton() -> None:
    """BackendService and IBackendService should resolve to the same singleton."""

    from typing import cast

    from src.core.app.stages.backend import BackendStage
    from src.core.config.app_config import AppConfig
    from src.core.di.container import ServiceCollection
    from src.core.interfaces.application_state_interface import IApplicationState
    from src.core.interfaces.backend_config_provider_interface import (
        IBackendConfigProvider,
    )
    from src.core.interfaces.backend_service_interface import IBackendService
    from src.core.interfaces.session_service_interface import ISessionService
    from src.core.interfaces.wire_capture_interface import IWireCapture
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.rate_limiter import RateLimiter

    services = ServiceCollection()
    services.add_instance(AppConfig, AppConfig())
    services.add_instance(BackendFactory, MagicMock(spec=BackendFactory))
    services.add_instance(RateLimiter, MagicMock(spec=RateLimiter))
    services.add_instance(
        cast(type, IBackendConfigProvider), MagicMock(spec=IBackendConfigProvider)
    )
    services.add_instance(cast(type, ISessionService), MagicMock(spec=ISessionService))
    services.add_instance(cast(type, IApplicationState), MagicMock())
    services.add_instance(cast(type, IWireCapture), MagicMock())

    fake_instance = object()

    backend_stage = BackendStage()

    with patch(
        "src.core.services.backend_service.BackendService",
        side_effect=lambda *args, **kwargs: fake_instance,
    ) as backend_cls:
        backend_stage._register_backend_service(services)

    provider = services.build_service_provider()

    concrete = provider.get_required_service(backend_cls)
    interface_instance = provider.get_required_service(cast(type, IBackendService))

    assert concrete is fake_instance
    assert interface_instance is fake_instance
