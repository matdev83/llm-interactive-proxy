"""Security tests for UniversalToolExecutor."""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.services.universal_tool_executor import UniversalToolExecutor


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace for testing."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def executor(temp_workspace: Path) -> UniversalToolExecutor:
    """Create a UniversalToolExecutor instance for testing."""
    return UniversalToolExecutor(
        working_directory=str(temp_workspace),
        default_timeout=5,
        result_format="kilo_standard",
    )


class TestPathTraversalSecurity:
    """Tests for path traversal prevention."""

    @pytest.mark.asyncio
    async def test_read_file_outside_workspace_blocked(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test that reading a file outside the workspace is blocked."""
        # Create a file outside the workspace
        outside_file = temp_workspace.parent / "secret.txt"
        outside_file.write_text("Secret content")

        # Try to read it using ..
        result = await executor.execute_tool("read_file", {"path": "../secret.txt"})

        # Should fail with access denied or similar
        assert result["exit_code"] == 1
        assert (
            "Access denied" in result["output"]
            or "outside working directory" in result["output"]
        )

    @pytest.mark.asyncio
    async def test_write_file_outside_workspace_blocked(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test that writing a file outside the workspace is blocked."""
        # Try to write using ..
        result = await executor.execute_tool(
            "__proxy_write_to_file", {"path": "../hacked.txt", "content": "hacked"}
        )

        assert result["exit_code"] == 1
        assert (
            "Access denied" in result["output"]
            or "outside working directory" in result["output"]
        )

        # Verify file was not created
        outside_file = temp_workspace.parent / "hacked.txt"
        assert not outside_file.exists()

    @pytest.mark.asyncio
    async def test_edit_file_outside_workspace_blocked(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test that editing a file outside the workspace is blocked."""
        # Create a file outside
        outside_file = temp_workspace.parent / "config.txt"
        outside_file.write_text("Original")

        result = await executor.execute_tool(
            "__proxy_edit_file", {"path": "../config.txt", "content": "Hacked"}
        )

        assert result["exit_code"] == 1
        assert (
            "Access denied" in result["output"]
            or "outside working directory" in result["output"]
        )
        assert outside_file.read_text() == "Original"

    @pytest.mark.asyncio
    async def test_list_dir_outside_workspace_blocked(
        self, executor: UniversalToolExecutor, temp_workspace: Path
    ) -> None:
        """Test that listing a directory outside the workspace is blocked."""
        result = await executor.execute_tool("list_dir", {"path": ".."})

        assert result["exit_code"] == 1
        assert (
            "Access denied" in result["output"]
            or "outside working directory" in result["output"]
        )
