"""
Tests for ProjectDirCommandHandler.

This module tests the project directory command handler functionality.
"""

import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from src.core.commands.handlers.base_handler import CommandHandlerResult
from src.core.commands.handlers.project_dir_handler import ProjectDirCommandHandler
from src.core.interfaces.domain_entities_interface import ISessionState


class TestProjectDirCommandHandler:
    """Tests for ProjectDirCommandHandler class."""

    @pytest.fixture
    def handler(self) -> ProjectDirCommandHandler:
        """Create a ProjectDirCommandHandler instance."""
        return ProjectDirCommandHandler()

    @pytest.fixture
    def mock_state(self) -> ISessionState:
        """Create a mock session state."""
        state = Mock(spec=ISessionState)
        state.with_project_dir = Mock(return_value=state)
        return state

    def test_handler_properties(self, handler: ProjectDirCommandHandler) -> None:
        """Test handler properties."""
        assert handler.name == "project-dir"
        assert handler.aliases == ["project_dir", "projectdir"]
        assert handler.description == "Set the current project directory"
        assert handler.examples == [
            "!/project-dir(/path/to/project)",
            "!/project-dir(C:\\Users\\username\\projects\\myproject)",
        ]

    def test_can_handle_project_dir_variations(
        self, handler: ProjectDirCommandHandler
    ) -> None:
        """Test can_handle with various project directory parameter names."""
        # Exact matches
        assert handler.can_handle("project-dir") is True
        assert handler.can_handle("project_dir") is True
        assert handler.can_handle("project dir") is True

        # Alias matches
        assert handler.can_handle("project_dir") is True
        assert handler.can_handle("projectdir") is True

        # Case insensitive
        assert handler.can_handle("PROJECT-DIR") is True
        assert handler.can_handle("Project-Dir") is True

        # No matches
        assert handler.can_handle("project") is False
        assert handler.can_handle("directory") is False
        assert handler.can_handle("other") is False

    @pytest.mark.asyncio
    async def test_handle_with_valid_directory(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with a valid directory path."""
        test_dir = tmp_path / "test_project"
        test_dir.mkdir()

        result = handler.handle(str(test_dir), mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Project directory set to {test_dir}"
        assert result.new_state is mock_state

        # Verify the state was updated correctly
        mock_state.with_project_dir.assert_called_once_with(str(test_dir))

    @pytest.mark.asyncio
    async def test_handle_with_nonexistent_directory(
        self, handler: ProjectDirCommandHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with a nonexistent directory path."""
        nonexistent_dir = "/path/that/does/not/exist"

        result = handler.handle(nonexistent_dir, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == f"Directory '{nonexistent_dir}' not found."
        assert result.new_state is None

        # Verify the state was not updated
        mock_state.with_project_dir.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_with_file_path(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with a file path instead of directory."""
        test_file = tmp_path / "test_file.txt"
        test_file.write_text("test content")

        result = handler.handle(str(test_file), mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False
        assert result.message == f"Directory '{test_file}' not found."
        assert result.new_state is None

        # Verify the state was not updated
        mock_state.with_project_dir.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_with_none_value(
        self, handler: ProjectDirCommandHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with None value (unset directory)."""
        result = handler.handle(None, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == "Project directory unset"
        assert result.new_state is mock_state

        # Verify the state was updated with None
        mock_state.with_project_dir.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_handle_with_empty_string(
        self, handler: ProjectDirCommandHandler, mock_state: ISessionState
    ) -> None:
        """Test handle with empty string (unset directory)."""
        result = handler.handle("", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == "Project directory unset"
        assert result.new_state is mock_state

        # Verify the state was updated with None
        mock_state.with_project_dir.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_handle_with_relative_path(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with relative path."""
        # Create a subdirectory
        test_dir = tmp_path / "subdir"
        test_dir.mkdir()

        # Change to tmp_path and use relative path
        original_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            result = handler.handle("subdir", mock_state)

            assert isinstance(result, CommandHandlerResult)
            assert result.success is True
            # The handler uses the original relative path in the message
            assert result.message == "Project directory set to subdir"
            assert result.new_state is mock_state

            # Verify the state was updated correctly with the original relative path
            mock_state.with_project_dir.assert_called_once_with("subdir")
        finally:
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_handle_with_current_directory(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with current directory (dot)."""
        result = handler.handle(".", mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        # The handler uses the original "." in the message
        assert result.message == "Project directory set to ."
        assert result.new_state is mock_state

        # Verify the state was updated correctly with the original "." path
        mock_state.with_project_dir.assert_called_once_with(".")

    @pytest.mark.asyncio
    async def test_handle_with_parent_directory(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with parent directory."""
        # Create a nested directory structure
        nested_dir = tmp_path / "parent" / "child"
        nested_dir.mkdir(parents=True)

        result = handler.handle(str(nested_dir), mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Project directory set to {nested_dir}"
        assert result.new_state is mock_state

        # Verify the state was updated correctly
        mock_state.with_project_dir.assert_called_once_with(str(nested_dir))

    @pytest.mark.asyncio
    async def test_handle_with_none_context(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with None context."""
        test_dir = tmp_path / "test_project"
        test_dir.mkdir()

        result = handler.handle(str(test_dir), mock_state, None)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Project directory set to {test_dir}"
        assert result.new_state is mock_state

        # Verify the state was updated correctly
        mock_state.with_project_dir.assert_called_once_with(str(test_dir))

    @pytest.mark.asyncio
    async def test_handle_with_nested_directory_path(
        self,
        handler: ProjectDirCommandHandler,
        mock_state: ISessionState,
        tmp_path: Path,
    ) -> None:
        """Test handle with deeply nested directory path."""
        # Create a deeply nested directory
        nested_path = tmp_path / "level1" / "level2" / "level3" / "project"
        nested_path.mkdir(parents=True)

        result = handler.handle(str(nested_path), mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is True
        assert result.message == f"Project directory set to {nested_path}"
        assert result.new_state is mock_state

        # Verify the state was updated correctly
        mock_state.with_project_dir.assert_called_once_with(str(nested_path))

    @pytest.mark.asyncio
    async def test_handle_preserves_state_on_failure(
        self, handler: ProjectDirCommandHandler, mock_state: ISessionState
    ) -> None:
        """Test that state is not modified when directory validation fails."""
        nonexistent_dir = "/definitely/does/not/exist"

        # Record initial call count
        initial_call_count = mock_state.with_project_dir.call_count

        result = handler.handle(nonexistent_dir, mock_state)

        assert isinstance(result, CommandHandlerResult)
        assert result.success is False

        # Verify the state update method was never called
        assert mock_state.with_project_dir.call_count == initial_call_count
