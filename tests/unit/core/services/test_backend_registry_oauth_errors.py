"""Unit tests for backend registry OAuth-specific error messages.

Tests that backend_registry.get_backend_factory() provides clear, specific error
messages when OAuth connectors are requested in Multi User Mode.

Uses subprocess-based isolation to test Multi User Mode behavior.

Requirements satisfied:
- 6.5: Requests to OAuth connectors fail with clear error indicating unavailability in Multi User Mode
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from src.core.services.backend_registry import BackendRegistry

_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
_CACHE_FILE = _PROJECT_ROOT / ".pytest_cache" / "oauth_errors_subprocess_cache.json"
_WATCHED = [
    _PROJECT_ROOT / "src" / "connectors" / "__init__.py",
    _PROJECT_ROOT / "src" / "core" / "services" / "backend_registry.py",
]


def _cache_key(script: str) -> str:
    h = hashlib.md5()
    h.update(script.encode())
    for p in _WATCHED:
        if p.exists():
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{st.st_mtime}".encode())
    return h.hexdigest()


def _load_cached(key: str) -> dict[str, str] | None:
    if not _CACHE_FILE.exists():
        return None
    try:
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if data.get("key") == key:
            return data.get("errors")
    except (OSError, json.JSONDecodeError):
        pass
    return None


def _store_cached(key: str, errors: dict[str, str]) -> None:
    _CACHE_FILE.parent.mkdir(exist_ok=True)
    try:
        with open(_CACHE_FILE, "w") as f:
            json.dump({"key": key, "errors": errors}, f)
    except OSError:
        pass


def _run_multi_user_oauth_errors() -> dict[str, str]:
    """Run OAuth error checks in one subprocess with disk caching."""
    script = """
import os
os.environ["LLM_PROXY_ACCESS_MODE"] = "multi_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

for name in ["gemini-oauth-auto", "qwen-oauth", "openai-codex"]:
    try:
        backend_registry.get_backend_factory(name)
        print(f"{name}||NO_ERROR")
    except ValueError as e:
        print(f"{name}||{e!s}")
"""
    key = _cache_key(script)
    cached = _load_cached(key)
    if cached is not None:
        return cached

    env = {
        **dict(os.environ),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONOPTIMIZE": "1",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")

    out: dict[str, str] = {}
    for line in result.stdout.strip().split("\n"):
        if "||" in line:
            name, _, msg = line.partition("||")
            out[name.strip()] = msg

    _store_cached(key, out)
    return out


@pytest.fixture(scope="class")
def multi_user_oauth_errors() -> dict[str, str]:
    """Shared OAuth error messages from one subprocess run."""
    return _run_multi_user_oauth_errors()


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

    def test_specific_error_for_oauth_connector_in_multi_user_mode(
        self, multi_user_oauth_errors: dict[str, str]
    ) -> None:
        """Test specific error for OAuth connector in Multi User Mode (Requirement 6.5)."""
        error_msg = multi_user_oauth_errors.get("gemini-oauth-auto", "")
        assert "NO_ERROR" not in error_msg, "Should raise ValueError"
        assert "Multi User Mode" in error_msg, "Error should mention Multi User Mode"
        assert "OAuth" in error_msg, "Error should mention OAuth"
        assert (
            "not available" in error_msg or "blocked" in error_msg
        ), "Error should indicate unavailability"
        assert (
            "personal credentials" in error_msg or "production" in error_msg
        ), "Error should explain why OAuth is blocked"

    def test_error_message_provides_actionable_guidance(
        self, multi_user_oauth_errors: dict[str, str]
    ) -> None:
        """Test error message provides guidance on alternatives (Requirement 6.5)."""
        error_msg = multi_user_oauth_errors.get("qwen-oauth", "").lower()
        has_guidance = any(
            p in error_msg
            for p in [
                "single-user-mode",
                "single user mode",
                "static api key",
                "non-oauth",
            ]
        )
        assert (
            has_guidance
        ), f"Error should provide guidance on alternatives: {error_msg}"

    def test_error_references_specific_backend_name(
        self, multi_user_oauth_errors: dict[str, str]
    ) -> None:
        """Test error message includes the specific backend name requested."""
        error_msg = multi_user_oauth_errors.get("openai-codex", "")
        assert (
            "openai-codex" in error_msg
        ), "Error should reference the requested backend name"
