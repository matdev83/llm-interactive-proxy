"""
Regression tests for BackendFactory strategy-based initialization equivalence.

These tests verify that:
1. Factory uses strategy augmentation for known connectors (Anthropic, Gemini, OpenRouter)
2. Factory uses default strategy for unknown connectors
3. Backward compatibility is maintained for existing configurations

These are regression-focused tests that use real strategies (not mocked) to ensure
the refactoring maintains equivalence with pre-refactoring behavior.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
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
    # Ensure get_registered_backends returns expected connectors
    registry.get_registered_backends.return_value = {
        "anthropic",
        "gemini",
        "openrouter",
        "openai",
        "unknown-backend",
    }
    return registry


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
async def test_anthropic_strategy_is_used_real_registry(
    factory: BackendFactory,
) -> None:
    """Test that Anthropic strategy is actually used (not mocked).

    This regression test verifies that the factory uses the real Anthropic
    initialization strategy from the registry, ensuring strategy-based
    augmentation works correctly.
    """
    # Arrange
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-anthropic-key")

    # Act - use real registry, mock only backend creation/initialization
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify strategy augmentation was applied
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]

        # Verify Anthropic strategy augmentation: key_name should be set
        assert init_config["api_key"] == "test-anthropic-key"
        assert (
            init_config["key_name"] == "anthropic"
        ), "Anthropic strategy should set key_name='anthropic'"

        # Verify connector type used for strategy lookup
        mock_create.assert_called_once_with("anthropic", app_config)


@pytest.mark.asyncio
async def test_gemini_strategy_is_used_real_registry(
    factory: BackendFactory,
) -> None:
    """Test that Gemini strategy is actually used (not mocked).

    This regression test verifies that the factory uses the real Gemini
    initialization strategy from the registry, ensuring strategy-based
    augmentation works correctly.
    """
    # Arrange
    backend_type = "gemini"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-gemini-key")

    # Act - use real registry, mock only backend creation/initialization
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify strategy augmentation was applied
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]

        # Verify Gemini strategy augmentation
        assert init_config["api_key"] == "test-gemini-key"
        assert (
            init_config["key_name"] == "gemini"
        ), "Gemini strategy should set key_name='gemini'"
        assert (
            "gemini_api_base_url" in init_config
        ), "Gemini strategy should set gemini_api_base_url"
        assert (
            init_config["gemini_api_base_url"]
            == "https://generativelanguage.googleapis.com"
        ), "Gemini strategy should set default gemini_api_base_url when not provided"

        # Verify connector type used for strategy lookup
        mock_create.assert_called_once_with("gemini", app_config)


@pytest.mark.asyncio
async def test_openrouter_strategy_is_used_real_registry(
    factory: BackendFactory,
) -> None:
    """Test that OpenRouter strategy is actually used (not mocked).

    This regression test verifies that the factory uses the real OpenRouter
    initialization strategy from the registry, ensuring strategy-based
    augmentation works correctly.
    """
    # Arrange
    backend_type = "openrouter"
    app_config = factory._config
    backend_config = BackendConfig(api_key="test-openrouter-key")

    # Act - use real registry, mock only backend creation/initialization
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify strategy augmentation was applied
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]

        # Verify OpenRouter strategy augmentation
        assert init_config["api_key"] == "test-openrouter-key"
        assert (
            init_config["key_name"] == "openrouter"
        ), "OpenRouter strategy should set key_name='openrouter'"
        assert (
            "openrouter_headers_provider" in init_config
        ), "OpenRouter strategy should set openrouter_headers_provider"
        assert (
            init_config["api_base_url"] == "https://openrouter.ai/api/v1"
        ), "OpenRouter strategy should set default api_base_url when not provided"

        # Verify connector type used for strategy lookup
        mock_create.assert_called_once_with("openrouter", app_config)


@pytest.mark.asyncio
async def test_default_strategy_for_unknown_connector(
    factory: BackendFactory, caplog: pytest.LogCaptureFixture
) -> None:
    """Test that default strategy is used for unknown connectors.

    This regression test verifies that the factory uses the default strategy
    (pass-through) for connectors without custom strategies, ensuring
    backward compatibility for new/unknown connectors. Also verifies that
    a warning is logged when no custom strategy is found (requirement 6.7).
    """
    import logging

    # Arrange
    backend_type = "unknown-backend"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key="test-key",
        api_url="https://custom-api.example.com",
        extra={"custom_param": "custom_value"},
    )

    # Act - use real registry, mock only backend creation/initialization
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ) as mock_create,
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
        caplog.at_level(logging.WARNING),
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify default strategy behavior (no augmentation)
        mock_init.assert_called_once()
        init_config = mock_init.call_args[0][1]

        # Verify config passes through unchanged (default strategy behavior)
        assert init_config["api_key"] == "test-key"
        assert init_config["api_base_url"] == "https://custom-api.example.com"
        assert init_config["custom_param"] == "custom_value"

        # Verify no strategy-specific fields added
        assert (
            "key_name" not in init_config
        ), "Default strategy should not add key_name for unknown connectors"
        assert "gemini_api_base_url" not in init_config
        assert "openrouter_headers_provider" not in init_config

        # Verify connector type used for backend creation
        mock_create.assert_called_once_with("unknown-backend", app_config)

        # Verify warning is logged when no custom strategy is found (requirement 6.7)
        warning_messages = [
            record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ]
        assert any(
            "No custom initialization strategy registered for connector 'unknown-backend'"
            in msg
            for msg in warning_messages
        ), (
            "Registry should log a warning when no custom strategy is found "
            "for unknown connector (requirement 6.7)"
        )
        assert any(
            "Using default strategy" in msg for msg in warning_messages
        ), "Warning message should indicate default strategy is being used"


@pytest.mark.asyncio
async def test_backward_compatibility_anthropic_config_equivalence(
    factory: BackendFactory,
) -> None:
    """Test backward compatibility: Anthropic config produces same results.

    This regression test ensures that existing Anthropic configurations
    continue to work identically after the strategy-based refactoring.
    """
    # Arrange - simulate existing Anthropic configuration
    backend_type = "anthropic"
    app_config = factory._config
    backend_config = BackendConfig(
        api_key="anthropic-api-key",
        api_url="https://api.anthropic.com",
        extra={"timeout": 60},
    )

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ),
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify backward compatibility
        init_config = mock_init.call_args[0][1]

        # Verify strategy augmentation preserves existing behavior
        assert init_config["api_key"] == "anthropic-api-key"
        assert init_config["api_base_url"] == "https://api.anthropic.com"
        assert init_config["timeout"] == 60
        assert init_config["key_name"] == "anthropic", (
            "Anthropic strategy should set key_name='anthropic' "
            "(preserving pre-refactoring behavior)"
        )


@pytest.mark.asyncio
async def test_backward_compatibility_gemini_config_equivalence(
    factory: BackendFactory,
) -> None:
    """Test backward compatibility: Gemini config produces same results.

    This regression test ensures that existing Gemini configurations
    continue to work identically after the strategy-based refactoring,
    including the api_base_url to gemini_api_base_url mapping.
    """
    # Arrange - simulate existing Gemini configuration
    backend_type = "gemini"
    app_config = factory._config

    # Test case 1: Custom api_base_url should be mapped to gemini_api_base_url
    backend_config = BackendConfig(
        api_key="gemini-api-key",
        api_url="https://custom-gemini-api.example.com",
    )

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ),
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify backward compatibility
        init_config = mock_init.call_args[0][1]

        # Verify Gemini strategy preserves existing behavior
        assert init_config["api_key"] == "gemini-api-key"
        assert init_config["key_name"] == "gemini", (
            "Gemini strategy should set key_name='gemini' "
            "(preserving pre-refactoring behavior)"
        )
        # Verify api_base_url is mapped to gemini_api_base_url
        assert init_config["api_base_url"] == "https://custom-gemini-api.example.com"
        assert (
            init_config["gemini_api_base_url"]
            == "https://custom-gemini-api.example.com"
        ), (
            "Gemini strategy should map api_base_url to gemini_api_base_url "
            "(preserving pre-refactoring behavior)"
        )


@pytest.mark.asyncio
async def test_backward_compatibility_openrouter_config_equivalence(
    factory: BackendFactory,
) -> None:
    """Test backward compatibility: OpenRouter config produces same results.

    This regression test ensures that existing OpenRouter configurations
    continue to work identically after the strategy-based refactoring,
    including headers provider and default URL behavior.
    """
    # Arrange - simulate existing OpenRouter configuration
    backend_type = "openrouter"
    app_config = factory._config

    # Test case 1: Custom api_base_url should not be overridden
    backend_config = BackendConfig(
        api_key="openrouter-api-key",
        api_url="https://custom-openrouter-api.example.com",
    )

    # Act
    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ),
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config)

        # Assert - verify backward compatibility
        init_config = mock_init.call_args[0][1]

        # Verify OpenRouter strategy preserves existing behavior
        assert init_config["api_key"] == "openrouter-api-key"
        assert init_config["key_name"] == "openrouter", (
            "OpenRouter strategy should set key_name='openrouter' "
            "(preserving pre-refactoring behavior)"
        )
        assert "openrouter_headers_provider" in init_config, (
            "OpenRouter strategy should set openrouter_headers_provider "
            "(preserving pre-refactoring behavior)"
        )
        # Verify custom URL is preserved (not overridden by default)
        assert (
            init_config["api_base_url"] == "https://custom-openrouter-api.example.com"
        ), (
            "OpenRouter strategy should preserve custom api_base_url "
            "(preserving pre-refactoring behavior)"
        )

    # Test case 2: Default URL should be set when not provided
    backend_config_no_url = BackendConfig(api_key="openrouter-api-key")

    with (
        patch(
            "src.core.services.backend_factory.BackendFactory.create_backend",
            return_value=MagicMock(),
        ),
        patch(
            "src.core.services.backend_factory.BackendFactory.initialize_backend",
            new_callable=AsyncMock,
        ) as mock_init_no_url,
    ):
        await factory.ensure_backend(backend_type, app_config, backend_config_no_url)

        init_config_no_url = mock_init_no_url.call_args[0][1]
        assert init_config_no_url["api_base_url"] == "https://openrouter.ai/api/v1", (
            "OpenRouter strategy should set default api_base_url when not provided "
            "(preserving pre-refactoring behavior)"
        )


def test_backend_factory_api_surface_preservation() -> None:
    """Test that BackendFactory API surface remains unchanged (requirement 14.4).

    This regression test verifies that the public API surface of BackendFactory
    (specifically the ensure_backend method) remains unchanged for backward
    compatibility after the strategy-based refactoring.
    """
    import inspect
    from typing import get_type_hints

    from src.core.interfaces.backend_factory_interface import IBackendFactory
    from src.core.services.backend_factory import BackendFactory

    # Verify BackendFactory implements IBackendFactory interface
    # Note: IBackendFactory is a Protocol, so we check structural compatibility
    # by verifying method signatures match

    # Get ensure_backend method from both interface and implementation
    interface_method = IBackendFactory.ensure_backend
    impl_method = BackendFactory.ensure_backend

    # Verify method exists
    assert hasattr(
        BackendFactory, "ensure_backend"
    ), "BackendFactory must have ensure_backend method"
    assert callable(impl_method), "ensure_backend must be callable"

    # Check signatures match
    interface_sig = inspect.signature(interface_method)
    impl_sig = inspect.signature(impl_method)

    # Check parameters
    # Protocol methods include 'self' in signature, implementation methods also have 'self'
    # We compare all parameters including self, but skip 'self' for name/kind/default checks
    interface_params = list(interface_sig.parameters.values())
    impl_params = list(impl_sig.parameters.values())

    assert len(interface_params) == len(impl_params), (
        f"Parameter count mismatch: interface has {len(interface_params)}, "
        f"implementation has {len(impl_params)}"
    )

    # Verify parameter names and types match (skip self for detailed checks)
    for i_param, impl_param in zip(interface_params, impl_params, strict=True):
        # Skip 'self' parameter - it's always present and matches
        if i_param.name == "self":
            continue

        assert i_param.name == impl_param.name, (
            f"Parameter name mismatch: interface has '{i_param.name}', "
            f"implementation has '{impl_param.name}'"
        )
        assert i_param.kind == impl_param.kind, (
            f"Parameter kind mismatch for '{i_param.name}': "
            f"interface has {i_param.kind}, implementation has {impl_param.kind}"
        )
        # Check defaults match (both None or both have same default)
        assert i_param.default == impl_param.default, (
            f"Parameter default mismatch for '{i_param.name}': "
            f"interface has {i_param.default}, implementation has {impl_param.default}"
        )

    # Check return type hints
    interface_hints = get_type_hints(interface_method)
    impl_hints = get_type_hints(impl_method)

    if "return" in interface_hints:
        assert (
            "return" in impl_hints
        ), "Implementation missing return type hint for ensure_backend"
        # Verify return types are compatible (using string representation for comparison
        # since type objects may differ due to import paths)
        interface_return = str(interface_hints["return"])
        impl_return = str(impl_hints["return"])
        assert interface_return == impl_return or (
            "LLMBackend" in interface_return and "LLMBackend" in impl_return
        ), (
            f"Return type mismatch: interface returns {interface_return}, "
            f"implementation returns {impl_return}"
        )

    # Verify other public methods from interface also exist
    interface_methods = {
        name: method
        for name, method in inspect.getmembers(
            IBackendFactory, predicate=inspect.isfunction
        )
        if not name.startswith("_")
    }

    for method_name, _interface_method in interface_methods.items():
        assert hasattr(
            BackendFactory, method_name
        ), f"BackendFactory missing required method {method_name} from interface"
        impl_method = getattr(BackendFactory, method_name)
        assert callable(impl_method), f"{method_name} is not callable"


def test_factory_does_not_contain_hardcoded_connector_logic() -> None:
    """Test that factory doesn't contain hardcoded connector-specific logic.

    This regression test verifies that the factory delegates all backend-specific
    augmentation to strategies and doesn't contain hardcoded `if connector_type ==`
    branches for augmentation (requirement 1.5, 6.6).
    """
    import inspect

    from src.core.services.backend_factory import BackendFactory

    # Get the source code of ensure_backend method
    source = inspect.getsource(BackendFactory.ensure_backend)

    # Verify no hardcoded connector-specific augmentation logic
    # The factory should delegate to strategy registry, not contain:
    # - if connector_type == "anthropic"
    # - if connector_type == "gemini"
    # - if connector_type == "openrouter"
    # - if backend_type == "anthropic"
    # - etc.

    # Check that strategy registry is used
    assert (
        "initialization_strategy_registry" in source
    ), "Factory should use initialization_strategy_registry"
    assert "get_strategy" in source, "Factory should call get_strategy on the registry"
    assert (
        "augment_init_config" in source
    ), "Factory should call augment_init_config on the strategy"

    # Verify no hardcoded connector checks for augmentation
    # (Note: minimax env var mapping is acceptable as it's not augmentation)
    hardcoded_connector_checks = [
        'if connector_type == "anthropic"',
        'if connector_type == "gemini"',
        'if connector_type == "openrouter"',
        'if backend_type == "anthropic"',
        'if backend_type == "gemini"',
        'if backend_type == "openrouter"',
    ]

    for check in hardcoded_connector_checks:
        assert check not in source, (
            f"Factory should not contain hardcoded connector check: {check}. "
            "All backend-specific augmentation should be delegated to strategies."
        )
