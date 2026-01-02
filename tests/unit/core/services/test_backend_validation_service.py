"""
Unit tests for BackendValidationService.

Tests backend validation outcomes and environment behavior covering:
- Configured backend detection from default_backend, static_route, and explicit configs
- No backends configured behavior
- Test vs non-test environment behavior
- Error collection and logging
- Fail-fast behavior for missing dependencies
"""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.services.backend_validation_service import BackendValidationService


@pytest.fixture
def mock_backend_factory():
    """Create a mock BackendFactory."""
    factory = Mock()
    factory.ensure_backend = AsyncMock()
    return factory


@pytest.fixture
def mock_http_client_manager():
    """Create a mock IHttpClientManager."""
    manager = Mock()
    manager.get_or_create_client = Mock(return_value=Mock())
    manager.cleanup = AsyncMock()
    return manager


@pytest.fixture
def mock_backend_registry():
    """Create a mock BackendRegistry."""
    registry = Mock()
    registry.get_registered_backends = Mock(
        return_value=["openai", "anthropic", "gemini"]
    )
    return registry


@pytest.fixture
def functional_backend():
    """Create a mock backend that is functional."""
    backend = Mock()
    backend.is_backend_functional = Mock(return_value=True)
    backend.get_validation_errors = Mock(return_value=[])
    return backend


@pytest.fixture
def non_functional_backend():
    """Create a mock backend that is not functional."""
    backend = Mock()
    backend.is_backend_functional = Mock(return_value=False)
    backend.get_validation_errors = Mock(
        return_value=["Token expired", "Invalid credentials"]
    )
    return backend


@pytest.fixture
def app_config_default_backend():
    """Create AppConfig with default_backend configured."""
    return AppConfig(
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key="test_key"),
        )
    )


@pytest.fixture
def app_config_static_route():
    """Create AppConfig with static_route configured."""
    return AppConfig(
        backends=BackendSettings(
            static_route="anthropic:claude-3-opus",
            anthropic=BackendConfig(api_key="test_key"),
        )
    )


@pytest.fixture
def app_config_multiple_backends():
    """Create AppConfig with multiple backends configured."""
    return AppConfig(
        backends=BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key="openai_key"),
            anthropic=BackendConfig(api_key="anthropic_key"),
            gemini=BackendConfig(api_key="gemini_key"),
        )
    )


@pytest.fixture
def app_config_no_backends():
    """Create AppConfig with no backends configured."""
    return AppConfig(
        backends=BackendSettings(
            default_backend="",
        )
    )


@pytest.fixture
def app_config_explicit_backend_only():
    """Create AppConfig with only explicit backend config (no default_backend or static_route)."""
    return AppConfig(
        backends=BackendSettings(
            gemini=BackendConfig(api_key="gemini_key"),
        )
    )


class TestBackendValidationServiceConfiguredBackendDetection:
    """Test detection of configured backends from various config sources."""

    @pytest.mark.asyncio
    async def test_detects_default_backend(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
        app_config_default_backend,
    ):
        """Test that default_backend is detected as configured."""
        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_default_backend)

        assert result is True
        mock_backend_factory.ensure_backend.assert_called_once()
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "openai"

    @pytest.mark.asyncio
    async def test_detects_static_route_backend(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
        app_config_static_route,
    ):
        """Test that backend from static_route (before ':') is detected as configured."""
        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_static_route)

        assert result is True
        mock_backend_factory.ensure_backend.assert_called_once()
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "anthropic"

    @pytest.mark.asyncio
    async def test_detects_explicit_backend_configs(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
        app_config_explicit_backend_only,
    ):
        """Test that backends with explicit configs (api_key) are detected."""
        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_explicit_backend_only)

        assert result is True
        mock_backend_factory.ensure_backend.assert_called_once()
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "gemini"

    @pytest.mark.asyncio
    async def test_detects_multiple_configured_backends(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
        app_config_multiple_backends,
    ):
        """Test that multiple configured backends are all detected and validated."""
        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_multiple_backends)

        assert result is True
        # Should validate all configured backends
        assert mock_backend_factory.ensure_backend.call_count == 3
        validated_backends = {
            call.kwargs["backend_type"]
            for call in mock_backend_factory.ensure_backend.call_args_list
        }
        assert validated_backends == {"openai", "anthropic", "gemini"}

    @pytest.mark.asyncio
    async def test_ignores_backends_without_api_keys(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
    ):
        """Test that backends without api_key are not considered configured."""
        config = AppConfig(
            backends=BackendSettings(
                openai=BackendConfig(api_key="openai_key"),  # Has key
                anthropic=BackendConfig(api_key=None),  # No key
            )
        )

        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(config)

        assert result is True
        # Only openai should be validated
        assert mock_backend_factory.ensure_backend.call_count == 1
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "openai"

    @pytest.mark.asyncio
    async def test_ignores_unregistered_backends(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
    ):
        """Test that configured backends not in registry are ignored."""
        config = AppConfig(
            backends=BackendSettings(
                default_backend="unknown-backend",
                unknown_backend=BackendConfig(api_key="key"),
            )
        )
        mock_backend_registry.get_registered_backends.return_value = [
            "openai"
        ]  # unknown-backend not registered

        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(config)

        # Should allow startup (no configured backends that are registered)
        assert result is True
        # Should not attempt to validate unregistered backend
        mock_backend_factory.ensure_backend.assert_not_called()


class TestBackendValidationServiceNoBackendsBehavior:
    """Test behavior when no backends are configured."""

    @pytest.mark.asyncio
    async def test_allows_startup_when_no_backends_configured(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        app_config_no_backends,
        caplog,
    ):
        """Test that validation allows startup when no backends are configured."""
        with caplog.at_level("WARNING"):
            validator = BackendValidationService(
                backend_factory=mock_backend_factory,
                http_client_manager=mock_http_client_manager,
                backend_registry=mock_backend_registry,
            )

            result = await validator.validate_all(app_config_no_backends)

        assert result is True
        # Should log warning about no backends configured
        assert any(
            "no backends configured" in record.message.lower()
            for record in caplog.records
        )
        mock_backend_factory.ensure_backend.assert_not_called()


class TestBackendValidationServiceNonFunctionalBackends:
    """Test behavior when configured backends are non-functional."""

    @pytest.mark.asyncio
    async def test_fails_startup_when_all_backends_non_functional_in_production(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        non_functional_backend,
        app_config_default_backend,
        monkeypatch,
        caplog,
    ):
        """Test that validation fails when all backends are non-functional in non-test environment."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        mock_backend_factory.ensure_backend.return_value = non_functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        with caplog.at_level("ERROR"):
            result = await validator.validate_all(app_config_default_backend)

        assert result is False
        # Should log error about non-functional backends
        assert any(
            "no functional backends" in record.message.lower()
            for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_allows_startup_when_all_backends_non_functional_in_test_env(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        non_functional_backend,
        app_config_default_backend,
        monkeypatch,
        caplog,
    ):
        """Test that validation allows startup when all backends are non-functional in test environment."""
        monkeypatch.setenv(
            "PYTEST_CURRENT_TEST", "test_backend_validation_service.py::test"
        )

        mock_backend_factory.ensure_backend.return_value = non_functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        with caplog.at_level("WARNING"):
            result = await validator.validate_all(app_config_default_backend)

        assert result is True
        # Should log warning about test environment allowance
        assert any(
            "test environment" in record.message.lower() for record in caplog.records
        )

    @pytest.mark.asyncio
    async def test_allows_startup_when_some_backends_functional(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
        non_functional_backend,
        app_config_multiple_backends,
    ):
        """Test that validation passes when at least one backend is functional."""
        call_count = {"count": 0}

        async def ensure_backend_side_effect(*args, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                return functional_backend  # First backend is functional
            return non_functional_backend  # Others are not

        mock_backend_factory.ensure_backend.side_effect = ensure_backend_side_effect

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_multiple_backends)

        assert result is True


class TestBackendValidationServiceErrorCollection:
    """Test collection and logging of validation errors."""

    @pytest.mark.asyncio
    async def test_collects_validation_errors_for_non_functional_backends(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        non_functional_backend,
        app_config_multiple_backends,
        caplog,
    ):
        """Test that validation errors are collected and logged for non-functional backends."""
        mock_backend_factory.ensure_backend.return_value = non_functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        with caplog.at_level("ERROR"):
            await validator.validate_all(app_config_multiple_backends)

        # Should log errors for each non-functional backend
        error_logs = [
            record for record in caplog.records if record.levelname == "ERROR"
        ]
        assert len(error_logs) >= 3  # At least one error per backend
        # Verify error messages mention backend names
        error_messages = " ".join(record.message for record in error_logs)
        assert (
            "openai" in error_messages
            or "anthropic" in error_messages
            or "gemini" in error_messages
        )

    @pytest.mark.asyncio
    async def test_logs_backend_validation_errors_with_details(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        non_functional_backend,
        app_config_default_backend,
        caplog,
    ):
        """Test that validation errors include backend-specific error details."""
        mock_backend_factory.ensure_backend.return_value = non_functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        with caplog.at_level("ERROR"):
            await validator.validate_all(app_config_default_backend)

        # Should log error with validation error details
        error_logs = [
            record for record in caplog.records if record.levelname == "ERROR"
        ]
        assert len(error_logs) > 0
        error_message = " ".join(record.message for record in error_logs)
        # Should include error details from get_validation_errors()
        assert (
            "Token expired" in error_message or "Invalid credentials" in error_message
        )

    @pytest.mark.asyncio
    async def test_handles_backend_initialization_exception(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        app_config_default_backend,
        monkeypatch,
        caplog,
    ):
        """Test that exceptions during backend initialization are caught and logged."""
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        mock_backend_factory.ensure_backend.side_effect = Exception(
            "Initialization failed"
        )

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        with caplog.at_level("ERROR"):
            result = await validator.validate_all(app_config_default_backend)

        # Should log error and treat backend as non-functional
        error_logs = [
            record for record in caplog.records if record.levelname == "ERROR"
        ]
        assert len(error_logs) > 0
        error_message = " ".join(record.message for record in error_logs)
        assert "failed" in error_message.lower() or "error" in error_message.lower()
        # Should fail validation (no functional backends)
        assert result is False


class TestBackendValidationServiceFailFastBehavior:
    """Test fail-fast behavior when required dependencies are missing."""

    @pytest.mark.asyncio
    async def test_fails_fast_when_backend_factory_missing(
        self,
        mock_http_client_manager,
        mock_backend_registry,
        app_config_default_backend,
        monkeypatch,
        caplog,
    ):
        """Test that validation fails fast when BackendFactory is None at runtime.

        This tests runtime failure handling when backend_factory is None (e.g., in unit tests
        or edge cases). DI resolution failures (requirement 2.10) are tested separately in
        test_backend_validation_registration.py.
        """
        # Unset test environment to ensure fail-fast behavior
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

        # BackendValidationService stores backend_factory, but will fail when trying to use it
        validator = BackendValidationService(
            backend_factory=None,  # type: ignore[arg-type]
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        # When validate_all is called, it should catch the exception, log it, and return False
        with caplog.at_level("ERROR"):
            result = await validator.validate_all(app_config_default_backend)

        # Should return False (fail fast) and log error
        assert result is False
        assert any(
            "Failed to validate backend" in record.message
            or "ensure_backend" in record.message
            for record in caplog.records
        )


class TestBackendValidationServiceInterfaceCompliance:
    """Test that BackendValidationService implements IBackendValidator interface."""

    def test_implements_ibackend_validator_interface(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
    ):
        """Test that BackendValidationService implements IBackendValidator."""
        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        # Check that validator has the required interface method
        # Note: isinstance check not possible with Protocol unless runtime_checkable
        assert hasattr(validator, "validate_all")
        assert callable(validator.validate_all)

    @pytest.mark.asyncio
    async def test_validate_all_signature(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        app_config_default_backend,
        functional_backend,
    ):
        """Test that validate_all has correct signature and return type."""
        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(app_config_default_backend)

        assert isinstance(result, bool)


class TestBackendValidationServiceStaticRouteParsing:
    """Test parsing of static_route to extract backend name."""

    @pytest.mark.asyncio
    async def test_extracts_backend_from_static_route_with_model(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
    ):
        """Test that backend name is correctly extracted from static_route format 'backend:model'."""
        config = AppConfig(
            backends=BackendSettings(
                static_route="gemini:gemini-2.5-pro",
                gemini=BackendConfig(api_key="key"),
            )
        )

        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(config)

        assert result is True
        mock_backend_factory.ensure_backend.assert_called_once()
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "gemini"

    @pytest.mark.asyncio
    async def test_handles_static_route_without_colon(
        self,
        mock_backend_factory,
        mock_http_client_manager,
        mock_backend_registry,
        functional_backend,
    ):
        """Test that static_route without colon is handled (treats entire string as backend)."""
        config = AppConfig(
            backends=BackendSettings(
                static_route="openai",  # No colon
                openai=BackendConfig(api_key="key"),
            )
        )

        mock_backend_factory.ensure_backend.return_value = functional_backend

        validator = BackendValidationService(
            backend_factory=mock_backend_factory,
            http_client_manager=mock_http_client_manager,
            backend_registry=mock_backend_registry,
        )

        result = await validator.validate_all(config)

        assert result is True
        mock_backend_factory.ensure_backend.assert_called_once()
        call_args = mock_backend_factory.ensure_backend.call_args
        assert call_args.kwargs["backend_type"] == "openai"
