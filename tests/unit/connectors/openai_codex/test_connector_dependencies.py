"""Unit tests for Codex connector dependency validation.

Tests cover validation of dependency overrides and fail-fast behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from src.connectors.openai_codex.contracts import CodexConnectorDependencies
from src.connectors.openai_codex.interfaces import (
    ICredentialManager,
    IResponseExecutor,
)
from src.core.common.exceptions import ServiceResolutionError
from src.core.config.app_config import AppConfig


class TestConnectorDependencyValidation:
    """Test dependency override validation."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def mock_config(self):
        """Create a mock AppConfig."""
        config = MagicMock(spec=AppConfig)
        config.backends = MagicMock()
        return config

    def test_valid_overrides_accepted(self, mock_client, mock_config):
        """Test that valid overrides are accepted."""
        from src.connectors.openai_codex import OpenAICodexConnector

        valid_settings_loader = MagicMock(spec=["load"])
        valid_settings_loader.load = MagicMock(return_value=MagicMock())

        valid_credential_manager = MagicMock(spec=ICredentialManager)
        valid_credential_manager.initialize = MagicMock()
        valid_credential_manager.refresh_access_token = MagicMock()
        valid_credential_manager.get_access_token = MagicMock()
        valid_credential_manager.shutdown = MagicMock()

        dependencies = CodexConnectorDependencies(
            settings_loader=valid_settings_loader,
            credential_manager=valid_credential_manager,
        )

        # Should not raise
        connector = OpenAICodexConnector(
            client=mock_client,
            config=mock_config,
            dependencies=dependencies,
        )
        assert connector is not None

    def test_invalid_settings_loader_raises_error(self, mock_client, mock_config):
        """Test that invalid settings_loader override raises ServiceResolutionError."""
        from src.connectors.openai_codex import OpenAICodexConnector

        # Create a class without 'load' method
        class InvalidLoader:
            pass

        invalid_loader = InvalidLoader()

        dependencies = CodexConnectorDependencies(settings_loader=invalid_loader)

        with pytest.raises(ServiceResolutionError) as exc_info:
            OpenAICodexConnector(
                client=mock_client,
                config=mock_config,
                dependencies=dependencies,
            )

        assert "settings_loader" in str(exc_info.value)
        assert "ISettingsLoader" in str(exc_info.value)

    def test_invalid_credential_manager_raises_error(self, mock_client, mock_config):
        """Test that invalid credential_manager override raises ServiceResolutionError."""
        from src.connectors.openai_codex import OpenAICodexConnector

        # Create a class without required methods
        class InvalidManager:
            pass

        invalid_manager = InvalidManager()

        dependencies = CodexConnectorDependencies(credential_manager=invalid_manager)

        with pytest.raises(ServiceResolutionError) as exc_info:
            OpenAICodexConnector(
                client=mock_client,
                config=mock_config,
                dependencies=dependencies,
            )

        assert "credential_manager" in str(exc_info.value)
        assert "ICredentialManager" in str(exc_info.value)

    def test_invalid_response_executor_raises_error(self, mock_client, mock_config):
        """Test that invalid response_executor override raises ServiceResolutionError."""
        from src.connectors.openai_codex import OpenAICodexConnector

        # Create a class without 'execute' method
        class InvalidExecutor:
            pass

        invalid_executor = InvalidExecutor()

        dependencies = CodexConnectorDependencies(response_executor=invalid_executor)

        with pytest.raises(ServiceResolutionError) as exc_info:
            OpenAICodexConnector(
                client=mock_client,
                config=mock_config,
                dependencies=dependencies,
            )

        assert "response_executor" in str(exc_info.value)
        assert "IResponseExecutor" in str(exc_info.value)

    def test_partial_overrides_work(self, mock_client, mock_config):
        """Test that partial overrides (some None, some provided) work correctly."""
        from src.connectors.openai_codex import OpenAICodexConnector

        valid_executor = MagicMock(spec=IResponseExecutor)
        valid_executor.execute = MagicMock()

        dependencies = CodexConnectorDependencies(
            response_executor=valid_executor,
            settings_loader=None,  # None is allowed
            credential_manager=None,  # None is allowed
        )

        # Should not raise
        connector = OpenAICodexConnector(
            client=mock_client,
            config=mock_config,
            dependencies=dependencies,
        )
        assert connector is not None

    def test_validation_happens_before_use(self, mock_client, mock_config):
        """Test that validation happens early in __init__ before connector is used."""
        from src.connectors.openai_codex import OpenAICodexConnector

        # Create a class without 'execute' method
        class InvalidExecutor:
            pass

        invalid_executor = InvalidExecutor()

        dependencies = CodexConnectorDependencies(response_executor=invalid_executor)

        # Should raise during __init__, not later
        with pytest.raises(ServiceResolutionError):
            OpenAICodexConnector(
                client=mock_client,
                config=mock_config,
                dependencies=dependencies,
            )
