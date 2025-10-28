"""Integration tests for universal tool execution in the command system."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from src.core.commands.models import Command
from src.core.commands.registry import get_command_handler
from src.core.commands.service import NewCommandService
from src.core.domain.command_context import CommandContext


class TestUniversalToolIntegration:
    """Test that universal tools are properly integrated into the command system."""

    @pytest_asyncio.fixture
    async def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            
            # Create test files
            (workspace / "test_file.txt").write_text("Hello, World!\nLine 2\nLine 3")
            (workspace / "test_dir").mkdir()
            (workspace / "test_dir" / "nested_file.py").write_text("def hello():\n    print('Hello')")
            
            yield workspace

    @pytest_asyncio.fixture
    async def command_context(self, temp_workspace):
        """Create a command context for testing."""
        import os
        original_cwd = os.getcwd()
        os.chdir(str(temp_workspace))
        try:
            yield CommandContext()
        finally:
            os.chdir(original_cwd)

    def test_kilocode_tool_handlers_registered(self):
        """Test that KiloCode tool handlers are registered in the command registry."""
        kilocode_tools = [
            "read_file", "list_dir", "list_files", "grep_files", 
            "codebase_search", "search_files", "use_mcp_tool",
            "completion_marker", "attempt_completion", 
            "followup_marker", "ask_followup_question"
        ]
        
        for tool_name in kilocode_tools:
            handler = get_command_handler(tool_name)
            assert handler is not None, f"Handler not registered for tool: {tool_name}"

    async def test_read_file_command_execution(self, command_context, temp_workspace):
        """Test that read_file command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="read_file", args={"file_path": "test_file.txt"})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "Hello, World!" in result.message

    async def test_list_dir_command_execution(self, command_context, temp_workspace):
        """Test that list_dir command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="list_dir", args={"dir_path": "."})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "test_file.txt" in result.message
        assert "test_dir" in result.message

    async def test_list_files_alias_command_execution(self, command_context, temp_workspace):
        """Test that list_files (alias) command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="list_files", args={"dir_path": "."})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "test_file.txt" in result.message

    async def test_grep_files_command_execution(self, command_context, temp_workspace):
        """Test that grep_files command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="grep_files", args={"pattern": "Hello", "path": "."})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        # Should find matches in test files

    async def test_completion_marker_command_execution(self, command_context, temp_workspace):
        """Test that completion_marker command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="completion_marker", args={"result": "Task completed"})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "[COMPLETION]" in result.message
        assert "Task completed" in result.message

    async def test_attempt_completion_alias_command_execution(self, command_context, temp_workspace):
        """Test that attempt_completion (alias) command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="attempt_completion", args={"result": "Task done"})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "[COMPLETION]" in result.message

    async def test_followup_marker_command_execution(self, command_context, temp_workspace):
        """Test that followup_marker command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="followup_marker", args={"question": "Need help?"})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "[FOLLOWUP]" in result.message
        assert "Need help?" in result.message

    async def test_use_mcp_tool_command_execution(self, command_context, temp_workspace):
        """Test that use_mcp_tool command executes through the command system."""
        command_service = NewCommandService()
        
        command = Command(name="use_mcp_tool", args={
            "tool_name": "test_tool",
            "arguments": '{"key": "value"}'
        })
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is True
        assert "test_tool" in result.message

    async def test_unknown_tool_command_execution(self, command_context, temp_workspace):
        """Test that unknown tools return appropriate errors."""
        # This should fail because there's no handler for "unknown_tool"
        handler = get_command_handler("unknown_tool")
        assert handler is None

    async def test_command_error_handling(self, command_context, temp_workspace):
        """Test error handling in command execution."""
        command_service = NewCommandService()
        
        # Try to read a non-existent file
        command = Command(name="read_file", args={"file_path": "nonexistent.txt"})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is False
        assert "not found" in result.message.lower()

    async def test_command_with_missing_arguments(self, command_context, temp_workspace):
        """Test command execution with missing required arguments."""
        command_service = NewCommandService()
        
        # Try to read a file without providing file_path
        command = Command(name="read_file", args={})
        result = await command_service.execute_command(command, command_context)
        
        assert result.success is False
        assert "file_path is required" in result.message