"""Unit tests for backend registry OAuth-specific error messages.

Tests that backend_registry.get_backend_factory() provides clear, specific error
messages when OAuth connectors are requested in Multi User Mode.

Uses subprocess-based isolation to test Multi User Mode behavior.

Requirements satisfied:
- 6.5: Requests to OAuth connectors fail with clear error indicating unavailability in Multi User Mode
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from src.core.services.backend_registry import BackendRegistry

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent


class TestBackendRegistryOAuthErrors:
    """Tests for OAuth-specific error messages in backend registry."""

    def test_generic_error_for_unregistered_backend(self) -> None:
        """Test generic error for truly unregistered backend."""
        registry = BackendRegistry()

        with pytest.raises(ValueError) as exc_info:
            registry.get_backend_factory("nonexistent-backend")

        error_msg = str(exc_info.value)
        assert "nonexistent-backend" in error_msg
        assert "is not registered" in error_msg

    def test_specific_error_for_oauth_connector_in_multi_user_mode(self) -> None:
        """Test specific error for OAuth connector in Multi User Mode (Requirement 6.5)."""
        script = """
import os
os.environ["LLM_PROXY_ACCESS_MODE"] = "multi_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

try:
    backend_registry.get_backend_factory("gemini-oauth-auto")
    print("NO_ERROR")
except ValueError as e:
    error_msg = str(e)
    print(f"ERROR:{error_msg}")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"

        output = result.stdout.strip()
        assert "NO_ERROR" not in output, "Should raise ValueError"

        # Extract error message
        error_line = next(
            line for line in output.split("\n") if line.startswith("ERROR:")
        )
        error_msg = error_line.replace("ERROR:", "")

        # Verify error message is specific to Multi User Mode OAuth blocking
        assert "Multi User Mode" in error_msg, "Error should mention Multi User Mode"
        assert "OAuth" in error_msg, "Error should mention OAuth"
        assert (
            "not available" in error_msg or "blocked" in error_msg
        ), "Error should indicate unavailability"
        assert (
            "personal credentials" in error_msg or "production" in error_msg
        ), "Error should explain why OAuth is blocked"

    def test_error_message_provides_actionable_guidance(self) -> None:
        """Test error message provides guidance on alternatives (Requirement 6.5)."""
        script = """
import os
os.environ["LLM_PROXY_ACCESS_MODE"] = "multi_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

try:
    backend_registry.get_backend_factory("anthropic-oauth")
except ValueError as e:
    error_msg = str(e)
    print(f"ERROR:{error_msg}")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"

        error_line = next(
            line
            for line in result.stdout.strip().split("\n")
            if line.startswith("ERROR:")
        )
        error_msg = error_line.replace("ERROR:", "")

        # Should provide guidance on alternatives
        has_guidance = any(
            phrase in error_msg.lower()
            for phrase in [
                "single-user-mode",
                "single user mode",
                "static api key",
                "non-oauth",
            ]
        )
        assert (
            has_guidance
        ), f"Error should provide guidance on alternatives: {error_msg}"

    def test_error_references_specific_backend_name(self) -> None:
        """Test error message includes the specific backend name requested."""
        script = """
import os
os.environ["LLM_PROXY_ACCESS_MODE"] = "multi_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

try:
    backend_registry.get_backend_factory("qwen-oauth")
except ValueError as e:
    print(f"ERROR:{str(e)}")
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"Script failed: {result.stderr}"

        error_line = next(
            line
            for line in result.stdout.strip().split("\n")
            if line.startswith("ERROR:")
        )
        error_msg = error_line.replace("ERROR:", "")

        assert (
            "qwen-oauth" in error_msg
        ), "Error should reference the requested backend name"
