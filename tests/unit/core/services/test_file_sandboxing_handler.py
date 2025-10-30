"""Tests for FileSandboxingHandler error response generation."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.configuration.sandboxing_config import SandboxingConfiguration
from src.core.domain.session import Session, SessionState
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallContext,
    ToolCallReactionResult,
)
from src.core.services.file_sandboxing_handler import FileSandboxingHandler


@pytest.fixture
def mock_path_validator():
    """Create a mock path validator."""
    validator = Mock()
    validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
    validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
    validator.is_within_boundary = Mock(return_value=False)
    return validator


@pytest.fixture
def mock_session_service():
    """Create a mock session service."""
    service = AsyncMock()
    session = Session(
        session_id="test-session",
        state=SessionState(project_dir="/home/user/project"),
    )
    service.get_session = AsyncMock(return_value=session)
    return service


@pytest.fixture
def sandboxing_config():
    """Create a sandboxing configuration."""
    return SandboxingConfiguration(
        enabled=True,
        strict_mode=False,
        allow_parent_access=False,
    )


@pytest.fixture
def handler(sandboxing_config, mock_path_validator, mock_session_service):
    """Create a file sandboxing handler."""
    return FileSandboxingHandler(
        config=sandboxing_config,
        path_validator=mock_path_validator,
        session_service=mock_session_service,
    )


@pytest.mark.asyncio
async def test_handler_implements_interface(handler):
    """Test that handler implements IToolCallHandler interface."""
    assert hasattr(handler, "name")
    assert hasattr(handler, "priority")
    assert hasattr(handler, "can_handle")
    assert hasattr(handler, "handle")
    assert handler.name == "file_sandboxing_handler"
    assert isinstance(handler.priority, int)


@pytest.mark.asyncio
async def test_can_handle_file_changing_tool(handler):
    """Test that handler can handle file-changing tools."""
    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="write_to_file",
        tool_arguments={"path": "/etc/passwd", "content": "test"},
    )

    assert await handler.can_handle(context) is True


@pytest.mark.asyncio
async def test_can_handle_non_file_changing_tool(handler):
    """Test that handler does not handle non-file-changing tools."""
    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="read_file",
        tool_arguments={"path": "/etc/passwd"},
    )

    assert await handler.can_handle(context) is False


@pytest.mark.asyncio
async def test_handle_blocks_path_outside_project(handler, mock_path_validator):
    """Test that handler blocks paths outside project root."""
    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="write_to_file",
        tool_arguments={"path": "/etc/passwd", "content": "test"},
    )

    result = await handler.handle(context)

    assert isinstance(result, ToolCallReactionResult)
    assert result.should_swallow is True
    assert result.replacement_response is not None
    assert "outside of the project root" in result.replacement_response
    # Check for project path (platform-agnostic - could be /home/user/project or \home\user\project)
    assert "project" in result.replacement_response
    assert result.metadata["decision"] == "blocked"
    assert result.metadata["handler"] == "file_sandboxing_handler"


@pytest.mark.asyncio
async def test_handle_allows_path_inside_project(handler, mock_path_validator):
    """Test that handler allows paths inside project root."""
    # Configure mock to return path inside project
    mock_path_validator.extract_paths_from_arguments.return_value = [
        "/home/user/project/file.txt"
    ]
    mock_path_validator.normalize_path.return_value = Path(
        "/home/user/project/file.txt"
    )
    mock_path_validator.is_within_boundary.return_value = True

    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="write_to_file",
        tool_arguments={"path": "/home/user/project/file.txt", "content": "test"},
    )

    result = await handler.handle(context)

    assert isinstance(result, ToolCallReactionResult)
    assert result.should_swallow is False
    assert result.metadata["decision"] == "allowed"


@pytest.mark.asyncio
async def test_handle_no_project_directory(handler, mock_session_service):
    """Test that handler skips validation when no project directory is set."""
    # Configure mock to return session without project directory
    session = Session(
        session_id="test-session",
        state=SessionState(project_dir=None),
    )
    mock_session_service.get_session = AsyncMock(return_value=session)

    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="write_to_file",
        tool_arguments={"path": "/etc/passwd", "content": "test"},
    )

    result = await handler.handle(context)

    assert isinstance(result, ToolCallReactionResult)
    assert result.should_swallow is False
    assert result.metadata["decision"] == "skipped_no_project_dir"


@pytest.mark.asyncio
async def test_error_response_includes_tool_call_id(handler):
    """Test that error response metadata includes tool information."""
    context = ToolCallContext(
        session_id="test-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response=None,
        tool_name="write_to_file",
        tool_arguments={"path": "/etc/passwd", "content": "test"},
    )

    result = await handler.handle(context)

    assert result.metadata["tool_name"] == "write_to_file"
    assert result.metadata["session_id"] == "test-session"


# ============================================================================
# Task 15.1: Test tool pattern matching
# ============================================================================


class TestToolPatternMatching:
    """Tests for tool pattern matching functionality."""

    def test_default_tool_patterns_from_inventory(self):
        """Test that all tools from TOOL_INVENTORY.md are recognized."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Tools from TOOL_INVENTORY.md that should be recognized
        tools_from_inventory = [
            # Cline
            "write_to_file",
            "replace_in_file",
            # Kilocode
            "write_to_file",
            "apply_diff",
            "edit_file",
            "insert_content",
            "search_and_replace",
            "generate_image",
            # Codebuff
            "write_file",
            "str_replace",
            # Codex
            "apply_patch",
            # Common variations
            "delete_file",
            "remove_file",
            "create_file",
            "move_file",
            "rename_file",
            "copy_file",
        ]

        for tool_name in tools_from_inventory:
            assert handler._is_file_changing_tool(
                tool_name
            ), f"Tool '{tool_name}' from TOOL_INVENTORY.md not recognized"

    def test_custom_tool_patterns(self):
        """Test that custom tool patterns are recognized."""
        config = SandboxingConfiguration(
            enabled=True,
            custom_tool_patterns=[
                r"custom_write_.*",
                r"my_file_editor",
            ],
        )
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Custom patterns should match
        assert handler._is_file_changing_tool("custom_write_file")
        assert handler._is_file_changing_tool("custom_write_data")
        assert handler._is_file_changing_tool("my_file_editor")

        # Non-matching tools should not match
        assert not handler._is_file_changing_tool("custom_read_file")
        assert not handler._is_file_changing_tool("other_tool")

    def test_excluded_tools(self):
        """Test that excluded tools are not treated as file-changing."""
        config = SandboxingConfiguration(
            enabled=True,
            excluded_tools=[
                r"read_file",
                r"list_.*",
            ],
        )
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Excluded tools should not be treated as file-changing
        assert not handler._is_file_changing_tool("read_file")
        assert not handler._is_file_changing_tool("list_files")
        assert not handler._is_file_changing_tool("list_directory")

        # File-changing tools should still be recognized
        assert handler._is_file_changing_tool("write_file")

    def test_pattern_compilation_errors(self):
        """Test that invalid regex patterns are caught during config validation."""
        # Invalid regex patterns should be caught by SandboxingConfiguration validation
        # This test verifies that the configuration validates patterns

        with pytest.raises(ValueError):  # Should raise validation error
            config = SandboxingConfiguration(
                enabled=True,
                custom_tool_patterns=[
                    r"valid_pattern",
                    r"[invalid(pattern",  # Invalid regex
                ],
            )

        # Valid patterns should work fine
        config = SandboxingConfiguration(
            enabled=True,
            custom_tool_patterns=[
                r"valid_pattern",
                r"another_valid_.*",
            ],
        )
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Valid patterns should work
        assert handler._is_file_changing_tool("valid_pattern")
        assert handler._is_file_changing_tool("another_valid_tool")

    def test_case_insensitive_matching(self):
        """Test that tool name matching is case-insensitive."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Different case variations should all match
        assert handler._is_file_changing_tool("write_to_file")
        assert handler._is_file_changing_tool("WRITE_TO_FILE")
        assert handler._is_file_changing_tool("Write_To_File")
        assert handler._is_file_changing_tool("WrItE_tO_fIlE")

    def test_non_file_changing_tools(self):
        """Test that non-file-changing tools are not recognized."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # These should not be recognized as file-changing
        non_file_tools = [
            "read_file",
            "list_files",
            "search_files",
            "get_file_info",
            "execute_command",
            "ask_followup_question",
            "attempt_completion",
        ]

        for tool_name in non_file_tools:
            assert not handler._is_file_changing_tool(
                tool_name
            ), f"Tool '{tool_name}' incorrectly identified as file-changing"


# ============================================================================
# Task 15.2: Test blocking logic
# ============================================================================


class TestBlockingLogic:
    """Tests for path blocking and allowing logic."""

    @pytest.mark.asyncio
    async def test_block_path_outside_boundary(self):
        """Test that paths outside project root are blocked."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks
        validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
        validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
        validator.is_within_boundary = Mock(return_value=False)

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.replacement_response is not None
        assert "outside of the project root" in result.replacement_response
        assert result.metadata["decision"] == "blocked"
        assert handler.get_metrics()["blocked_count"] == 1

    @pytest.mark.asyncio
    async def test_allow_path_inside_boundary(self):
        """Test that paths inside project root are allowed."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks
        validator.extract_paths_from_arguments = Mock(
            return_value=["/home/user/project/file.txt"]
        )
        validator.normalize_path = Mock(
            return_value=Path("/home/user/project/file.txt")
        )
        validator.is_within_boundary = Mock(return_value=True)

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/project/file.txt", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "allowed"
        assert handler.get_metrics()["allowed_count"] == 1

    @pytest.mark.asyncio
    async def test_strict_mode_blocks_unparseable_paths(self):
        """Test that strict mode blocks tool calls with unparseable paths."""
        config = SandboxingConfiguration(
            enabled=True,
            strict_mode=True,
        )
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks to simulate extraction failure
        validator.extract_paths_from_arguments = Mock(
            side_effect=ValueError("Invalid path format")
        )

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "invalid:::path", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.replacement_response is not None
        assert "Failed to extract file paths" in result.replacement_response
        assert result.metadata["decision"] == "blocked"
        assert handler.get_metrics()["validation_errors"] == 1

    @pytest.mark.asyncio
    async def test_non_strict_mode_allows_unparseable_paths(self):
        """Test that non-strict mode allows tool calls with unparseable paths."""
        config = SandboxingConfiguration(
            enabled=True,
            strict_mode=False,
        )
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks to simulate extraction failure
        validator.extract_paths_from_arguments = Mock(
            side_effect=ValueError("Invalid path format")
        )

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "invalid:::path", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.should_swallow is False
        assert result.metadata["decision"] == "extraction_error_fail_open"
        assert handler.get_metrics()["validation_errors"] == 1

    @pytest.mark.asyncio
    async def test_error_message_includes_project_root(self):
        """Test that error messages include the project root path."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks
        validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
        validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
        validator.is_within_boundary = Mock(return_value=False)

        project_dir = "/home/user/my_project"
        session = Session(
            session_id="test-session",
            state=SessionState(project_dir=project_dir),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        assert result.replacement_response is not None
        # Check that project root is mentioned (platform-agnostic)
        assert "my_project" in result.replacement_response
        # Project root in metadata will be normalized to platform format
        assert "my_project" in result.metadata["project_root"]

    @pytest.mark.asyncio
    async def test_multiple_violating_paths(self):
        """Test that all violating paths are included in error message."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks for multiple paths
        violating_paths = ["/etc/passwd", "/var/log/system.log"]
        validator.extract_paths_from_arguments = Mock(return_value=violating_paths)
        validator.normalize_path = Mock(side_effect=lambda p, base_dir=None: Path(p))
        validator.is_within_boundary = Mock(return_value=False)

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"paths": violating_paths},
        )

        result = await handler.handle(context)

        assert result.should_swallow is True
        assert result.replacement_response is not None
        # Both paths should be mentioned
        assert "/etc/passwd" in result.replacement_response
        assert "/var/log/system.log" in result.replacement_response


# ============================================================================
# Task 15.3: Test session state handling
# ============================================================================


class TestSessionStateHandling:
    """Tests for session state handling in sandboxing."""

    @pytest.mark.asyncio
    async def test_with_project_directory_set(self):
        """Test that sandboxing works when project directory is set."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks
        validator.extract_paths_from_arguments = Mock(
            return_value=["/home/user/project/file.txt"]
        )
        validator.normalize_path = Mock(
            return_value=Path("/home/user/project/file.txt")
        )
        validator.is_within_boundary = Mock(return_value=True)

        # Session with project directory set
        session = Session(
            session_id="test-session",
            state=SessionState(
                project_dir="/home/user/project",
                project_dir_resolution_attempted=True,
            ),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/project/file.txt", "content": "test"},
        )

        result = await handler.handle(context)

        # Should perform validation
        assert result.metadata["decision"] == "allowed"
        validator.extract_paths_from_arguments.assert_called_once()
        validator.normalize_path.assert_called_once()
        validator.is_within_boundary.assert_called_once()

    @pytest.mark.asyncio
    async def test_without_project_directory(self):
        """Test that sandboxing is skipped when no project directory is set."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Session without project directory
        session = Session(
            session_id="test-session",
            state=SessionState(
                project_dir=None,
                project_dir_resolution_attempted=True,
            ),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        # Should skip validation
        assert result.should_swallow is False
        assert result.metadata["decision"] == "skipped_no_project_dir"
        # Validator should not be called
        validator.extract_paths_from_arguments.assert_not_called()

    @pytest.mark.asyncio
    async def test_with_resolution_not_attempted(self):
        """Test behavior when project directory resolution not attempted."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Session where resolution hasn't been attempted yet
        session = Session(
            session_id="test-session",
            state=SessionState(
                project_dir=None,
                project_dir_resolution_attempted=False,
            ),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        # Should skip validation (no project dir)
        assert result.should_swallow is False
        assert result.metadata["decision"] == "skipped_no_project_dir"

    @pytest.mark.asyncio
    async def test_session_retrieval_error(self):
        """Test that session retrieval errors are handled gracefully."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure session service to raise error
        session_service.get_session = AsyncMock(
            side_effect=Exception("Session not found")
        )

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        context = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )

        result = await handler.handle(context)

        # Should fail open (allow the tool call)
        assert result.should_swallow is False
        assert result.metadata["decision"] == "error_fail_open"
        assert "error" in result.metadata

    @pytest.mark.asyncio
    async def test_different_sessions_isolated(self):
        """Test that different sessions are handled independently."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks
        validator.extract_paths_from_arguments = Mock(return_value=["/tmp/file.txt"])
        validator.normalize_path = Mock(return_value=Path("/tmp/file.txt"))
        validator.is_within_boundary = Mock(return_value=False)

        # Two different sessions with different project directories
        session1 = Session(
            session_id="session-1",
            state=SessionState(project_dir="/home/user/project1"),
        )
        session2 = Session(
            session_id="session-2",
            state=SessionState(project_dir="/home/user/project2"),
        )

        async def get_session_mock(session_id: str):
            if session_id == "session-1":
                return session1
            elif session_id == "session-2":
                return session2
            raise ValueError(f"Unknown session: {session_id}")

        session_service.get_session = AsyncMock(side_effect=get_session_mock)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Test with session 1
        context1 = ToolCallContext(
            session_id="session-1",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/tmp/file.txt", "content": "test"},
        )

        result1 = await handler.handle(context1)
        assert result1.metadata["session_id"] == "session-1"
        # Project root will be normalized to platform format
        assert "project1" in result1.metadata["project_root"]

        # Test with session 2
        context2 = ToolCallContext(
            session_id="session-2",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/tmp/file.txt", "content": "test"},
        )

        result2 = await handler.handle(context2)
        assert result2.metadata["session_id"] == "session-2"
        # Project root will be normalized to platform format
        assert "project2" in result2.metadata["project_root"]


# ============================================================================
# Task 15.4: Test metrics tracking
# ============================================================================


class TestMetricsTracking:
    """Tests for metrics tracking functionality."""

    @pytest.mark.asyncio
    async def test_blocked_count_increment(self):
        """Test that blocked count increments correctly."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks to block paths
        validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
        validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
        validator.is_within_boundary = Mock(return_value=False)

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Initial metrics
        metrics = handler.get_metrics()
        assert metrics["blocked_count"] == 0
        assert metrics["allowed_count"] == 0
        assert metrics["validation_errors"] == 0

        # Block first tool call
        context1 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/etc/passwd", "content": "test"},
        )
        await handler.handle(context1)

        metrics = handler.get_metrics()
        assert metrics["blocked_count"] == 1
        assert metrics["allowed_count"] == 0

        # Block second tool call
        context2 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="delete_file",
            tool_arguments={"path": "/var/log/system.log"},
        )
        await handler.handle(context2)

        metrics = handler.get_metrics()
        assert metrics["blocked_count"] == 2
        assert metrics["allowed_count"] == 0

    @pytest.mark.asyncio
    async def test_allowed_count_increment(self):
        """Test that allowed count increments correctly."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks to allow paths
        validator.extract_paths_from_arguments = Mock(
            return_value=["/home/user/project/file.txt"]
        )
        validator.normalize_path = Mock(
            return_value=Path("/home/user/project/file.txt")
        )
        validator.is_within_boundary = Mock(return_value=True)

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Initial metrics
        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 0

        # Allow first tool call
        context1 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/project/file.txt", "content": "test"},
        )
        await handler.handle(context1)

        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 1
        assert metrics["blocked_count"] == 0

        # Allow second tool call
        context2 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="edit_file",
            tool_arguments={"path": "/home/user/project/other.txt", "content": "test"},
        )
        await handler.handle(context2)

        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 2
        assert metrics["blocked_count"] == 0

    @pytest.mark.asyncio
    async def test_validation_error_count(self):
        """Test that validation error count increments correctly."""
        config = SandboxingConfiguration(
            enabled=True,
            strict_mode=False,  # Non-strict mode to allow errors
        )
        validator = Mock()
        session_service = AsyncMock()

        # Configure mocks to raise errors
        validator.extract_paths_from_arguments = Mock(
            side_effect=ValueError("Invalid path format")
        )

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Initial metrics
        metrics = handler.get_metrics()
        assert metrics["validation_errors"] == 0

        # Trigger validation error
        context1 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "invalid:::path", "content": "test"},
        )
        await handler.handle(context1)

        metrics = handler.get_metrics()
        assert metrics["validation_errors"] == 1

        # Trigger another validation error
        context2 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="edit_file",
            tool_arguments={"path": "another:::bad:::path", "content": "test"},
        )
        await handler.handle(context2)

        metrics = handler.get_metrics()
        assert metrics["validation_errors"] == 2

    @pytest.mark.asyncio
    async def test_mixed_metrics(self):
        """Test that all metrics work together correctly."""
        config = SandboxingConfiguration(
            enabled=True,
            strict_mode=False,
        )
        validator = Mock()
        session_service = AsyncMock()

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Scenario 1: Allow a valid path
        validator.extract_paths_from_arguments = Mock(
            return_value=["/home/user/project/file.txt"]
        )
        validator.normalize_path = Mock(
            return_value=Path("/home/user/project/file.txt")
        )
        validator.is_within_boundary = Mock(return_value=True)

        context1 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="write_to_file",
            tool_arguments={"path": "/home/user/project/file.txt", "content": "test"},
        )
        await handler.handle(context1)

        # Scenario 2: Block an invalid path
        validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
        validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
        validator.is_within_boundary = Mock(return_value=False)

        context2 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="delete_file",
            tool_arguments={"path": "/etc/passwd"},
        )
        await handler.handle(context2)

        # Scenario 3: Validation error
        validator.extract_paths_from_arguments = Mock(
            side_effect=ValueError("Invalid format")
        )

        context3 = ToolCallContext(
            session_id="test-session",
            backend_name="test-backend",
            model_name="test-model",
            full_response=None,
            tool_name="edit_file",
            tool_arguments={"path": "bad:::path", "content": "test"},
        )
        await handler.handle(context3)

        # Check final metrics
        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 1
        assert metrics["blocked_count"] == 1
        assert metrics["validation_errors"] == 1

    @pytest.mark.asyncio
    async def test_metrics_persist_across_calls(self):
        """Test that metrics persist across multiple tool calls."""
        config = SandboxingConfiguration(enabled=True)
        validator = Mock()
        session_service = AsyncMock()

        session = Session(
            session_id="test-session",
            state=SessionState(project_dir="/home/user/project"),
        )
        session_service.get_session = AsyncMock(return_value=session)

        handler = FileSandboxingHandler(
            config=config,
            path_validator=validator,
            session_service=session_service,
        )

        # Configure for allowed path
        validator.extract_paths_from_arguments = Mock(
            return_value=["/home/user/project/file.txt"]
        )
        validator.normalize_path = Mock(
            return_value=Path("/home/user/project/file.txt")
        )
        validator.is_within_boundary = Mock(return_value=True)

        # Make multiple calls
        for i in range(5):
            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="write_to_file",
                tool_arguments={
                    "path": f"/home/user/project/file{i}.txt",
                    "content": "test",
                },
            )
            await handler.handle(context)

        # Metrics should accumulate
        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 5

        # Configure for blocked path
        validator.extract_paths_from_arguments = Mock(return_value=["/etc/passwd"])
        validator.normalize_path = Mock(return_value=Path("/etc/passwd"))
        validator.is_within_boundary = Mock(return_value=False)

        # Make more calls
        for i in range(3):
            context = ToolCallContext(
                session_id="test-session",
                backend_name="test-backend",
                model_name="test-model",
                full_response=None,
                tool_name="delete_file",
                tool_arguments={"path": f"/etc/file{i}"},
            )
            await handler.handle(context)

        # Metrics should continue to accumulate
        metrics = handler.get_metrics()
        assert metrics["allowed_count"] == 5
        assert metrics["blocked_count"] == 3
