"""Test helper utilities for Codex connector tests.

This module provides reusable fixtures and utilities for building
CodexConnectorDependencies with mocked components, enabling tests to use
public configuration seams instead of mutating private fields.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexConnectorDependencies,
    CodexConnectorSettings,
)
from src.connectors.openai_codex.interfaces import (
    ICredentialManager,
    IResponseExecutor,
    ISettingsLoader,
)
from src.core.config.app_config import AppConfig


def create_mock_settings_loader(
    max_retries: int = 2,
    retry_backoff_seconds: tuple[float, ...] = (0.5, 1.5, 3.0),
    **overrides: Any,
) -> ISettingsLoader:
    """Create a mock settings loader with custom retry configuration.

    Args:
        max_retries: Maximum retry attempts for streaming auth failures
        retry_backoff_seconds: Backoff sequence for retries
        **overrides: Additional settings overrides

    Returns:
        Mock settings loader that implements ISettingsLoader
    """
    mock_loader = MagicMock(spec=ISettingsLoader)

    # Create default settings structure
    default_settings = {
        "default_capabilities": CodexClientCapabilities(),
        "agent_overrides": {},
        "renderer": {
            "default": "none",
            "fallback": "summary",
            "aliases": {},
            "modules": {},
        },
        "prompt": {
            "template": None,
            "prepend": [],
            "append": [],
            "deduplicate": True,
            "fallback_to_default": True,
        },
        "tool_schema": {
            "base_tools": None,
            "custom_tools": [],
        },
        "streaming": {
            "max_retries": max_retries,
            "retry_backoff_seconds": retry_backoff_seconds,
        },
        "compatibility_layer": {
            "enabled": False,
            "detection": {
                "cache_ttl_seconds": 3600,
                "heuristic_threshold": 2,
            },
            "translation": {
                "max_tool_execution_timeout": 30,
                "result_format": "kilo_standard",
            },
            "telemetry": {
                "log_translations": True,
                "log_detection": True,
                "emit_metrics": True,
            },
        },
    }

    # Apply overrides
    default_settings.update(overrides)

    # Create CodexConnectorSettings instance
    settings = CodexConnectorSettings(**default_settings)

    # Configure mock to return settings (accepts app_config parameter per interface)
    def mock_load(app_config: Any) -> CodexConnectorSettings:
        return settings

    mock_loader.load = MagicMock(side_effect=mock_load)

    return mock_loader


def create_mock_credential_manager(
    refresh_success: bool = True,
    access_token: str | None = "test_token",
) -> ICredentialManager:
    """Create a mock credential manager.

    Args:
        refresh_success: Whether refresh_access_token should succeed
        access_token: Access token to return from get_access_token

    Returns:
        Mock credential manager that implements ICredentialManager
    """
    mock_manager = MagicMock(spec=ICredentialManager)
    mock_manager.initialize = AsyncMock()
    mock_manager.refresh_access_token = AsyncMock(return_value=refresh_success)
    mock_manager.get_access_token = MagicMock(return_value=access_token)
    mock_manager.shutdown = AsyncMock()
    mock_manager.is_watcher_running = MagicMock(return_value=False)
    # Add _load_auth method for connector initialization
    mock_manager._load_auth = AsyncMock(return_value=True)

    return mock_manager


def create_mock_response_executor() -> IResponseExecutor:
    """Create a mock response executor for path validation.

    Returns:
        Mock response executor that implements IResponseExecutor
    """
    mock_executor = MagicMock(spec=IResponseExecutor)
    mock_executor.execute = AsyncMock()

    return mock_executor


def create_codex_connector_with_dependencies(
    client: Any,
    config: AppConfig,
    translation_service: Any,
    *,
    settings_loader: ISettingsLoader | None = None,
    credential_manager: ICredentialManager | None = None,
    response_executor: IResponseExecutor | None = None,
    **other_dependencies: Any,
) -> Any:
    """Create a Codex connector with dependency overrides.

    Args:
        client: HTTP client for the connector
        config: Application configuration
        translation_service: Translation service instance
        settings_loader: Optional settings loader override
        credential_manager: Optional credential manager override
        response_executor: Optional response executor override
        **other_dependencies: Additional dependency overrides

    Returns:
        OpenAICodexConnector instance with specified dependencies
    """
    from src.connectors.openai_codex import OpenAICodexConnector

    dependencies = CodexConnectorDependencies(
        settings_loader=settings_loader,
        credential_manager=credential_manager,
        response_executor=response_executor,
        **other_dependencies,
    )

    return OpenAICodexConnector(
        client=client,
        config=config,
        translation_service=translation_service,
        dependencies=dependencies,
    )
