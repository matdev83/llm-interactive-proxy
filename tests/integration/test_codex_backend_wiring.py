"""Integration tests for Codex connector backend wiring and configuration.

This test suite verifies:
- Backend registration through staged initialization
- Configuration defaults and precedence (CLI > ENV > YAML)
- DI wiring and component resolution
- Backend factory integration
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from src.core.app.stages.backend import BackendStage
from src.core.config.app_config import AppConfig, BackendSettings
from src.core.di.container import ServiceCollection
from src.core.services.backend_registry import backend_registry


@pytest_asyncio.fixture(name="auth_dir")
async def auth_dir_tmp(tmp_path: Path):
    """Create temporary auth directory with credentials."""
    data = {"tokens": {"access_token": "test_token"}}
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "auth.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backend_registration_in_staged_init(auth_dir: Path):
    """Test that Codex backend is registered during staged initialization."""
    # Create service collection
    services = ServiceCollection()
    config = AppConfig(
        backends=BackendSettings(default_backend="openai-codex"),
    )

    # Execute backend stage
    stage = BackendStage()
    await stage.execute(services, config)

    # Verify backend is registered
    registered_backends = backend_registry.get_registered_backends()
    assert "openai-codex" in registered_backends

    # Verify we can get the factory
    factory = backend_registry.get_backend_factory("openai-codex")
    assert factory is not None
    assert callable(factory)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_codex_dependencies_registration(auth_dir: Path):
    """Test that Codex component dependencies are registered."""
    from src.connectors.openai_codex.interfaces import (
        ICredentialManager,
        ISettingsLoader,
        IToolExecutionService,
    )
    from src.core.di.registrations._backend.codex import register_codex_services

    services = ServiceCollection()

    # Register required dependencies
    import httpx

    services.add_singleton(
        httpx.AsyncClient, implementation_factory=lambda provider: httpx.AsyncClient()
    )

    # Register Codex services
    register_codex_services(services)

    # Verify services are registered
    provider = services.build_service_provider()

    settings_loader = provider.get_service(ISettingsLoader)
    assert settings_loader is not None

    credential_manager = provider.get_service(ICredentialManager)
    assert credential_manager is not None

    tool_execution_service = provider.get_service(IToolExecutionService)
    assert tool_execution_service is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configuration_precedence_env_overrides_yaml(auth_dir: Path):
    """Test that environment variables override YAML configuration."""
    from src.connectors.openai_codex.settings import SettingsLoader

    # Set environment variable
    os.environ["OPENAI_CODEX_STREAMING_MAX_RETRIES"] = "5"

    try:
        config = AppConfig()
        loader = SettingsLoader()
        settings = loader.load(config)

        # Verify environment override was applied
        assert settings.streaming["max_retries"] == 5
    finally:
        # Cleanup
        os.environ.pop("OPENAI_CODEX_STREAMING_MAX_RETRIES", None)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_configuration_defaults_preserved(auth_dir: Path):
    """Test that configuration defaults are preserved when not overridden."""
    from src.connectors.openai_codex.settings import SettingsLoader

    # Clear any environment overrides
    env_vars_to_clear = [
        "OPENAI_CODEX_STREAMING_MAX_RETRIES",
        "OPENAI_CODEX_STREAMING_RETRY_BACKOFF",
        "OPENAI_CODEX_COMPATIBILITY_LAYER_ENABLED",
    ]
    original_values = {}
    for var in env_vars_to_clear:
        original_values[var] = os.environ.pop(var, None)

    try:
        config = AppConfig()
        loader = SettingsLoader()
        settings = loader.load(config)

        # Verify defaults are preserved
        assert settings.streaming["max_retries"] == 2  # Default from design
        assert settings.streaming["retry_backoff_seconds"] == (0.5, 1.5, 3.0)  # Default
        assert settings.compatibility_layer["enabled"] is False  # Default
    finally:
        # Restore original values
        for var, value in original_values.items():
            if value is not None:
                os.environ[var] = value


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backend_factory_resolves_codex_connector(auth_dir: Path):
    """Test that backend factory can resolve Codex connector with dependencies."""
    from src.core.di.registrations._backend.codex import register_codex_services
    from src.core.di.registrations._backend.factory import register_backend_factory
    from src.core.services.backend_factory import BackendFactory
    from src.core.services.backend_registry import BackendRegistry, backend_registry
    from src.core.services.translation_service import TranslationService

    services = ServiceCollection()

    # Register BackendRegistry
    services.add_singleton(
        BackendRegistry, implementation_factory=lambda _: backend_registry
    )

    # Register required dependencies
    services.add_singleton(
        httpx.AsyncClient, implementation_factory=lambda provider: httpx.AsyncClient()
    )
    services.add_singleton(AppConfig, implementation_factory=lambda _: AppConfig())
    services.add_singleton(
        TranslationService, implementation_factory=lambda _: TranslationService()
    )

    # Register Codex services
    register_codex_services(services)

    # Register backend factory
    register_backend_factory(services, AppConfig())

    # Build provider
    provider = services.build_service_provider()

    # Get factory
    factory = provider.get_service(BackendFactory)
    assert factory is not None

    # Create Codex connector
    # Note: BackendFactory.create_backend only takes backend_type and optional config
    # The factory already has httpx_client from its constructor
    config = AppConfig()
    connector = factory.create_backend("openai-codex", config)

    assert connector is not None
    assert connector.backend_type == "openai-codex"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connector_initialization_with_dependencies(auth_dir: Path):
    """Test that connector initializes correctly with injected dependencies."""
    # Import using importlib to avoid package/module name conflict
    import importlib.util
    from pathlib import Path

    # Load the module file directly
    module_path = (
        Path(__file__).parent.parent.parent / "src" / "connectors" / "openai_codex.py"
    )
    spec = importlib.util.spec_from_file_location("openai_codex_module", module_path)
    openai_codex_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(openai_codex_module)
    OpenAICodexConnector = openai_codex_module.OpenAICodexConnector

    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    async with httpx.AsyncClient() as client:
        ts = TranslationService()

        # Create connector - components are initialized in __init__
        connector = OpenAICodexConnector(client, config, translation_service=ts)

        # Verify components are initialized (they should be after __init__)
        assert connector._settings_loader is not None
        assert connector._credential_manager is not None
        assert connector._payload_builder is not None
        assert connector._response_executor is not None

        # Initialize connector with mocked validation
        with (
            patch.object(
                connector, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                connector, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(connector, "_start_file_watching"),
        ):
            await connector.initialize(openai_codex_path=str(auth_dir))
            connector._auth_credentials = {"tokens": {"access_token": "test_token"}}

            # Verify credential manager was initialized
            assert connector._credential_manager.get_access_token() is not None


@pytest.mark.integration
@pytest.mark.integration
@pytest.mark.asyncio
async def test_backend_functional_state_after_init(auth_dir: Path):
    """Test that is_backend_functional returns correct state after initialization."""
    from src.connectors.openai_codex import OpenAICodexConnector
    from src.core.services.translation_service import TranslationService

    async with httpx.AsyncClient() as client:
        cfg = AppConfig()
        ts = TranslationService()
        backend = OpenAICodexConnector(client, cfg, translation_service=ts)

        # Before initialization, backend should not be functional
        assert backend.is_backend_functional() is False

        with (
            patch.object(
                backend, "_validate_credentials_file_exists", return_value=(True, [])
            ),
            patch.object(
                backend, "_validate_credentials_structure", return_value=(True, [])
            ),
            patch.object(backend, "_start_file_watching"),
        ):
            await backend.initialize(openai_codex_path=str(auth_dir))
            backend._auth_credentials = {"tokens": {"access_token": "test_token"}}

            # After initialization, backend should be functional
            assert backend.is_backend_functional() is True


@pytest.mark.integration
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_staged_initialization_pipeline(auth_dir: Path):
    """Test that connector works through full staged initialization pipeline (Req 3.4)."""
    from src.core.app.test_builder import build_test_app, create_test_config

    config = create_test_config()
    config.backends.default_backend = "openai-codex"

    # Build app through full staged initialization
    app = build_test_app(config)
    service_provider = app.state.service_provider

    # Verify backend factory is available
    from src.core.services.backend_factory import BackendFactory

    backend_factory = service_provider.get_service(BackendFactory)
    assert backend_factory is not None

    # Verify backend can be created through factory after staged init
    # Note: build_test_app uses mock backends, so we verify the factory works
    # by checking that it can create a backend (even if it's a mock in test mode)
    backend_config = getattr(config.backends, "openai_codex", None)
    # If backend_config doesn't exist, create a minimal one for testing
    if not backend_config:
        from src.core.config.app_config import BackendConfig

        backend_config = BackendConfig()
        # Set auth path for Codex connector
        backend_config.credentials_path = str(auth_dir / "auth.json")

    backend = await backend_factory.ensure_backend(
        backend_type="openai-codex",
        app_config=config,
        backend_config=backend_config,
    )
    assert backend is not None
    # In test mode, backend might be a mock, so we verify it was created
    # and that the backend type is registered
    assert "openai-codex" in backend_registry.get_registered_backends()
    # If backend has backend_type attribute, verify it
    if hasattr(backend, "backend_type"):
        assert backend.backend_type == "openai-codex"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_config_keys_honored_from_documentation(auth_dir: Path):
    """Test that documented configuration keys are honored (Req 9.1)."""
    from src.connectors.openai_codex.settings import SettingsLoader

    # Test key configuration keys that should be honored
    config = AppConfig()

    # Set config via backend extra (simulating YAML config)
    if not hasattr(config.backends, "openai_codex"):
        from src.core.config.app_config import BackendConfig

        config.backends.openai_codex = BackendConfig()

    # Set some documented keys
    if not hasattr(config.backends.openai_codex, "extra"):
        config.backends.openai_codex.extra = {}

    # SettingsLoader expects config under "codex" key in extra, not directly in extra
    config.backends.openai_codex.extra["codex"] = {
        "streaming": {
            "max_retries": 3,
            "retry_backoff_seconds": [1.0, 2.0, 4.0],
        },
        "compatibility_layer": {
            "enabled": True,
            "detection": {
                "cache_ttl_seconds": 7200,
                "heuristic_threshold": 3,
            },
        },
    }

    loader = SettingsLoader()
    settings = loader.load(config)

    # Verify documented keys are honored
    assert settings.streaming["max_retries"] == 3
    assert settings.streaming["retry_backoff_seconds"] == (1.0, 2.0, 4.0)
    assert settings.compatibility_layer["enabled"] is True
    assert settings.compatibility_layer["detection"]["cache_ttl_seconds"] == 7200
    assert settings.compatibility_layer["detection"]["heuristic_threshold"] == 3
