from __future__ import annotations

import pytest
from src.core.app.application_builder import ApplicationBuilder
from src.core.app.stages import (
    BackendStage,
    CommandStage,
    ControllerStage,
    CoreServicesStage,
    InfrastructureStage,
    ProcessorStage,
)
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendSettings,
    LoggingConfig,
    LogLevel,
    SessionConfig,
    ToolCallReactorConfig,
)


@pytest.mark.asyncio
async def test_app_builds_successfully_with_minimal_config():
    """
    Tests that the application builder can successfully build the application with a minimal configuration.
    This test is designed to catch regressions in the startup process, such as dependency injection issues.
    """
    try:
        # Create an AppConfig instance directly
        config = AppConfig(
            backends=BackendSettings(
                static_route="gemini-oauth-plan:gemini-2.5-pro",
            ),
            port=8000,
            auth=AuthConfig(disable_auth=True),
            logging=LoggingConfig(
                level=LogLevel.DEBUG,
                capture_file="logs/wire_capture.log",
            ),
            session=SessionConfig(
                project_dir_resolution_mode="deterministic",
                tool_call_reactor=ToolCallReactorConfig(
                    pytest_full_suite_steering_enabled=True,
                    pytest_context_saving_enabled=True,
                ),
                pytest_compression_enabled=True,
            ),
        )

        builder = ApplicationBuilder()

        # Register all production stages
        builder.add_stage(InfrastructureStage())
        builder.add_stage(CoreServicesStage())
        builder.add_stage(BackendStage())
        builder.add_stage(CommandStage())
        builder.add_stage(ProcessorStage())
        builder.add_stage(ControllerStage())

        # The build process should complete without raising any exceptions
        app = await builder.build(config)

        assert app is not None

    except Exception as e:
        pytest.fail(f"Application build failed with exception: {e}")
