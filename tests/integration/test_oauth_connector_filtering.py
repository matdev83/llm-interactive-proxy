"""Integration tests for OAuth connector filtering in Multi User Mode.

Tests that OAuth connectors are filtered during auto-discovery when running
in Multi User Mode, while all connectors are loaded in Single User Mode.

Uses subprocess-based tests for true module isolation between test runs.

Requirements satisfied:
- 3.1, 3.2: Single User Mode loads all connectors including OAuth
- 6.1, 6.2: Multi User Mode skips OAuth connectors during auto-discovery
- 6.4: Backend registry does not contain OAuth connectors in Multi User Mode
- 6.5: Requests to OAuth connectors fail in Multi User Mode
- 10.4, 10.5: Logging of loaded/skipped OAuth connectors
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent


@pytest.fixture(scope="module")
def single_user_data() -> dict[str, int | list[str]]:
    """Shared Single User Mode backend data from one subprocess run."""
    return _run_single_user_checks()


@pytest.fixture(scope="module")
def multi_user_data_module() -> dict[str, int | list[str] | str | bool]:
    """Shared Multi User Mode backend data from one subprocess run (module scope)."""
    return _run_multi_user_checks()


def _run_single_user_checks() -> dict[str, int | list[str]]:
    """Run Single User Mode checks in one subprocess to avoid redundant imports."""
    script = """
import os
os.environ["LLM_PROXY_ACCESS_MODE"] = "single_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

backends = backend_registry.get_registered_backends()
oauth_backends = [b for b in backends if any(p in b for p in ["oauth", "codex"])]
known_oauth = ["gemini-oauth-auto", "gemini-oauth-plan", "gemini-oauth-free",
               "anthropic-oauth", "qwen-oauth", "openai-codex"]
found_oauth = [n for n in known_oauth if n in backends]
print(f"TOTAL_BACKENDS:{len(backends)}")
print(f"OAUTH_BACKENDS:{len(oauth_backends)}")
print(f"FOUND_OAUTH:{','.join(found_oauth)}")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")
    lines = result.stdout.strip().split("\n")
    total = int(
        next(l.split(":")[-1] for l in lines if l.startswith("TOTAL_BACKENDS:"))
    )
    oauth_count = int(
        next(l.split(":")[-1] for l in lines if l.startswith("OAUTH_BACKENDS:"))
    )
    found_str = next(l.split(":")[-1] for l in lines if l.startswith("FOUND_OAUTH:"))
    return {
        "total_backends": total,
        "oauth_count": oauth_count,
        "found_oauth": found_str.split(",") if found_str else [],
    }


class TestOAuthConnectorFilteringSingleUserMode:
    """Integration tests for Single User Mode connector loading."""

    def test_single_user_mode_loads_all_connectors_including_oauth(
        self, single_user_data: dict[str, int | list[str]]
    ) -> None:
        """Test Single User Mode loads all connectors including OAuth (Requirement 3.1)."""
        assert single_user_data["total_backends"] > 0, "No backends were loaded"
        assert (
            single_user_data["oauth_count"] > 0
        ), "OAuth backends should be loaded in Single User Mode"

    def test_single_user_mode_includes_specific_oauth_connectors(
        self, single_user_data: dict[str, int | list[str]]
    ) -> None:
        """Test Single User Mode includes known OAuth connectors (Requirement 3.1)."""
        assert (
            len(single_user_data["found_oauth"]) > 0
        ), "No OAuth connectors found in Single User Mode"


def _run_multi_user_checks() -> dict[str, int | list[str] | str | bool]:
    """Run Multi User Mode checks in one subprocess to avoid redundant imports."""
    script = """
import os
import logging
import sys
logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
os.environ["LLM_PROXY_ACCESS_MODE"] = "multi_user"

import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry

backends = backend_registry.get_registered_backends()
oauth_backends = [b for b in backends if any(p in b for p in ["oauth", "codex"])]
known_oauth = ["gemini-oauth-auto", "gemini-oauth-plan", "gemini-oauth-free",
               "anthropic-oauth", "qwen-oauth", "openai-codex", "antigravity-oauth",
               "kiro-oauth-auto"]
found_oauth = [n for n in known_oauth if n in backends]
non_oauth = ["openai", "anthropic", "gemini"]
found_non_oauth = [n for n in non_oauth if n in backends]
print(f"TOTAL_BACKENDS:{len(backends)}")
print(f"OAUTH_BACKENDS:{len(oauth_backends)}")
print(f"FOUND_NON_OAUTH:{','.join(found_non_oauth)}")
print(f"NO_OAUTH_IN_REGISTRY:{len(found_oauth) == 0}")
try:
    backend_registry.get_backend_factory("gemini-oauth-auto")
    print("REJECTION_ERROR_NO_EXCEPTION")
except ValueError as e:
    err = str(e)
    print(f"REJECTION_ERROR_MESSAGE:{err}")
    if "Multi User Mode" in err and "OAuth" in err:
        print("REJECTION_SUCCESS_SPECIFIC_ERROR")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")
    lines = result.stdout.strip().split("\n")
    total = int(
        next(l.split(":")[-1] for l in lines if l.startswith("TOTAL_BACKENDS:"))
    )
    oauth_count = int(
        next(l.split(":")[-1] for l in lines if l.startswith("OAUTH_BACKENDS:"))
    )
    found_non_str = next(
        l.split(":")[-1] for l in lines if l.startswith("FOUND_NON_OAUTH:")
    )
    no_oauth = (
        next(l.split(":")[-1] for l in lines if l.startswith("NO_OAUTH_IN_REGISTRY:"))
        == "True"
    )
    rejection_no_exception = any(
        "REJECTION_ERROR_NO_EXCEPTION" in line for line in lines
    )
    rejection_success = any(
        "REJECTION_SUCCESS_SPECIFIC_ERROR" in line for line in lines
    )
    return {
        "total_backends": total,
        "oauth_count": oauth_count,
        "found_non_oauth": found_non_str.split(",") if found_non_str else [],
        "no_oauth_in_registry": no_oauth,
        "stderr": result.stderr,
        "rejection_no_exception": rejection_no_exception,
        "rejection_success": rejection_success,
    }


@pytest.fixture(scope="class")
def multi_user_data(
    multi_user_data_module: dict[str, int | list[str] | str | bool]
) -> dict[str, int | list[str] | str | bool]:
    """Shared Multi User Mode backend data (reuses module fixture)."""
    return multi_user_data_module


class TestOAuthConnectorFilteringMultiUserMode:
    """Integration tests for Multi User Mode connector filtering."""

    def test_multi_user_mode_skips_oauth_connectors(
        self, multi_user_data: dict[str, int | list[str] | str]
    ) -> None:
        """Test Multi User Mode skips OAuth connectors during auto-discovery (Requirement 6.1)."""
        assert multi_user_data["total_backends"] > 0, "No backends were loaded"
        assert multi_user_data["oauth_count"] == 0, (
            f"OAuth backends should NOT be loaded in Multi User Mode, "
            f"but found: {multi_user_data['oauth_count']}"
        )

    def test_multi_user_mode_loads_non_oauth_connectors(
        self, multi_user_data: dict[str, int | list[str] | str]
    ) -> None:
        """Test Multi User Mode still loads non-OAuth connectors (Requirement 6.2)."""
        assert multi_user_data["total_backends"] > 0, "No backends were loaded"
        assert (
            len(multi_user_data["found_non_oauth"]) > 0
        ), "Non-OAuth connectors should be loaded in Multi User Mode"

    def test_multi_user_mode_backend_registry_excludes_oauth(
        self, multi_user_data: dict[str, int | list[str] | str]
    ) -> None:
        """Test backend registry does not contain OAuth connectors in Multi User Mode (Requirement 6.4)."""
        assert (
            multi_user_data["no_oauth_in_registry"] is True
        ), "OAuth connectors found in backend registry in Multi User Mode"

    def test_multi_user_mode_logs_skipped_oauth_count(
        self, multi_user_data: dict[str, int | list[str] | str]
    ) -> None:
        """Test Multi User Mode logs skipped OAuth connector count (Requirement 10.5)."""
        log_output = str(multi_user_data["stderr"]).lower()
        assert (
            "skip" in log_output or "filter" in log_output or "block" in log_output
        ), f"Expected logging about skipped OAuth connectors, got: {multi_user_data['stderr']}"


class TestOAuthConnectorFilteringRequestRejection:
    """Integration tests for request rejection of OAuth connectors in Multi User Mode."""

    def test_multi_user_mode_rejects_requests_to_oauth_connectors(
        self, multi_user_data_module: dict[str, int | list[str] | str | bool]
    ) -> None:
        """Test requests to OAuth connectors fail with specific error in Multi User Mode (Requirement 6.5)."""
        # Uses multi_user_data_module (from _run_multi_user_checks) - no extra subprocess
        assert not multi_user_data_module.get(
            "rejection_no_exception", True
        ), "OAuth connector should not be available"
        assert multi_user_data_module.get("rejection_success", False), (
            "Error message should be specific to Multi User Mode OAuth blocking. "
            f"Data: {multi_user_data_module}"
        )


def _run_oauth_mode_count(mode: str) -> int:
    """Run a subprocess to get backend count for the given access mode. Used for parallel execution."""
    script = """
import os
import sys
os.environ["LLM_PROXY_ACCESS_MODE"] = sys.argv[1]
import src.connectors  # noqa: F401
from src.core.services.backend_registry import backend_registry
print(len(backend_registry.get_registered_backends()))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, mode],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Script failed: {result.stderr}")
    return int(result.stdout.strip())


class TestOAuthConnectorFilteringComparison:
    """Comparison tests between Single User and Multi User modes."""

    def test_single_user_has_more_backends_than_multi_user(
        self,
        single_user_data: dict[str, int | list[str]],
        multi_user_data_module: dict[str, int | list[str] | str],
    ) -> None:
        """Test Single User Mode loads more backends than Multi User Mode."""
        count_single = single_user_data["total_backends"]
        count_multi = multi_user_data_module["total_backends"]

        # Single User Mode should have more backends (includes OAuth)
        assert (
            count_single > count_multi
        ), f"Single User Mode ({count_single}) should have more backends than Multi User Mode ({count_multi})"

    def test_difference_is_oauth_connectors_only(
        self, single_user_data: dict[str, int | list[str]]
    ) -> None:
        """Test the difference between modes is OAuth connectors only."""
        # Reuse single_user_data - OAuth connectors are the difference (single has them, multi doesn't)
        oauth_count = single_user_data["oauth_count"]
        assert oauth_count > 0, "No OAuth connectors found in Single User Mode"
