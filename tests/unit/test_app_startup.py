from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from src.core.app.application_builder import ApplicationBuilder
from src.core.app.stages import (
    BackendStage,
    CommandStage,
    ControllerStage,
    CoreServicesStage,
    InfrastructureStage,
    ProcessorStage,
)
from src.core.common.exceptions import ConfigurationError
from src.core.config.app_config import (
    AppConfig,
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
    LogLevel,
    SessionConfig,
    ToolCallReactorConfig,
)
from src.core.domain.responses import ResponseEnvelope
from src.core.services.backend_discovery import reset_backend_discovery_state
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import backend_registry


@pytest.mark.asyncio
async def test_app_builds_successfully_with_minimal_core_config():
    """
    Tests that the application builder can successfully build the application with a minimal configuration.
    This test is designed to catch regressions in the startup process, such as dependency injection issues.
    """
    try:
        # Create an AppConfig instance directly
        config = AppConfig(
            backends=BackendSettings(
                static_route="openai:gpt-4o-mini",
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


@pytest.mark.asyncio
async def test_app_builds_successfully_without_plugin_entry_points():
    """Startup should succeed in core-only mode when no plugin entry points exist."""
    config = AppConfig(
        backends=BackendSettings(static_route="openai:gpt-4o-mini"),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    with patch(
        "src.core.services.backend_plugin_discovery._load_entry_points", return_value=[]
    ):
        app = await builder.build(config)

    assert app is not None


@pytest.mark.asyncio
async def test_core_only_mode_keeps_api_key_backend_factory_operational():
    """Core-only startup should still allow API-key backend instantiation."""
    config = AppConfig(
        backends=BackendSettings(static_route="openai:gpt-4o-mini"),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    with patch(
        "src.core.services.backend_plugin_discovery._load_entry_points", return_value=[]
    ):
        app = await builder.build(config)

    assert app is not None

    factory = BackendFactory(
        httpx_client=MagicMock(spec=httpx.AsyncClient),
        backend_registry=backend_registry,
        config=config,
        translation_service=MagicMock(),
    )
    backend = factory.create_backend("openai")

    assert backend is not None
    assert hasattr(backend, "chat_completions")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "backend_type", ["openai", "anthropic", "gemini", "openrouter"]
)
async def test_core_only_mode_keeps_core_api_key_backends_operational(
    backend_type: str,
):
    """Core-only mode should keep API-key-based core backends available."""
    config = AppConfig(
        backends=BackendSettings(static_route="openai:gpt-4o-mini"),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    with patch(
        "src.core.services.backend_plugin_discovery._load_entry_points", return_value=[]
    ):
        app = await builder.build(config)

    assert app is not None

    factory = BackendFactory(
        httpx_client=MagicMock(spec=httpx.AsyncClient),
        backend_registry=backend_registry,
        config=config,
        translation_service=MagicMock(),
    )
    backend = factory.create_backend(backend_type)

    assert backend is not None
    assert hasattr(backend, "chat_completions")


@pytest.mark.xdist_group("isolated")
def test_core_only_mode_keeps_openai_request_path_operational(monkeypatch) -> None:
    """Core-only mode should still serve OpenAI protocol requests.

    Marked for xdist isolation because it mutates process environment
    variables (OPENAI_API_KEY) and builds a full app via build_compat
    (which spawns threads). Running this alongside other tests on the
    same worker can cause race conditions with module-level connector
    imports and the global backend_registry singleton.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-key")
    config = AppConfig(
        backends=BackendSettings(
            static_route="openai:gpt-4o-mini",
            openai=BackendConfig(api_key="dummy-key"),
        ),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    with patch(
        "src.core.services.backend_plugin_discovery._load_entry_points", return_value=[]
    ):
        app = ApplicationBuilder().add_default_stages().build_compat(config)

    stubbed_response = ResponseEnvelope(
        content={
            "id": "chatcmpl-core-only",
            "object": "chat.completion",
            "created": 0,
            "model": "openai:gpt-4o-mini",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        },
        status_code=200,
        headers={},
    )

    with (
        patch(
            "src.connectors.openai.OpenAIConnector.chat_completions",
            return_value=stubbed_response,
        ),
        TestClient(app) as client,
    ):
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "openai:gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "openai:gpt-4o-mini"
    assert payload["choices"][0]["message"]["content"] == "ok"


@pytest.mark.asyncio
async def test_app_builds_when_plugin_entry_point_load_fails_fail_open(
    caplog: pytest.LogCaptureFixture,
):
    """Broken plugin entry points should not prevent startup."""

    def _raise_load_error():
        raise ImportError("simulated plugin load failure")

    broken_entry_point = SimpleNamespace(
        name="broken-oauth",
        load=_raise_load_error,
        module="broken.plugin",
        attr="provider",
        dist=SimpleNamespace(name="broken-plugin"),
    )

    config = AppConfig(
        backends=BackendSettings(static_route="openai:gpt-4o-mini"),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    reset_backend_discovery_state()
    with (
        patch(
            "src.core.services.backend_plugin_discovery._load_entry_points",
            return_value=[broken_entry_point],
        ),
        patch(
            "src.core.services.backend_plugin_discovery._resolve_core_version",
            return_value="0.1.0",
        ),
        caplog.at_level("WARNING"),
    ):
        app = await builder.build(config)

    assert app is not None
    assert "Failed to load backend plugin entry point 'broken-oauth'" in caplog.text


@pytest.mark.asyncio
async def test_app_build_fails_without_viable_backend_path_for_missing_extracted():
    """Startup should fail when only missing extracted backends are configured."""
    config = AppConfig(
        backends=BackendSettings(default_backend="gemini-oauth-plan"),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())

    with (
        patch(
            "src.core.config.semantic_validation.backend_registry.get_registered_backends",
            return_value=["openai", "anthropic", "gemini"],
        ),
        pytest.raises(ConfigurationError) as exc_info,
    ):
        await builder.build(config)

    exc = exc_info.value
    assert exc.details.get("error_code") == "missing_extracted_backends_no_viable_path"
    assert "gemini-oauth-plan" in exc.details.get("missing_extracted_backends", [])


@pytest.mark.asyncio
async def test_app_build_warns_but_starts_when_missing_extracted_has_viable_core_path(
    caplog: pytest.LogCaptureFixture,
):
    """Startup should continue with warning when core alternatives are configured."""
    config = AppConfig(
        backends=BackendSettings(
            default_backend="openai",
            static_route="gemini-oauth-plan:gemini-2.5-pro",
        ),
        auth=AuthConfig(disable_auth=True),
        logging=LoggingConfig(level=LogLevel.INFO),
    )

    builder = ApplicationBuilder()
    builder.add_stage(InfrastructureStage())
    builder.add_stage(CoreServicesStage())
    builder.add_stage(BackendStage())

    with (
        caplog.at_level("WARNING"),
        patch(
            "src.core.config.semantic_validation.backend_registry.get_registered_backends",
            return_value=["openai", "anthropic", "gemini"],
        ),
    ):
        app = await builder.build(config)

    assert app is not None
    assert (
        "Startup continues because registered alternatives are configured"
        in caplog.text
    )
    assert "pip install llm-interactive-proxy[oauth]" in caplog.text
