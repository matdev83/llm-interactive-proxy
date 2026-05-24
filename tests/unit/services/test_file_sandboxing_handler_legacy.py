"""Unit tests for FileSandboxingHandler."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.session import Session, SessionState
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.file_sandboxing_handler import (
    FileSandboxingHandler,
)
from src.core.services.path_validation_service import PathValidationService


class TestFileSandboxingHandler:
    """Unit tests for file sandboxing handler."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def config(self):
        """Create a default sandboxing configuration."""
        return SandboxingConfiguration(enabled=True)

    @pytest.fixture
    def path_validator(self):
        """Create a PathValidationService instance."""
        return PathValidationService()

    @pytest.fixture
    def mock_session_service(self, temp_dir):
        """Create a mock session service."""
        service = AsyncMock()
        state = SessionState(project_dir=str(temp_dir))
        session = Session(session_id="test-session", state=state)
        service.get_session.return_value = session
        return service

    @pytest.fixture
    def handler(self, config, path_validator, mock_session_service):
        """Create a FileSandboxingHandler instance."""
        return FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=mock_session_service,
        )

    def create_context(
        self,
        tool_name: str,
        tool_arguments: dict,
        session_id: str = "test-session",
    ) -> ToolCallContext:
        """Helper to create a ToolCallContext."""
        return ToolCallContext(
            session_id=session_id,
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name=tool_name,
            tool_arguments=tool_arguments,
        )

    # Test handler properties

    def test_handler_name(self, handler):
        """Test handler name property."""
        assert handler.name == "file_sandboxing_handler"

    def test_handler_priority(self, handler):
        """Test handler priority property."""
        assert handler.priority == 80

    # Test can_handle

    @pytest.mark.asyncio
    async def test_can_handle_file_changing_tool(self, handler):
        """Test can_handle returns True for file-changing tools."""
        context = self.create_context("write_to_file", {})
        assert await handler.can_handle(context) is True

    @pytest.mark.asyncio
    async def test_can_handle_non_file_tool(self, handler):
        """Test can_handle returns False for non-file tools."""
        context = self.create_context("get_weather", {})
        assert await handler.can_handle(context) is False

    @pytest.mark.asyncio
    async def test_can_handle_disabled_sandboxing(
        self, path_validator, mock_session_service
    ):
        """Test can_handle returns False when sandboxing is disabled."""
        config = SandboxingConfiguration(enabled=False)
        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=mock_session_service,
        )

        context = self.create_context("write_to_file", {})
        assert await handler.can_handle(context) is False

    # Test tool pattern matching

    def test_is_file_changing_tool_write_to_file(self, handler):
        """Test recognition of write_to_file tool."""
        assert handler._is_file_changing_tool("write_to_file") is True

    def test_is_file_changing_tool_edit_file(self, handler):
        """Test recognition of edit_file tool."""
        assert handler._is_file_changing_tool("edit_file") is True

    def test_is_file_changing_tool_str_replace(self, handler):
        """Test recognition of str_replace tool."""
        assert handler._is_file_changing_tool("str_replace") is True

    def test_is_file_changing_tool_case_insensitive(self, handler):
        """Test case-insensitive tool matching."""
        assert handler._is_file_changing_tool("WRITE_TO_FILE") is True
        assert handler._is_file_changing_tool("Write_To_File") is True

    def test_is_file_changing_tool_non_file_tool(self, handler):
        """Test non-file tools return False."""
        assert handler._is_file_changing_tool("get_weather") is False
        assert handler._is_file_changing_tool("search_web") is False

    def test_is_file_changing_tool_excluded_pattern(
        self, path_validator, mock_session_service
    ):
        """Test excluded tools are not considered file-changing."""
        config = SandboxingConfiguration(
            enabled=True,
            excluded_tools=[r"read_.*"],
        )
        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=mock_session_service,
        )

        assert handler._is_file_changing_tool("read_file") is False
        assert handler._is_file_changing_tool("write_file") is True

    # Test handle method - blocking scenarios

    @pytest.mark.asyncio
    async def test_handle_blocks_path_outside_project(self, handler, temp_dir):
        """Test handler blocks paths outside project root."""
        outside_path = str(temp_dir.parent / "outside.txt")
        context = self.create_context(
            "write_to_file",
            {"path": outside_path, "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert "paths outside project root" in result.replacement_response.lower()
        assert result.metadata["decision"] == "blocked"

    @pytest.mark.asyncio
    async def test_handle_blocks_path_traversal(self, handler, temp_dir):
        """Test handler blocks path traversal attempts."""
        context = self.create_context(
            "write_to_file",
            {"path": "../../etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.metadata["decision"] == "blocked"

    @pytest.mark.asyncio
    async def test_handle_blocks_multiple_violating_paths(self, handler, temp_dir):
        """Test handler blocks when multiple paths violate boundary."""
        outside_path1 = str(temp_dir.parent / "outside1.txt")
        outside_path2 = str(temp_dir.parent / "outside2.txt")

        context = self.create_context(
            "copy_files",
            {"paths": [outside_path1, outside_path2]},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.metadata["decision"] == "blocked"

    # Test handle method - allowing scenarios

    @pytest.mark.asyncio
    async def test_handle_allows_path_inside_project(self, handler, temp_dir):
        """Test handler allows paths inside project root."""
        inside_path = str(temp_dir / "file.txt")
        context = self.create_context(
            "write_to_file",
            {"path": inside_path, "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    @pytest.mark.asyncio
    async def test_handle_allows_relative_path_inside_project(self, handler, temp_dir):
        """Test handler allows relative paths that resolve inside project."""
        context = self.create_context(
            "write_to_file",
            {"path": "./subdir/file.txt", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    @pytest.mark.asyncio
    async def test_handle_allows_nested_paths(self, handler, temp_dir):
        """Test handler allows deeply nested paths inside project."""
        nested_path = str(temp_dir / "a" / "b" / "c" / "file.txt")
        context = self.create_context(
            "write_to_file",
            {"path": nested_path, "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    # Test handle method - no project directory

    @pytest.mark.asyncio
    async def test_handle_skips_when_no_project_dir(self, config, path_validator):
        """Test handler skips validation when no project directory is set."""
        # Create session service with no project directory
        service = AsyncMock()
        state = SessionState(project_dir=None)
        session = Session(session_id="test-session", state=state)
        service.get_session.return_value = session

        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=service,
        )

        context = self.create_context(
            "write_to_file",
            {"path": "/tmp/file.txt", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "skipped_no_project_dir"

    # Test strict mode

    @pytest.mark.asyncio
    async def test_strict_mode_blocks_unparseable_paths(
        self, path_validator, mock_session_service
    ):
        """Test strict mode blocks unparseable paths."""
        config = SandboxingConfiguration(enabled=True, strict_mode=True)
        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=mock_session_service,
        )

        context = self.create_context(
            "write_to_file",
            {"path": "\x00invalid\x00", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.metadata["decision"] == "blocked"

    # Test allow_parent_access

    @pytest.mark.asyncio
    async def test_allow_parent_access_enabled(self, path_validator, temp_dir):
        """Test allow_parent_access configuration."""
        # Create subdirectory as project root
        sub_dir = temp_dir / "subproject"
        sub_dir.mkdir()

        # Create session service with subdirectory as project root
        service = AsyncMock()
        state = SessionState(project_dir=str(sub_dir))
        session = Session(session_id="test-session", state=state)
        service.get_session.return_value = session

        config = SandboxingConfiguration(enabled=True, allow_parent_access=True)
        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=service,
        )

        # Try to access parent directory
        context = self.create_context(
            "write_to_file",
            {"path": str(temp_dir), "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"

    # Test metrics

    def test_get_metrics_initial_state(self, handler):
        """Test metrics are initialized to zero."""
        metrics = handler.get_metrics()
        assert metrics.blocked_count == 0
        assert metrics.allowed_count == 0
        assert metrics.validation_errors == 0

    @pytest.mark.asyncio
    async def test_get_metrics_after_blocking(self, handler, temp_dir):
        """Test metrics are updated after blocking."""
        outside_path = str(temp_dir.parent / "outside.txt")
        context = self.create_context(
            "write_to_file",
            {"path": outside_path, "content": "test"},
        )

        await handler.handle(context)

        metrics = handler.get_metrics()
        assert metrics.blocked_count == 1
        assert metrics.allowed_count == 0

    @pytest.mark.asyncio
    async def test_get_metrics_after_allowing(self, handler, temp_dir):
        """Test metrics are updated after allowing."""
        inside_path = str(temp_dir / "file.txt")
        context = self.create_context(
            "write_to_file",
            {"path": inside_path, "content": "test"},
        )

        await handler.handle(context)

        metrics = handler.get_metrics()
        assert metrics.blocked_count == 0
        assert metrics.allowed_count == 1

    # Test error handling

    @pytest.mark.asyncio
    async def test_handle_session_retrieval_error(self, config, path_validator):
        """Test handler fails open on session retrieval error."""
        service = AsyncMock()
        service.get_session.side_effect = Exception("Session error")

        handler = FileSandboxingHandler(
            config=config,
            path_validator=path_validator,
            session_service=service,
        )

        context = self.create_context(
            "write_to_file",
            {"path": "/tmp/file.txt", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "error_fail_open"

    @pytest.mark.asyncio
    async def test_handle_no_paths_found(self, handler):
        """Test handler allows when no paths are found in arguments."""
        context = self.create_context(
            "write_to_file",
            {"content": "test"},  # No path argument
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "no_paths_found"
