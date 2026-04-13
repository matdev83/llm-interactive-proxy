"""
Tests for post-build hooks.

These tests verify that:
- Post-build hooks run correctly after provider build
- Tool-call handler registration runs during post-build
- MiddlewareApplicationManager can be resolved after streaming registrar runs
- Validation-only provider build skips post-build hooks
"""

from __future__ import annotations

from unittest.mock import patch

from src.core.config.app_config import AppConfig
from src.core.di.container import ServiceCollection
from src.core.di.provider_lifecycle import post_build_hooks
from src.core.di.registrations import core, streaming
from src.core.interfaces.di_interface import IServiceProvider
from src.core.services.middleware_application_manager import (
    MiddlewareApplicationManager,
)


class TestPostBuildHooks:
    """Test post-build hooks functionality."""

    def test_post_build_hooks_run_successfully(self) -> None:
        """Verify post-build hooks run without errors after provider build."""
        services = ServiceCollection()
        config = AppConfig()

        # Register all services (core then streaming)
        core.register(services, config)
        streaming.register(services, config)

        # Build provider
        provider = services.build_service_provider()

        # Post-build hooks should run without errors
        post_build_hooks(provider)

        # Verify MiddlewareApplicationManager is available (required by post-build hooks)
        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None

    def test_register_tool_call_handlers_invoked_from_post_build_hooks(self) -> None:
        """Post-build hooks must invoke tool-call handler registration."""
        services = ServiceCollection()
        config = AppConfig()

        core.register(services, config)
        streaming.register(services, config)

        provider = services.build_service_provider()

        with patch(
            "src.core.di.registration_helpers.post_build_actions.register_tool_call_handlers"
        ) as mock_register:
            post_build_hooks(provider)

        mock_register.assert_called_once_with(provider)

    def test_middleware_application_manager_resolved_in_post_build(self) -> None:
        """Verify MiddlewareApplicationManager can be resolved during post-build hooks."""
        services = ServiceCollection()
        config = AppConfig()

        # Register all services
        core.register(services, config)
        streaming.register(services, config)

        # Build provider
        provider = services.build_service_provider()

        # Verify MiddlewareApplicationManager is registered before post-build hooks
        manager = provider.get_service(MiddlewareApplicationManager)
        assert manager is not None

        # Post-build hooks should be able to access it
        post_build_hooks(provider)

        # Verify it's still accessible after hooks
        manager2 = provider.get_service(MiddlewareApplicationManager)
        assert manager2 is not None
        assert manager is manager2

    def test_validation_only_build_skips_post_build_hooks(self) -> None:
        """Verify that building a provider with run_post_build_hooks=False skips hooks."""
        services = ServiceCollection()
        config = AppConfig()

        # Register minimal services needed for provider build
        core.register(services, config)
        streaming.register(services, config)

        # Track whether post_build_hooks was called
        hooks_called = False

        def track_hooks_call(provider_arg: IServiceProvider) -> None:
            nonlocal hooks_called
            hooks_called = True
            # Call original to avoid breaking other tests
            post_build_hooks(provider_arg)

        # Monkeypatch post_build_hooks at the module where it's imported
        with patch(
            "src.core.di.provider_lifecycle.post_build_hooks",
            side_effect=track_hooks_call,
        ):
            # Build provider with hooks disabled
            provider = services.build_service_provider(run_post_build_hooks=False)

            # Verify hooks were NOT called
            assert (
                not hooks_called
            ), "Post-build hooks should not run when run_post_build_hooks=False"

            # Verify provider is still functional (can resolve services)
            manager = provider.get_service(MiddlewareApplicationManager)
            assert manager is not None

    def test_default_build_runs_post_build_hooks(self) -> None:
        """Verify that default build (no parameter) still runs post-build hooks."""
        services = ServiceCollection()
        config = AppConfig()

        # Register minimal services
        core.register(services, config)
        streaming.register(services, config)

        # Track whether post_build_hooks was called
        hooks_called = False

        def track_hooks_call(provider_arg: IServiceProvider) -> None:
            nonlocal hooks_called
            hooks_called = True
            # Call original to avoid breaking other tests
            post_build_hooks(provider_arg)

        # Monkeypatch post_build_hooks at the module where it's imported
        with patch(
            "src.core.di.provider_lifecycle.post_build_hooks",
            side_effect=track_hooks_call,
        ):
            # Build provider with default behavior (should run hooks)
            provider = services.build_service_provider()

            # Verify hooks WERE called
            assert hooks_called, "Post-build hooks should run by default"

            # Verify provider is functional
            manager = provider.get_service(MiddlewareApplicationManager)
            assert manager is not None

    def test_post_build_hooks_execute_registered_plugin_hooks(self) -> None:
        """Plugin hooks should execute after core post-build actions."""
        services = ServiceCollection()
        config = AppConfig()
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider(run_post_build_hooks=False)

        hook_calls: list[IServiceProvider] = []

        def plugin_hook(received_provider: IServiceProvider) -> None:
            hook_calls.append(received_provider)

        with (
            patch(
                "src.core.di.registration_helpers.post_build_actions.register_tool_call_handlers"
            ),
            patch(
                "src.core.common.backend_discovery_state.get_plugin_post_build_hooks",
                return_value=[("hooked-oauth", plugin_hook)],
            ),
        ):
            post_build_hooks(provider)

        assert hook_calls == [provider]

    def test_post_build_hooks_handle_plugin_hook_failures_fail_open(
        self, caplog
    ) -> None:
        """Plugin hook failures should log warnings and continue startup."""
        services = ServiceCollection()
        config = AppConfig()
        core.register(services, config)
        streaming.register(services, config)
        provider = services.build_service_provider(run_post_build_hooks=False)

        def failing_hook(_provider: IServiceProvider) -> None:
            raise RuntimeError("hook failed")

        with (
            patch(
                "src.core.di.registration_helpers.post_build_actions.register_tool_call_handlers"
            ),
            patch(
                "src.core.common.backend_discovery_state.get_plugin_post_build_hooks",
                return_value=[("broken-oauth", failing_hook)],
            ),
            caplog.at_level("WARNING"),
        ):
            post_build_hooks(provider)

        assert "Plugin post-build hook failed for backend 'broken-oauth'" in caplog.text

    def test_lazy_global_provider_build_runs_post_build_hooks_once(self) -> None:
        """Global lazy provider construction should execute post-build hooks once."""
        from src.core.di import provider_lifecycle

        services = ServiceCollection()
        hook_calls: list[IServiceProvider] = []

        def track_hooks_call(provider_arg: IServiceProvider) -> None:
            hook_calls.append(provider_arg)

        provider_lifecycle.set_service_provider(None)
        try:
            with (
                patch(
                    "src.core.di.services.get_service_collection",
                    return_value=services,
                ),
                patch("src.core.di.services.register_core_services"),
                patch(
                    "src.core.di.provider_lifecycle.post_build_hooks",
                    side_effect=track_hooks_call,
                ),
            ):
                provider = provider_lifecycle.get_or_build_service_provider()

            assert hook_calls == [provider]
        finally:
            provider_lifecycle.set_service_provider(None)
