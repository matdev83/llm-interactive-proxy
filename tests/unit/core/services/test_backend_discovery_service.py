"""Unit tests for unified backend discovery and OAuth package status logging."""

from __future__ import annotations

from importlib import metadata
from unittest.mock import patch

import pytest
from src.core.services.backend_discovery import discover_backends
from src.core.services.backend_registry import backend_registry


class TestOAuthPackageStatusLogging:
    """Tests for OAuth connectors package presence logging at startup."""

    def test_logs_oauth_backends_when_package_installed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When OAuth package is installed and backends are registered, log them."""
        with (
            caplog.at_level("INFO"),
            patch(
                "src.core.services.backend_discovery.import_module",
            ),
            patch(
                "src.core.services.backend_discovery.discover_plugin_backends",
                return_value=["gemini-oauth-auto", "qwen-oauth"],
            ),
            patch.object(
                backend_registry, "get_registered_backends"
            ) as mock_registered,
            patch(
                "src.core.services.backend_discovery.metadata.version",
                return_value="1.0.0",
            ),
        ):
            mock_registered.return_value = [
                "openai",
                "anthropic",
                "gemini-oauth-auto",
                "qwen-oauth",
            ]
            discover_backends(force=True)

        assert "OAuth connectors package installed" in caplog.text
        assert "Supported backends:" in caplog.text
        assert "qwen-oauth" in caplog.text
        assert "gemini-oauth-auto" in caplog.text

    def test_logs_not_installed_when_no_oauth_backends(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When no OAuth backends are registered and package absent, log install hint."""
        with (
            caplog.at_level("INFO"),
            patch(
                "src.core.services.backend_discovery.import_module",
            ),
            patch(
                "src.core.services.backend_discovery.discover_plugin_backends",
                return_value=[],
            ),
            patch.object(
                backend_registry, "get_registered_backends"
            ) as mock_registered,
            patch(
                "src.core.services.backend_discovery.metadata.version",
                side_effect=metadata.PackageNotFoundError(
                    "llm-interactive-proxy-oauth-connectors"
                ),
            ),
        ):
            mock_registered.return_value = ["openai", "anthropic"]
            discover_backends(force=True)

        assert "OAuth connectors package not installed" in caplog.text
        assert "pip install" in caplog.text

    def test_logs_blocked_when_package_installed_but_no_backends(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When package is installed but no OAuth backends (Multi User Mode), log accordingly."""
        with (
            caplog.at_level("INFO"),
            patch(
                "src.core.services.backend_discovery.import_module",
            ),
            patch(
                "src.core.services.backend_discovery.discover_plugin_backends",
                return_value=[],
            ),
            patch.object(
                backend_registry, "get_registered_backends"
            ) as mock_registered,
            patch(
                "src.core.services.backend_discovery.metadata.version",
                return_value="1.0.0",
            ),
        ):
            mock_registered.return_value = ["openai", "anthropic"]
            discover_backends(force=True)

        assert "OAuth connectors package installed" in caplog.text
        assert "No backends available" in caplog.text
        assert "Multi User Mode" in caplog.text

    def test_oauth_list_enumerated_from_registry_not_hardcoded(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OAuth backends are enumerated from live registry; any *-oauth backend appears."""
        with (
            caplog.at_level("INFO"),
            patch(
                "src.core.services.backend_discovery.import_module",
            ),
            patch(
                "src.core.services.backend_discovery.discover_plugin_backends",
                return_value=["custom-oauth-foo"],
            ),
            patch.object(
                backend_registry, "get_registered_backends"
            ) as mock_registered,
            patch(
                "src.core.services.backend_discovery.metadata.version",
                return_value="1.0.0",
            ),
        ):
            mock_registered.return_value = ["openai", "custom-oauth-foo", "xyz-oauth"]
            discover_backends(force=True)

        assert "custom-oauth-foo" in caplog.text
        assert "xyz-oauth" in caplog.text
