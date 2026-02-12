"""
Unit tests for backend startup validation logic.

Tests that BackendStage.validate() delegates to IBackendValidator.
"""

from __future__ import annotations

from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig, BackendConfig, BackendSettings
from src.core.di.container import ServiceCollection
from src.core.interfaces.backend_validator_interface import IBackendValidator
from src.core.interfaces.di_interface import IServiceProvider


class TestBackendStageDelegation:
    """Test that BackendStage.validate() delegates to IBackendValidator."""

    @pytest.fixture
    def backend_stage(self) -> BackendStage:
        """Create a BackendStage instance for testing."""
        return BackendStage()

    @pytest.fixture
    def services(self) -> ServiceCollection:
        """Create a mock ServiceCollection."""
        return Mock(spec=ServiceCollection)

    @pytest.fixture
    def app_config(self) -> AppConfig:
        """Create a basic AppConfig."""
        return AppConfig(
            backends=BackendSettings(
                default_backend="openai",
                openai=BackendConfig(api_key="test_key"),
            )
        )

    @pytest.mark.asyncio
    async def test_validate_delegates_to_backend_validator(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config: AppConfig,
    ):
        """Test that validate() resolves IBackendValidator and delegates to validate_all()."""
        mock_validator = AsyncMock(spec=IBackendValidator)
        mock_validator.validate_all = AsyncMock(return_value=True)

        mock_provider = Mock(spec=IServiceProvider)
        mock_provider.get_required_service = Mock(return_value=mock_validator)
        mock_provider.get_service = Mock()

        with (
            patch(
                "src.core.di.provider_lifecycle.get_current_service_provider",
                return_value=mock_provider,
            ),
        ):
            result = await backend_stage.validate(services, app_config)

        assert result is True
        mock_provider.get_required_service.assert_called_once_with(
            cast(type, IBackendValidator)
        )
        mock_provider.get_service.assert_not_called()
        mock_validator.validate_all.assert_called_once_with(app_config)

    @pytest.mark.asyncio
    async def test_validate_returns_validator_result(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config: AppConfig,
    ):
        """Test that validate() returns the result from validator.validate_all()."""
        mock_validator = AsyncMock(spec=IBackendValidator)
        mock_validator.validate_all = AsyncMock(return_value=False)

        mock_provider = Mock(spec=IServiceProvider)
        mock_provider.get_required_service = Mock(return_value=mock_validator)

        with (
            patch(
                "src.core.di.provider_lifecycle.get_current_service_provider",
                return_value=mock_provider,
            ),
        ):
            result = await backend_stage.validate(services, app_config)

        assert result is False
        mock_validator.validate_all.assert_called_once_with(app_config)

    @pytest.mark.asyncio
    async def test_validate_propagates_exceptions(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config: AppConfig,
    ):
        """Test that validate() propagates exceptions from validator."""
        from src.core.common.exceptions import ServiceResolutionError

        mock_provider = Mock(spec=IServiceProvider)
        mock_provider.get_required_service = Mock(
            side_effect=ServiceResolutionError("Validator not found")
        )

        with (
            patch(
                "src.core.di.provider_lifecycle.get_current_service_provider",
                return_value=mock_provider,
            ),
            pytest.raises(ServiceResolutionError),
        ):
            await backend_stage.validate(services, app_config)

    @pytest.mark.asyncio
    async def test_validate_propagates_validator_exceptions(
        self,
        backend_stage: BackendStage,
        services: ServiceCollection,
        app_config: AppConfig,
    ):
        """Test that validate() propagates exceptions raised by validator.validate_all()."""
        mock_validator = AsyncMock(spec=IBackendValidator)
        mock_validator.validate_all = AsyncMock(
            side_effect=RuntimeError("Validation failed")
        )

        mock_provider = Mock(spec=IServiceProvider)
        mock_provider.get_required_service = Mock(return_value=mock_validator)

        with (
            patch(
                "src.core.di.provider_lifecycle.get_current_service_provider",
                return_value=mock_provider,
            ),
            pytest.raises(RuntimeError, match="Validation failed"),
        ):
            await backend_stage.validate(services, app_config)
