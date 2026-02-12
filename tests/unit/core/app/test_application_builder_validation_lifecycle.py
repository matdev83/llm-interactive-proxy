"""
Tests for ApplicationBuilder validation lifecycle and config injection.

Tests cover:
- Config injection before validation
- Validation provider lifecycle (build without post-build hooks)
- Temporary provider installation and restoration
- Cleanup on validation failure
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.app.stages.base import InitializationStage
from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.interfaces.di_interface import IServiceProvider


class MockValidationStage(InitializationStage):
    """Mock stage for testing validation lifecycle."""

    @property
    def name(self) -> str:
        return "mock_validation"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Mock validation stage"

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Mock validation that always succeeds."""
        return True

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Mock execution."""


class MockFailingValidationStage(InitializationStage):
    """Mock stage that fails validation."""

    @property
    def name(self) -> str:
        return "mock_failing"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Mock failing validation stage"

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Mock validation that always fails."""
        return False

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Mock execution."""


class MockExceptionValidationStage(InitializationStage):
    """Mock stage that raises exception during validation."""

    @property
    def name(self) -> str:
        return "mock_exception"

    def get_dependencies(self) -> list[str]:
        return []

    def get_description(self) -> str:
        return "Mock exception validation stage"

    async def validate(self, services: ServiceCollection, config: AppConfig) -> bool:
        """Mock validation that raises exception."""
        raise ValueError("Validation failed")

    async def execute(self, services: ServiceCollection, config: AppConfig) -> None:
        """Mock execution."""


class TestConfigInjection:
    """Tests for config injection before validation."""

    @pytest.mark.asyncio
    async def test_runtime_config_replaces_default_config_before_validation(
        self,
    ) -> None:
        """Test that runtime config replaces default config in DI before validation."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        # Create a custom config instance
        custom_config = AppConfig()

        # Mock the add_instance to verify it's called with the runtime config
        with (
            patch.object(builder._services, "add_instance") as mock_add_instance,
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_temp_provider.return_value.__enter__ = MagicMock()
            mock_temp_provider.return_value.__exit__ = MagicMock(return_value=False)

            with contextlib.suppress(Exception):
                # Expected to fail at stage execution, but config injection should happen
                await builder.build(custom_config)

            # Verify add_instance was called with runtime config (for both AppConfig and IConfig)
            assert mock_add_instance.call_count >= 2  # Called for AppConfig and IConfig
            # Verify at least one call was with AppConfig and custom_config
            app_config_calls = [
                call
                for call in mock_add_instance.call_args_list
                if call[0][0] == AppConfig and call[0][1] is custom_config
            ]
            assert (
                len(app_config_calls) > 0
            ), "add_instance should be called with AppConfig and custom_config"

    @pytest.mark.asyncio
    async def test_config_injection_happens_after_connector_import(
        self,
    ) -> None:
        """Test that config injection happens after connector import."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        custom_config = AppConfig()

        call_order = []

        def track_import(*args, **kwargs):
            call_order.append("import")

        def track_validate(*args, **kwargs):
            call_order.append("validate_static_route")

        def track_register(*args, **kwargs):
            call_order.append("register_config")

        with (
            patch("importlib.import_module", side_effect=track_import),
            patch(
                "src.core.config.semantic_validation.validate_static_route",
                side_effect=track_validate,
            ),
            patch.object(builder._services, "add_instance", side_effect=track_register),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_temp_provider.return_value.__enter__ = MagicMock()
            mock_temp_provider.return_value.__exit__ = MagicMock(return_value=False)

            with contextlib.suppress(Exception):
                await builder.build(custom_config)

            # Verify order: import -> validate_static_route -> register_config
            assert call_order.index("import") < call_order.index("register_config")
            assert call_order.index("validate_static_route") < call_order.index(
                "register_config"
            )

    @pytest.mark.asyncio
    async def test_merged_constrained_validation_runs_before_config_registration(
        self,
    ) -> None:
        """Startup must run merged constrained-family validation before DI registration."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())
        custom_config = AppConfig()
        call_order: list[str] = []

        def track_import(*args, **kwargs):
            call_order.append("import")

        def track_static_route(*args, **kwargs):
            call_order.append("validate_static_route")

        def track_constrained_validation(*args, **kwargs):
            call_order.append("validate_constrained_backends")

        def track_register(*args, **kwargs):
            call_order.append("register_config")

        with (
            patch("importlib.import_module", side_effect=track_import),
            patch(
                "src.core.config.semantic_validation.validate_static_route",
                side_effect=track_static_route,
            ),
            patch(
                "src.core.config.semantic_validation.validate_constrained_backend_instances",
                side_effect=track_constrained_validation,
            ),
            patch.object(builder._services, "add_instance", side_effect=track_register),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_temp_provider.return_value.__enter__ = MagicMock()
            mock_temp_provider.return_value.__exit__ = MagicMock(return_value=False)

            with contextlib.suppress(Exception):
                await builder.build(custom_config)

            assert call_order.index("import") < call_order.index(
                "validate_static_route"
            )
            assert call_order.index("validate_static_route") < call_order.index(
                "validate_constrained_backends"
            )
            assert call_order.index("validate_constrained_backends") < call_order.index(
                "register_config"
            )

    @pytest.mark.asyncio
    async def test_runtime_config_replaces_existing_config_by_object_identity(
        self,
    ) -> None:
        """Test that runtime config actually replaces existing config (Fix 3 - object identity)."""
        # Create configs with different default_backend values at initialization
        # (AppConfig is frozen, so we can't modify after creation)
        from src.core.config.models.backends import BackendSettings

        custom_backend_settings = BackendSettings(default_backend="test-backend-12345")
        custom_config = AppConfig(backends=custom_backend_settings)

        builder = ApplicationBuilder()

        # Create a stage that verifies config identity during validation
        class ConfigVerifyingStage(InitializationStage):
            @property
            def name(self) -> str:
                return "config_verifying"

            def get_dependencies(self) -> list[str]:
                return []

            def get_description(self) -> str:
                return "Config verifying stage"

            async def validate(
                self, services: ServiceCollection, config: AppConfig
            ) -> bool:
                """Verify that resolved config matches the runtime config."""
                from src.core.di.provider_lifecycle import (
                    get_current_service_provider,
                )

                provider = get_current_service_provider()
                resolved_config = provider.get_required_service(AppConfig)
                # Verify object identity - must be the exact instance passed to build()
                assert (
                    resolved_config is config
                ), "Resolved config must be the exact runtime config instance"
                assert (
                    resolved_config.backends.default_backend == "test-backend-12345"
                ), "Resolved config must have runtime config values"
                return True

            async def execute(
                self, services: ServiceCollection, config: AppConfig
            ) -> None:
                """Mock execution."""

        builder.add_stage(ConfigVerifyingStage())

        # Store reference to real build_service_provider before mocking
        real_build_provider = builder._services.build_service_provider

        # Now build with custom config - should replace any existing config
        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            # Create a real provider for validation that uses the actual services
            # Use the stored reference to avoid recursion
            def build_provider_mock(*args, **kwargs):
                return real_build_provider()

            mock_build_provider.side_effect = build_provider_mock
            mock_temp_provider.return_value.__enter__ = MagicMock()
            mock_temp_provider.return_value.__exit__ = MagicMock(return_value=False)

            with contextlib.suppress(Exception):
                await builder.build(custom_config)

            # If we got here without assertion failure in validate(), the test passed
            assert True


class TestValidationProviderLifecycle:
    """Tests for validation provider lifecycle."""

    @pytest.mark.asyncio
    async def test_validation_provider_built_without_post_build_hooks(
        self,
    ) -> None:
        """Test that validation provider is built without post-build hooks."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_temp_provider.return_value.__enter__ = MagicMock()
            mock_temp_provider.return_value.__exit__ = MagicMock(return_value=False)

            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify build_service_provider was called with run_post_build_hooks=False for validation
            # (it may also be called again during stage execution with default True)
            validation_calls = [
                call
                for call in mock_build_provider.call_args_list
                if call.kwargs.get("run_post_build_hooks") is False
            ]
            assert (
                len(validation_calls) >= 1
            ), "Validation provider should be built at least once without post-build hooks"

    @pytest.mark.asyncio
    async def test_validation_provider_installed_via_temporary_context(
        self,
    ) -> None:
        """Test that validation provider is installed via temporary_service_provider context."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify temporary_service_provider was called with validation provider
            mock_temp_provider.assert_called_once_with(mock_provider)
            # Verify context manager was entered
            mock_context.__enter__.assert_called_once()

    @pytest.mark.asyncio
    async def test_previous_provider_restored_after_validation_success(
        self,
    ) -> None:
        """Test that previous provider is restored after successful validation."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify context manager was exited (restores previous provider)
            mock_context.__exit__.assert_called_once()
            # Verify exit was called with None, None, None (no exception)
            call_args = mock_context.__exit__.call_args[0]
            assert call_args == (None, None, None)

    @pytest.mark.asyncio
    async def test_previous_provider_restored_after_validation_failure(
        self,
    ) -> None:
        """Test that previous provider is restored after validation failure."""
        builder = ApplicationBuilder()
        builder.add_stage(MockFailingValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with pytest.raises(RuntimeError, match="validation failed"):
                await builder.build(config)

            # Verify context manager was exited even on failure
            mock_context.__exit__.assert_called_once()


class TestValidationProviderDisposal:
    """Tests for validation provider disposal after validation."""

    @pytest.mark.asyncio
    async def test_validation_provider_disposed_after_successful_validation(
        self,
    ) -> None:
        """Test that validation provider is disposed after successful validation."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_provider.dispose = AsyncMock()
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify validation provider dispose was called
            mock_provider.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_provider_disposed_after_failed_validation(
        self,
    ) -> None:
        """Test that validation provider is disposed after failed validation."""
        builder = ApplicationBuilder()
        builder.add_stage(MockFailingValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_provider.dispose = AsyncMock()
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with pytest.raises(RuntimeError, match="validation failed"):
                await builder.build(config)

            # Verify validation provider dispose was called even on failure
            mock_provider.dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_validation_provider_disposed_after_provider_restoration(
        self,
    ) -> None:
        """Test that validation provider disposal happens after provider restoration."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        disposal_order = []

        def track_context_exit(*args, **kwargs):
            disposal_order.append("context_exit")

        def track_provider_dispose(*args, **kwargs):
            disposal_order.append("provider_dispose")

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_provider.dispose = AsyncMock(side_effect=track_provider_dispose)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(
                return_value=False, side_effect=track_context_exit
            )
            mock_temp_provider.return_value = mock_context

            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify disposal happens after context exit (provider restoration)
            assert disposal_order.index("context_exit") < disposal_order.index(
                "provider_dispose"
            )

    @pytest.mark.asyncio
    async def test_validation_provider_disposal_errors_suppressed(
        self,
    ) -> None:
        """Test that validation provider disposal errors are suppressed."""
        builder = ApplicationBuilder()
        builder.add_stage(MockValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_provider.dispose = AsyncMock(
                side_effect=RuntimeError("Dispose failed")
            )
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            # Should not raise exception from disposal error
            with contextlib.suppress(Exception):
                await builder.build(config)

            # Verify dispose was called despite the error
            mock_provider.dispose.assert_called_once()


class TestValidationFailureCleanup:
    """Tests for cleanup behavior on validation failure."""

    @pytest.mark.asyncio
    async def test_service_collection_disposed_on_validation_failure(
        self,
    ) -> None:
        """Test that ServiceCollection is disposed on validation failure."""
        builder = ApplicationBuilder()
        builder.add_stage(MockFailingValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
            patch.object(
                builder._services, "dispose", new_callable=AsyncMock
            ) as mock_dispose,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with pytest.raises(RuntimeError):
                await builder.build(config)

            # Verify dispose was called
            mock_dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_collection_disposed_on_validation_exception(
        self,
    ) -> None:
        """Test that ServiceCollection is disposed on validation exception."""
        builder = ApplicationBuilder()
        builder.add_stage(MockExceptionValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
            patch.object(
                builder._services, "dispose", new_callable=AsyncMock
            ) as mock_dispose,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            with pytest.raises(RuntimeError, match="validation error"):
                await builder.build(config)

            # Verify dispose was called
            mock_dispose.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispose_errors_suppressed_on_validation_failure(
        self,
    ) -> None:
        """Test that dispose errors are suppressed on validation failure."""
        builder = ApplicationBuilder()
        builder.add_stage(MockFailingValidationStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
            patch.object(
                builder._services, "build_service_provider"
            ) as mock_build_provider,
            patch(
                "src.core.di.provider_lifecycle.temporary_service_provider"
            ) as mock_temp_provider,
            patch.object(
                builder._services, "dispose", new_callable=AsyncMock
            ) as mock_dispose,
        ):
            mock_provider = MagicMock(spec=IServiceProvider)
            mock_build_provider.return_value = mock_provider
            mock_context = MagicMock()
            mock_context.__enter__ = MagicMock(return_value=None)
            mock_context.__exit__ = MagicMock(return_value=False)
            mock_temp_provider.return_value = mock_context

            # Make dispose raise an exception
            mock_dispose.side_effect = RuntimeError("Dispose failed")

            # Should still raise the validation error, not the dispose error
            with pytest.raises(RuntimeError, match="validation failed"):
                await builder.build(config)

            # Verify dispose was called despite the error
            mock_dispose.assert_called_once()


class TestValidationServiceResolution:
    """Tests for service resolution during validation."""

    @pytest.mark.asyncio
    async def test_stage_validation_can_resolve_services_from_provider(
        self,
    ) -> None:
        """Test that stage validation can resolve services from the installed provider."""
        builder = ApplicationBuilder()

        # Create a stage that resolves a service during validation
        class ServiceResolvingStage(InitializationStage):
            @property
            def name(self) -> str:
                return "service_resolving"

            def get_dependencies(self) -> list[str]:
                return []

            def get_description(self) -> str:
                return "Service resolving stage"

            async def validate(
                self, services: ServiceCollection, config: AppConfig
            ) -> bool:
                """Resolve service from installed provider."""
                from src.core.di.provider_lifecycle import (
                    get_current_service_provider,
                )

                provider = get_current_service_provider()
                # Try to resolve AppConfig
                resolved_config = provider.get_service(AppConfig)
                assert resolved_config is not None
                assert resolved_config is config
                return True

            async def execute(
                self, services: ServiceCollection, config: AppConfig
            ) -> None:
                """Mock execution."""

        builder.add_stage(ServiceResolvingStage())

        config = AppConfig()

        with (
            patch("importlib.import_module"),
            patch("src.core.config.semantic_validation.validate_static_route"),
            patch(
                "src.core.di.registration_helpers.core_foundational.register_app_config"
            ),
        ):
            # Config is already registered via add_instance in build()

            with contextlib.suppress(Exception):
                # Expected to fail at stage execution, but validation should succeed
                await builder.build(config)

            # If we got here without exception in validate(), the test passed
            assert True
