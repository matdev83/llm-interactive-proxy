"""
Test-specific application builder.

This module provides builders and utilities specifically designed for testing,
making it easy to create applications with mock services and test doubles.
"""

from __future__ import annotations

# type: ignore[unreachable]
import asyncio
import logging
from typing import Any, cast

from fastapi import FastAPI

from src.core.app.application_builder import ApplicationBuilder
from src.core.app.stages import (
    CommandStage,
    ControllerStage,
    CoreServicesStage,
    InfrastructureStage,
    ProcessorStage,
)
from src.core.app.stages.test_stages import (
    CustomTestStage,
    MinimalTestStage,
    MockBackendStage,
    RealBackendTestStage,
)
from src.core.app.test_utils import get_app_config_from_state
from src.core.config.app_config import AppConfig

logger = logging.getLogger(__name__)


class ApplicationTestBuilder(ApplicationBuilder):
    """
    Application builder specifically designed for testing.

    This builder provides convenient methods for creating test applications
    with different levels of mocking and service replacement.
    """

    # Prevent pytest from collecting this as a test class
    __test__ = False

    def add_test_stages(self) -> ApplicationTestBuilder:
        """
        Add stages optimized for testing with mock backends.

        This creates a full application but replaces backend services
        with mocks for predictable testing.

        Returns:
            Self for method chaining
        """
        self.add_stage(CoreServicesStage())
        self.add_stage(InfrastructureStage())
        self.add_stage(MockBackendStage())  # Mock backends instead of real ones
        self.add_stage(CommandStage())
        self.add_stage(ProcessorStage())
        self.add_stage(ControllerStage())
        return self

    def add_minimal_stages(self) -> ApplicationTestBuilder:
        """
        Add only minimal stages for lightweight testing.

        This creates a minimal application with only core services
        and basic mocks, useful for unit tests that don't need
        full application functionality.

        Returns:
            Self for method chaining
        """
        self.add_stage(CoreServicesStage())
        self.add_stage(MinimalTestStage())
        return self

    def add_custom_stage(
        self,
        name: str,
        services: dict[type, Any],
        dependencies: list[str] | None = None,
    ) -> ApplicationTestBuilder:
        """

        Returns:
            Self for method chaining
        """
        custom_stage = CustomTestStage(name, services, dependencies)
        self.add_stage(custom_stage)
        return self

    def replace_stage(
        self, stage_name: str, replacement_stage: Any
    ) -> ApplicationTestBuilder:
        """
        Replace an existing stage with a different implementation.

        This allows tests to replace specific stages (e.g., replace
        the backend stage with a mock stage) while keeping others.

        Args:
            stage_name: Name of the stage to replace
            replacement_stage: The replacement stage instance

        Returns:
            Self for method chaining
        """
        # Remove existing stage if present
        if stage_name in self._stages:
            del self._stages[stage_name]

        # Add replacement stage
        self.add_stage(replacement_stage)
        return self


# Convenience functions for common test scenarios


async def build_test_app_async(config: AppConfig | None = None) -> FastAPI:
    """
    Build a test application asynchronously with mock backends.

    Args:
        config: Test configuration, defaults to basic test config

    Returns:
        FastAPI application configured for testing
    """
    if config is None:
        # Allow tests to patch/load a custom config via the standard loader.
        try:
            from src.core.config.app_config import load_config

            cfg = (
                load_config()
            )  # tests may have patched this to return a custom AppConfig
            if cfg is not None:
                config = cfg
            else:  # type: ignore[unreachable]
                config = create_test_config()  # type: ignore[unreachable]
        except Exception:
            config = create_test_config()
    builder = ApplicationTestBuilder().add_test_stages()
    app = await builder.build(config)

    # Install redaction filter after the app is created to avoid affecting
    # staged initialization and backend registration during tests.
    try:
        from src.core.common.logging_utils import (
            discover_api_keys_from_config_and_env,
            install_api_key_redaction_filter,
        )

        # Use IApplicationState to get config for API key discovery
        app_config = get_app_config_from_state(app)
        api_keys = discover_api_keys_from_config_and_env(app_config)
        install_api_key_redaction_filter(api_keys)
    except Exception:
        # Don't fail test app creation if redaction installation fails
        pass

    return app


def build_test_app(config: AppConfig | None = None) -> FastAPI:
    """
    Build a test application synchronously with mock backends.

    Args:
        config: Test configuration, defaults to basic test config

    Returns:
        FastAPI application configured for testing
    """
    if config is None:
        try:
            from src.core.config.app_config import load_config

            cfg = load_config()
            if cfg is not None:
                config = cfg
            else:  # type: ignore[unreachable]
                config = create_test_config()  # type: ignore[unreachable]
        except Exception:
            config = create_test_config()

    try:
        asyncio.get_running_loop()
        # If we're in an async context, run in a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, build_test_app_async(config))
            return future.result()
    except RuntimeError:
        # No running loop, use asyncio.run directly
        return asyncio.run(build_test_app_async(config))


async def build_minimal_test_app_async(config: AppConfig | None = None) -> FastAPI:
    """
    Build a minimal test application asynchronously.

    Args:
        config: Test configuration, defaults to basic test config

    Returns:
        Minimal FastAPI application for lightweight testing
    """
    if config is None:
        config = create_test_config()
    builder = ApplicationTestBuilder().add_minimal_stages()
    app = await builder.build(config)

    try:
        from src.core.common.logging_utils import (
            discover_api_keys_from_config_and_env,
            install_api_key_redaction_filter,
        )

        # Use IApplicationState to get config for API key discovery
        app_config = get_app_config_from_state(app)
        api_keys = discover_api_keys_from_config_and_env(app_config)
        install_api_key_redaction_filter(api_keys)
    except Exception:
        pass

    return app


def build_minimal_test_app(config: AppConfig | None = None) -> FastAPI:
    """
    Build a minimal test application synchronously.

    Args:
        config: Test configuration, defaults to basic test config

    Returns:
        Minimal FastAPI application for lightweight testing
    """
    if config is None:
        config = create_test_config()

    try:
        asyncio.get_running_loop()
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, build_minimal_test_app_async(config))
            return future.result()
    except RuntimeError:
        return asyncio.run(build_minimal_test_app_async(config))


def create_test_config() -> AppConfig:
    """
    Create a basic test configuration.

    Returns:
        AppConfig instance suitable for testing
    """
    # Use the LLM_BACKEND environment variable if set, otherwise default to "openai"
    import os

    from src.core.config.app_config import (
        AuthConfig,
        BackendConfig,
        BackendSettings,
        LoggingConfig,
        LogLevel,
        SessionConfig,
    )

    default_backend = os.environ.get("LLM_BACKEND", "openai")

    # Set up backend config based on the default backend
    backend_settings = BackendSettings(default_backend=default_backend)

    # Always include openai as a fallback
    backend_settings.__dict__["openai"] = BackendConfig(api_key=["test_key"])

    # Add the default backend if it's not openai
    if default_backend != "openai":
        backend_settings.__dict__[default_backend] = BackendConfig(
            api_key=[f"test_key_{default_backend}"]
        )

    # Get command prefix from environment if set
    command_prefix = os.environ.get("COMMAND_PREFIX", "!/")

    return AppConfig(
        host="localhost",
        port=9000,
        proxy_timeout=10,
        command_prefix=command_prefix,
        backends=backend_settings,
        auth=AuthConfig(disable_auth=True, api_keys=["test-proxy-key"]),
        session=SessionConfig(cleanup_enabled=False, default_interactive_mode=True),
        logging=LoggingConfig(level=LogLevel.WARNING),  # Quiet during tests
    )


# Example usage patterns for different test scenarios


def build_httpx_mock_test_app(config: AppConfig | None = None) -> FastAPI:
    """
    Build a test app with real backends for HTTP mocking tests.

    This uses real backend services that make HTTP calls, which can then
    be mocked using HTTPXMock or similar tools. This is useful for tests
    that need to mock HTTP responses but want to test the full request flow.

    Args:
        config: Test configuration, defaults to basic test config

    Returns:
        FastAPI application with real backends for HTTP mocking
    """
    if config is None:
        config = create_test_config()

    # Use real backend services for HTTP mocking
    builder = (
        ApplicationTestBuilder()
        .add_stage(CoreServicesStage())
        .add_stage(InfrastructureStage())
        .add_stage(RealBackendTestStage())  # Real backends for HTTP mocking
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )

    return cast(FastAPI, asyncio.run(builder.build(config)))


def build_integration_test_app(config: AppConfig | None = None) -> FastAPI:
    """
    Build an app for integration testing with real-like services but test data.

    This uses real service implementations but with test configuration
    and isolated data stores.
    """
    if config is None:
        config = create_test_config()

    # Use mostly real stages but with test configuration
    builder = (
        ApplicationTestBuilder()
        .add_stage(CoreServicesStage())
        .add_stage(InfrastructureStage())
        .add_stage(MockBackendStage())  # Still mock backends for predictability
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )

    return cast(FastAPI, asyncio.run(builder.build(config)))


def build_unit_test_app(
    services_to_mock: dict[type, Any], config: AppConfig | None = None
) -> FastAPI:
    """
    Build an app for unit testing with specific services mocked.

    Args:
        services_to_mock: Dictionary of service types to mock instances
        config: Test configuration

    Returns:
        FastAPI app with specified services mocked
    """
    if config is None:
        config = create_test_config()

    builder: ApplicationTestBuilder = ApplicationTestBuilder()
    builder = builder.add_stage(CoreServicesStage())  # type: ignore[assignment]
    builder = builder.add_custom_stage(
        "unit_test_mocks", services_to_mock, ["core_services"]
    )  # type: ignore[assignment]

    return cast(FastAPI, asyncio.run(builder.build(config)))


"""
USAGE EXAMPLES:

# Basic test app with all mocks
app = build_test_app()

# Minimal app for lightweight unit tests
app = build_minimal_test_app()

# Custom app with specific mocks
from src.core.interfaces.backend_service_interface import IBackendService
mock_backend = MagicMock(spec=IBackendService)
app = build_unit_test_app({IBackendService: mock_backend})

# Integration test app
app = build_integration_test_app()

# Completely custom test app
builder = (ApplicationTestBuilder()
           .add_stage(CoreServicesStage())
           .add_custom_stage("my_mocks", {MyService: my_mock})
           .add_stage(ProcessorStage()))
app = asyncio.run(builder.build(test_config))

This approach makes testing much more flexible and maintainable compared
to the original complex conftest.py approach.
"""

# Export TestApplicationBuilder as an alias for backwards compatibility
TestApplicationBuilder = ApplicationTestBuilder
