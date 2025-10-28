"""Unit tests for Universal Tool Execution."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from src.core.services.universal_tool_executor import UniversalToolExecutor
from src.core.services.universal_mcp_client import UniversalMCPClient, MCPToolDefinition


class TestUniversalToolExecutor:
    """Test universal tool execution functionality."""

    @pytest_asyncio.fixture
    async def temp_workspace(self):
        """Create a temporary workspace for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            
            # Create test files and directories
            (workspace / "test_file.txt").write_text("Hello, World!\nLine 2\nLine 3")
            (workspace / "test_dir").mkdir()
            (workspace / "test_dir" / "nested_file.py").write_text("def hello():\n    print('Hello')")
            (workspace / ".hidden_file").write_text("Hidden content")
            
            yield workspace

    @pytest_asyncio.fixture
    async def executor(self, temp_workspace):
        """Create a universal tool executor."""
        return UniversalToolExecutor(working_directory=str(temp_workspace))

    async def test_built_in_tool_registration(self, executor):
        """Test that built-in tools are properly registered."""
        available_tools = executor.get_available_tools()
        
        expected_tools = [
            "read_file", "list_dir", "list_files", "grep_files", 
            "codebase_search", "search_files", "completion_marker", 
            "attempt_completion", "followup_marker", "ask_followup_question"
        ]
        
        for tool in expected_tools:
            assert tool in available_tools, f"Missing built-in tool: {tool}"

    async def test_custom_tool_registration(self, executor):
        """Test registering custom tool handlers."""
        async def custom_handler(arguments):
            return {"output": f"Custom tool executed with {arguments}", "exit_code": 0}
        
        executor.register_tool_handler("custom_tool", custom_handler)
        
        available_tools = executor.get_available_tools()
        assert "custom_tool" in available_tools
        
        result = await executor.execute_tool("custom_tool", {"arg1": "value1"})
        assert result["exit_code"] == 0
        assert "Custom tool executed" in result["output"]

    async def test_read_file_execution(self, executor, temp_workspace):
        """Test read_file tool execution."""
        result = await executor.execute_tool("read_file", {"file_path": "test_file.txt"})
        
        assert result["exit_code"] == 0
        assert "Hello, World!" in result["output"]
        assert "Line 2" in result["output"]

    async def test_list_dir_execution(self, executor, temp_workspace):
        """Test list_dir tool execution."""
        result = await executor.execute_tool("list_dir", {"dir_path": "."})
        
        assert result["exit_code"] == 0
        assert "test_file.txt" in result["output"]
        assert "test_dir" in result["output"]

    async def test_list_files_alias(self, executor, temp_workspace):
        """Test that list_files works as an alias for list_dir."""
        result = await executor.execute_tool("list_files", {"dir_path": "."})
        
        assert result["exit_code"] == 0
        assert "test_file.txt" in result["output"]

    async def test_grep_files_execution(self, executor, temp_workspace):
        """Test grep_files tool execution."""
        result = await executor.execute_tool("grep_files", {"pattern": "Hello", "path": "."})
        
        assert result["exit_code"] == 0
        # Should find matches in test files

    async def test_completion_marker_execution(self, executor, temp_workspace):
        """Test completion marker execution."""
        result = await executor.execute_tool("completion_marker", {"result": "Task done"})
        
        assert result["exit_code"] == 0
        assert "[COMPLETION]" in result["output"]
        assert "Task done" in result["output"]

    async def test_attempt_completion_alias(self, executor, temp_workspace):
        """Test that attempt_completion works as an alias."""
        result = await executor.execute_tool("attempt_completion", {"result": "Task done"})
        
        assert result["exit_code"] == 0
        assert "[COMPLETION]" in result["output"]

    async def test_followup_marker_execution(self, executor, temp_workspace):
        """Test followup marker execution."""
        result = await executor.execute_tool("followup_marker", {"question": "Need help?"})
        
        assert result["exit_code"] == 0
        assert "[FOLLOWUP]" in result["output"]
        assert "Need help?" in result["output"]

    async def test_unknown_tool_error(self, executor, temp_workspace):
        """Test handling of unknown tools."""
        result = await executor.execute_tool("unknown_tool", {})
        
        assert result["exit_code"] == 1
        assert "Unknown tool" in result["output"]
        assert "Available tools:" in result["output"]

    async def test_mcp_tool_execution_priority(self, executor, temp_workspace):
        """Test that MCP tools are checked after built-in tools."""
        # Mock the MCP client to simulate an MCP tool
        mock_mcp_tool = MCPToolDefinition("test_mcp_tool", "Test MCP tool", {})
        executor.mcp_client._discovered_tools["test_mcp_tool"] = mock_mcp_tool
        
        # Mock the execution
        with patch.object(executor.mcp_client, 'execute_tool') as mock_execute:
            mock_execute.return_value = {"output": "MCP tool result", "exit_code": 0}
            
            result = await executor.execute_tool("test_mcp_tool", {"arg": "value"})
            
            assert result["exit_code"] == 0
            assert "MCP tool result" in result["output"]
            mock_execute.assert_called_once_with("test_mcp_tool", {"arg": "value"})

    async def test_generic_mcp_tool_execution(self, executor, temp_workspace):
        """Test generic MCP tool execution via use_mcp_tool."""
        with patch.object(executor.mcp_client, 'execute_tool') as mock_execute:
            mock_execute.return_value = {"output": "Generic MCP result", "exit_code": 0}
            
            result = await executor.execute_tool("use_mcp_tool", {
                "tool_name": "some_mcp_tool",
                "arguments": '{"key": "value"}',
                "path": "/some/path"
            })
            
            assert result["exit_code"] == 0
            mock_execute.assert_called_once_with("some_mcp_tool", {
                "key": "value",
                "path": "/some/path"
            })

    async def test_generic_mcp_tool_with_raw_content(self, executor, temp_workspace):
        """Test generic MCP tool with non-JSON content."""
        with patch.object(executor.mcp_client, 'execute_tool') as mock_execute:
            mock_execute.return_value = {"output": "Raw content result", "exit_code": 0}
            
            result = await executor.execute_tool("use_mcp_tool", {
                "tool_name": "text_tool",
                "arguments": "raw text content"
            })
            
            assert result["exit_code"] == 0
            mock_execute.assert_called_once_with("text_tool", {
                "content": "raw text content"
            })

    async def test_use_mcp_tool_missing_tool_name(self, executor, temp_workspace):
        """Test use_mcp_tool without tool_name."""
        result = await executor.execute_tool("use_mcp_tool", {"arguments": "some content"})
        
        assert result["exit_code"] == 1
        assert "tool_name is required" in result["output"]

    async def test_mcp_server_connection(self, executor, temp_workspace):
        """Test MCP server connection."""
        with patch.object(executor.mcp_client, 'connect_to_server') as mock_connect:
            mock_connect.return_value = True
            
            result = await executor.connect_mcp_server("test_server", {"type": "stdio"})
            
            assert result is True
            mock_connect.assert_called_once_with("test_server", {"type": "stdio"})

    async def test_tool_execution_exception_handling(self, executor, temp_workspace):
        """Test exception handling in tool execution."""
        # Register a handler that raises an exception
        async def failing_handler(arguments):
            raise ValueError("Test error")
        
        executor.register_tool_handler("failing_tool", failing_handler)
        
        result = await executor.execute_tool("failing_tool", {})
        
        assert result["exit_code"] == 1
        assert "Error executing failing_tool" in result["output"]
        assert "Test error" in result["output"]


class TestUniversalMCPClient:
    """Test universal MCP client functionality."""

    @pytest_asyncio.fixture
    async def mcp_client(self):
        """Create a universal MCP client."""
        return UniversalMCPClient()

    async def test_server_connection_placeholder(self, mcp_client):
        """Test server connection placeholder implementation."""
        result = await mcp_client.connect_to_server("test_server", {"type": "stdio"})
        
        # Should succeed with placeholder implementation
        assert result is True
        assert "test_server" in mcp_client._connected_servers

    async def test_tool_discovery_placeholder(self, mcp_client):
        """Test tool discovery placeholder implementation."""
        await mcp_client.connect_to_server("test_server", {"type": "stdio"})
        
        # Placeholder implementation should have no tools initially
        tools = mcp_client.get_available_tools()
        assert isinstance(tools, list)

    async def test_tool_execution_placeholder(self, mcp_client):
        """Test tool execution placeholder implementation."""
        # Manually add a tool for testing
        tool_def = MCPToolDefinition("test_tool", "Test tool", {"type": "object"})
        mcp_client._discovered_tools["test_tool"] = tool_def
        mcp_client._tool_to_server_map["test_tool"] = "test_server"
        mcp_client._connected_servers["test_server"] = {"status": "connected"}
        
        result = await mcp_client.execute_tool("test_tool", {"arg": "value"})
        
        assert result["exit_code"] == 0
        assert "test_tool" in result["output"]
        assert result["tool_name"] == "test_tool"

    async def test_tool_not_found(self, mcp_client):
        """Test execution of non-existent tool."""
        result = await mcp_client.execute_tool("nonexistent_tool", {})
        
        assert result["exit_code"] == 1
        assert "not found" in result["output"]

    async def test_server_disconnection(self, mcp_client):
        """Test server disconnection."""
        # Connect and add a tool
        await mcp_client.connect_to_server("test_server", {"type": "stdio"})
        tool_def = MCPToolDefinition("test_tool", "Test tool", {"type": "object"})
        mcp_client._discovered_tools["test_tool"] = tool_def
        mcp_client._tool_to_server_map["test_tool"] = "test_server"
        
        # Disconnect
        await mcp_client.disconnect_server("test_server")
        
        # Tool should be removed
        assert "test_tool" not in mcp_client._discovered_tools
        assert "test_server" not in mcp_client._connected_servers

    async def test_mcp_tool_definition_to_openai_schema(self):
        """Test conversion of MCP tool definition to OpenAI schema."""
        tool_def = MCPToolDefinition(
            "test_tool",
            "A test tool",
            {
                "type": "object",
                "properties": {
                    "arg1": {"type": "string", "description": "First argument"}
                },
                "required": ["arg1"]
            }
        )
        
        schema = tool_def.to_openai_schema()
        
        assert schema["type"] == "function"
        assert schema["name"] == "test_tool"
        assert schema["description"] == "A test tool"
        assert schema["parameters"]["type"] == "object"
        assert "arg1" in schema["parameters"]["properties"]

    async def test_get_server_status(self, mcp_client):
        """Test getting server status."""
        await mcp_client.connect_to_server("server1", {"type": "stdio"})
        await mcp_client.connect_to_server("server2", {"type": "websocket"})
        
        status = mcp_client.get_server_status()
        
        assert "server1" in status
        assert "server2" in status
        assert status["server1"]["status"] == "connected"
        assert status["server2"]["status"] == "connected"