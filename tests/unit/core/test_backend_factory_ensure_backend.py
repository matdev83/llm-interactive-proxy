"""
Tests for BackendFactory.ensure_backend method.

These tests verify the behavior of the BackendFactory.ensure_backend method
with different types of backend configurations.
"""

# Tests for BackendFactory.ensure_backend method - now fixed with selective global mocking
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from src.core.common.exceptions import RoutingError
from src.core.config.app_config import BackendConfig
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_registry import BackendRegistry


@pytest.fixture
def mock_client() -> httpx.AsyncClient:
    """Create a mock HTTP client."""
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_backend_registry() -> BackendRegistry:
    """Create a mock backend registry."""
    registry = MagicMock(spec=BackendRegistry)
    mock_backend = MagicMock()
    mock_backend_factory = MagicMock(return_value=mock_backend)
    registry.get_backend_factory.return_value = mock_backend_factory
    return registry


# No custom test class needed anymore


def test_create_backend_maps_missing_extracted_backend_to_routing_error() -> None:
    """Missing extracted backends should surface deterministic routing errors."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_registry = MagicMock(spec=BackendRegistry)
    mock_registry.get_backend_factory.side_effect = ValueError(
        "Backend 'gemini-oauth-plan' is not registered."
    )
    factory = BackendFactory(
        mock_client, mock_registry, AppConfig(), TranslationService()
    )

    with pytest.raises(RoutingError) as exc_info:
        factory.create_backend("gemini-oauth-plan")

    exc = exc_info.value
    assert exc.details.get("code") == "unknown_model"
    assert exc.details.get("backend_type") == "gemini-oauth-plan"
    assert (
        exc.details.get("optional_package") == "llm-interactive-proxy-oauth-connectors"
    )
    assert (
        exc.details.get("install_command") == "pip install llm-interactive-proxy[oauth]"
    )


def test_create_backend_preserves_non_extracted_registry_error() -> None:
    """Unknown non-extracted backends should keep existing ValueError behavior."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_registry = MagicMock(spec=BackendRegistry)
    mock_registry.get_backend_factory.side_effect = ValueError(
        "Backend 'unknown-backend' is not registered."
    )
    factory = BackendFactory(
        mock_client, mock_registry, AppConfig(), TranslationService()
    )

    with pytest.raises(ValueError, match="unknown-backend"):
        factory.create_backend("unknown-backend")


def test_create_backend_surfaces_multi_user_oauth_guidance() -> None:
    """Multi User blocked OAuth backends should preserve mode-specific guidance."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_registry = MagicMock(spec=BackendRegistry)
    mock_registry.get_backend_factory.side_effect = ValueError(
        "Backend 'gemini-oauth-plan' is not available in Multi User Mode."
    )
    factory = BackendFactory(
        mock_client, mock_registry, AppConfig(), TranslationService()
    )

    with (
        patch(
            "src.core.services.backend_factory.is_running_in_multi_user_mode",
            return_value=True,
        ),
        patch(
            "src.core.services.backend_factory.get_skipped_oauth_connectors",
            return_value=["gemini_oauth_plan"],
        ),
        pytest.raises(RoutingError) as exc_info,
    ):
        factory.create_backend("gemini-oauth-plan")

    exc = exc_info.value
    assert "Multi User Mode" in exc.message
    assert exc.details.get("code") == "unknown_model"
    assert exc.details.get("multi_user_blocked") is True
    assert exc.details.get("access_mode") == "multi_user"
    assert exc.details.get("install_command") is None


def test_create_backend_blocks_registered_extracted_backend_in_multi_user_mode() -> (
    None
):
    """Extracted OAuth backends must be blocked before registry lookup in Multi User Mode."""
    from src.core.config.app_config import AppConfig
    from src.core.config.models.access_mode import AccessMode, AccessModeConfig
    from src.core.services.translation_service import TranslationService

    mock_client = MagicMock(spec=httpx.AsyncClient)
    mock_registry = MagicMock(spec=BackendRegistry)
    mock_registry.get_backend_factory.return_value = MagicMock()
    config = AppConfig(access_mode=AccessModeConfig(mode=AccessMode.MULTI_USER))
    factory = BackendFactory(mock_client, mock_registry, config, TranslationService())

    with pytest.raises(RoutingError) as exc_info:
        factory.create_backend("gemini-oauth-plan.primary")

    mock_registry.get_backend_factory.assert_not_called()
    exc = exc_info.value
    assert "Multi User Mode" in exc.message
    assert exc.details.get("code") == "unknown_model"
    assert exc.details.get("backend_type") == "gemini-oauth-plan"
    assert exc.details.get("multi_user_blocked") is True
    assert exc.details.get("access_mode") == "multi_user"


@pytest.fixture
def factory(
    mock_client: httpx.AsyncClient, mock_backend_registry: BackendRegistry
) -> BackendFactory:
    """Create a BackendFactory instance with mock dependencies."""
    from src.core.config.app_config import AppConfig
    from src.core.services.translation_service import TranslationService

    config = AppConfig()
    return BackendFactory(
        mock_client, mock_backend_registry, config, TranslationService()
    )


@pytest.mark.asyncio
async def test_ensure_backend_with_none_config(factory: BackendFactory) -> None:
    """Test ensure_backend with None config."""
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    mock_backend = MagicMock()

    # We need to patch the actual method, not the instance method
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, None)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_with_backend_config(factory: BackendFactory) -> None:
    """Test ensure_backend with a BackendConfig object."""
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key="test-api-key",
        api_url="https://custom-api.example.com",
        extra={"timeout": 30},
    )
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "test-api-key"
        assert init_config["api_base_url"] == "https://custom-api.example.com"
        assert init_config["timeout"] == 30
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_test_env_injection(factory: BackendFactory) -> None:
    """Test ensure_backend in test environment with no API key.

    Note: Production code no longer auto-injects test keys for security reasons.
    Tests must explicitly provide API keys if needed.
    """
    # Arrange
    backend_type = "openai"
    app_config = factory._config
    backend_config = BackendConfig()  # No API key
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_something"}),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        # No automatic test key injection for security - expect None when no key provided
        assert init_config["api_key"] is None
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_zai_coding_plan_keeps_explicit_key_over_live_env(
    factory: BackendFactory,
) -> None:
    """zai-coding-plan explicit key should win over ambient ZAI_CODING_PLAN_API_KEY."""

    backend_type = "zai-coding-plan"
    app_config = factory._config
    backend_config = BackendConfig(api_key="stale-config-key")
    mock_backend = MagicMock()

    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.core.services.backend_factory.get_env_value_with_windows_persistent_fallback",
            return_value=("live-env-key", "process"),
        ),
        patch.dict(os.environ, {"ZAI_CODING_PLAN_API_KEY": "live-env-key"}, clear=False),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

    mock_create.assert_called_once_with(backend_type, app_config)
    mock_init.assert_called_once()
    init_config = mock_init.call_args[0][1]
    assert init_config["api_key"] == "stale-config-key"
    assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_zai_coding_plan_keeps_explicit_key_over_windows_persistent(
    factory: BackendFactory,
) -> None:
    """zai-coding-plan explicit key should win over Windows persistent env values."""

    backend_type = "zai-coding-plan"
    app_config = factory._config
    backend_config = BackendConfig(api_key="stale-config-key")
    mock_backend = MagicMock()

    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.core.services.backend_factory.get_env_value_with_windows_persistent_fallback",
            return_value=("windows-persistent-key", "windows-user"),
        ),
        patch.dict(os.environ, {"ZAI_CODING_PLAN_API_KEY": "stale-process-key"}, clear=False),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

    mock_create.assert_called_once_with(backend_type, app_config)
    mock_init.assert_called_once()
    init_config = mock_init.call_args[0][1]
    assert init_config["api_key"] == "stale-config-key"
    assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_zai_coding_plan_keeps_explicit_key_when_no_env_available(
    factory: BackendFactory,
) -> None:
    """Explicit config should survive when neither process nor persistent env has a key."""

    backend_type = "zai-coding-plan"
    app_config = factory._config
    backend_config = BackendConfig(api_key="explicit-config-key")
    mock_backend = MagicMock()

    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.core.services.backend_factory.get_env_value_with_windows_persistent_fallback",
            return_value=(None, "missing"),
        ),
        patch.dict(os.environ, {}, clear=False),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

    mock_create.assert_called_once_with(backend_type, app_config)
    mock_init.assert_called_once()
    init_config = mock_init.call_args[0][1]
    assert init_config["api_key"] == "explicit-config-key"
    assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_zai_coding_plan_uses_live_env_when_key_missing(
    factory: BackendFactory,
) -> None:
    """zai-coding-plan should use live env value when no explicit key is configured."""

    backend_type = "zai-coding-plan"
    app_config = factory._config
    backend_config = BackendConfig(api_key=None)
    mock_backend = MagicMock()

    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.core.services.backend_factory.get_env_value_with_windows_persistent_fallback",
            return_value=("live-env-key", "process"),
        ),
        patch.dict(os.environ, {"ZAI_CODING_PLAN_API_KEY": "live-env-key"}, clear=False),
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

    mock_create.assert_called_once_with(backend_type, app_config)
    mock_init.assert_called_once()
    init_config = mock_init.call_args[0][1]
    assert init_config["api_key"] == "live-env-key"
    assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_anthropic_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with Anthropic-specific configuration."""
    # Arrange
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(api_key="anthropic-key")
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "anthropic-key"
        assert init_config["key_name"] == "anthropic"
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_openrouter_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with OpenRouter-specific configuration."""
    # Arrange
    backend_type = "openrouter"
    app_config = factory._config
    backend_config = BackendConfig(api_key="openrouter-key")
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "openrouter-key"
        assert init_config["key_name"] == "openrouter"
        assert "openrouter_headers_provider" in init_config
        assert init_config["api_base_url"] == "https://openrouter.ai/api/v1"
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_gemini_specific(factory: BackendFactory) -> None:
    """Test ensure_backend with Gemini-specific configuration."""
    # Arrange
    backend_type = "gemini"
    app_config = factory._config
    backend_config = BackendConfig(api_key="gemini-key")
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "gemini-key"
        assert init_config["key_name"] == "gemini"
        assert (
            init_config["gemini_api_base_url"]
            == "https://generativelanguage.googleapis.com"
        )
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_custom_api_url_not_overridden(
    factory: BackendFactory,
) -> None:
    """Test ensure_backend doesn't override custom API URL with default."""
    # Arrange
    backend_type = "gemini"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key="gemini-key", api_url="https://custom-gemini-api.example.com"
    )
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with(backend_type, app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        assert init_config["api_key"] == "gemini-key"
        assert init_config["api_base_url"] == "https://custom-gemini-api.example.com"
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_delegates_to_strategy_registry(
    factory: BackendFactory,
) -> None:
    """Test that ensure_backend delegates to initialization strategy registry."""
    # Arrange
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-key")
    mock_backend = MagicMock()
    mock_strategy = MagicMock()
    mock_strategy.augment_init_config.return_value = {
        "api_key": "test-key",
        "key_name": "anthropic",
    }

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        patch(
            "src.core.services.backend_factory.initialization_strategy_registry.get_strategy",
            return_value=mock_strategy,
        ) as mock_get_strategy,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_get_strategy.assert_called_once_with("anthropic")
        mock_strategy.augment_init_config.assert_called_once()
        mock_create.assert_called_once_with("anthropic", app_config)
        mock_init.assert_called_once()
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_uses_default_strategy_for_unknown_connector(
    factory: BackendFactory,
) -> None:
    """Test that ensure_backend uses default strategy for unknown connectors."""
    # Arrange
    backend_type = "unknown-backend"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-key")
    mock_backend = MagicMock()

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=mock_backend,
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        result = await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert
        mock_create.assert_called_once_with("unknown-backend", app_config)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]
        # Default strategy should pass config unmodified (no key_name added)
        assert init_config["api_key"] == "test-key"
        assert "key_name" not in init_config
        assert result == mock_backend


@pytest.mark.asyncio
async def test_ensure_backend_preserves_exception_context_from_strategy(
    factory: BackendFactory,
) -> None:
    """Test that exceptions from strategies propagate correctly.

    Note: Exception wrapping with connector context is handled by the registry's
    _ExceptionWrappingStrategy wrapper, which is tested separately in registry tests.
    This test verifies that exceptions from strategies propagate through the factory.
    """
    # Arrange
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-key")
    mock_strategy = MagicMock()
    mock_strategy.augment_init_config.side_effect = ValueError("Strategy error")

    # Act & Assert
    # When get_strategy returns a mock directly, it bypasses the registry's wrapper,
    # so we just verify the exception propagates. The registry's exception wrapping
    # is tested in tests/unit/connectors/strategies/test_registry.py
    with (
        patch(
            "src.core.services.backend_factory.initialization_strategy_registry.get_strategy",
            return_value=mock_strategy,
        ),
        pytest.raises(ValueError, match="Strategy error"),
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)


class TestBackendFactoryLogRedaction:
    """Tests for API key redaction in logs (Fix 5)."""

    @pytest.mark.asyncio
    async def test_logs_do_not_contain_raw_api_key(
        self, factory: BackendFactory, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that INFO logs do not contain raw API key strings."""
        import logging

        from src.core.config.app_config import AppConfig

        backend_type = "test-backend"
        app_config = AppConfig()
        backend_config = BackendConfig(
            api_key="secret-api-key-12345",
            api_url="https://api.example.com",
        )

        # Mock the backend creation and initialization
        mock_backend = MagicMock()
        mock_backend.initialize = AsyncMock()
        mock_backend.instance_name = "test-backend"

        with (
            patch.object(factory, "create_backend", return_value=mock_backend),
            patch.object(factory, "initialize_backend", new_callable=AsyncMock),
            caplog.at_level(logging.INFO),
        ):
            await factory.ensure_backend(
                backend_type=backend_type,
                app_config=app_config,
                backend_config=backend_config,
            )

        # Verify that no log line contains the raw API key
        log_text = caplog.text
        assert (
            "secret-api-key-12345" not in log_text
        ), "Logs should not contain raw API key"

        # Verify that logs still contain useful information
        assert (
            "test-backend" in log_text or "Factory initializing" in log_text
        ), "Logs should contain backend name"

        # Verify that redacted value appears in logs
        assert "[REDACTED]" in log_text, "Logs should contain redacted indicator"

    @pytest.mark.asyncio
    async def test_logs_redact_api_keys_collections(
        self, factory: BackendFactory, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from src.core.config.app_config import AppConfig

        backend_type = "internlm"
        app_config = AppConfig()
        backend_config = BackendConfig(
            api_key="primary-secret-key",
            api_url="https://api.example.com",
            extra={"api_keys": ["secret-key-1", "secret-key-2"]},
        )

        mock_backend = MagicMock()
        mock_backend.initialize = AsyncMock()
        mock_backend.instance_name = "internlm"

        with (
            patch.object(factory, "create_backend", return_value=mock_backend),
            patch.object(factory, "initialize_backend", new_callable=AsyncMock),
            caplog.at_level(logging.INFO),
        ):
            await factory.ensure_backend(
                backend_type=backend_type,
                app_config=app_config,
                backend_config=backend_config,
            )

        log_text = caplog.text
        assert "primary-secret-key" not in log_text
        assert "secret-key-1" not in log_text
        assert "secret-key-2" not in log_text
        assert "[REDACTED]" in log_text
