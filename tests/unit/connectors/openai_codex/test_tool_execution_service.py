"""Unit tests for ToolExecutionService.

Tests cover proxy tool execution, MCP tool execution, error handling, and result formatting.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.connectors.openai_codex.contracts import ToolArguments, ToolExecutionResult
from src.connectors.openai_codex.interfaces import IToolExecutionService
from src.connectors.openai_codex.tools import ToolExecutionService


class TestToolExecutionService:
    """Test ToolExecutionService implementation."""

    @pytest.fixture
    def service(self):
        """Create a ToolExecutionService instance for testing."""
        return ToolExecutionService()

    @pytest.fixture
    def mock_kilo_translator(self):
        """Create a mock KiloToolTranslator."""
        translator = MagicMock()

        def format_result(tool_name, result):
            return f"[{tool_name}] Result: success"

        translator.format_tool_result = MagicMock(side_effect=format_result)
        translator.handle_conversation_control = AsyncMock(
            return_value="[attempt_completion] Task completion acknowledged: done"
        )
        translator._translate_mcp_parameters = MagicMock(
            side_effect=lambda params, schema: params
        )
        return translator

    @pytest.fixture
    def mock_universal_executor(self):
        """Create a mock UniversalToolExecutor."""
        executor = AsyncMock()
        executor.execute_tool = AsyncMock(
            return_value={"output": "execution result", "exit_code": 0}
        )
        return executor

    @pytest.fixture
    def mock_mcp_client(self):
        """Create a mock MCP client."""
        client = AsyncMock()
        client.call_tool = AsyncMock(
            return_value={"content": "mcp result", "isError": False}
        )
        client.is_connected = MagicMock(return_value=True)
        client.get_tool_schema = AsyncMock(return_value=None)
        return client

    def test_service_implements_interface(self, service):
        """Verify service implements IToolExecutionService interface."""
        assert isinstance(service, IToolExecutionService)

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_conversation_control_attempt_completion(
        self, service, mock_kilo_translator
    ):
        """Test executing attempt_completion conversation control tool."""
        service._kilo_translator = mock_kilo_translator

        arguments = ToolArguments(payload={"result": "task completed"})
        result = await service.execute_proxy_tool(
            "__proxy_attempt_completion", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "[attempt_completion]" in result.result
        mock_kilo_translator.handle_conversation_control.assert_called_once_with(
            "__proxy_attempt_completion",
            {"result": "task completed"},
            "test-session-123",
        )

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_conversation_control_ask_followup(
        self, service, mock_kilo_translator
    ):
        """Test executing ask_followup_question conversation control tool."""
        service._kilo_translator = mock_kilo_translator
        mock_kilo_translator.handle_conversation_control.return_value = (
            "[ask_followup_question] Question received: What next?"
        )

        arguments = ToolArguments(payload={"question": "What next?"})
        result = await service.execute_proxy_tool(
            "__proxy_ask_followup_question", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "[ask_followup_question]" in result.result
        mock_kilo_translator.handle_conversation_control.assert_called_once_with(
            "__proxy_ask_followup_question",
            {"question": "What next?"},
            "test-session-123",
        )

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_conversation_control_no_translator(self, service):
        """Test conversation control tool execution when translator is not available."""
        service._kilo_translator = None

        arguments = ToolArguments(payload={"result": "done"})
        result = await service.execute_proxy_tool(
            "__proxy_attempt_completion", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert result.error is not None
        assert "KiloToolTranslator not available" in result.error

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_via_universal_executor(
        self, service, mock_universal_executor, mock_kilo_translator
    ):
        """Test executing regular proxy tool via UniversalToolExecutor."""
        service._universal_executor = mock_universal_executor
        service._kilo_translator = mock_kilo_translator

        arguments = ToolArguments(payload={"file_path": "/tmp/test.txt"})
        result = await service.execute_proxy_tool(
            "__proxy_read_file", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "[read_file]" in result.result
        mock_universal_executor.execute_tool.assert_called_once_with(
            "read_file", {"file_path": "/tmp/test.txt"}
        )
        mock_kilo_translator.format_tool_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_lazy_executor_initialization(
        self, service, mock_kilo_translator
    ):
        """Test proxy tool execution creates executor lazily when not provided."""
        # Start with no executor - implementation should create one lazily
        service._universal_executor = None
        service._kilo_translator = mock_kilo_translator

        arguments = ToolArguments(payload={"file_path": "/tmp/test.txt"})
        result = await service.execute_proxy_tool(
            "__proxy_read_file", arguments, "test-session-123"
        )

        # Lazy initialization means executor is created, so we get a result
        # (it may fail due to actual file system access, but that's ok)
        assert isinstance(result, ToolExecutionResult)
        # After execution, executor should have been lazily created
        assert service._universal_executor is not None

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_executor_error(
        self, service, mock_universal_executor, mock_kilo_translator
    ):
        """Test proxy tool execution when executor raises an error."""
        service._universal_executor = mock_universal_executor
        service._kilo_translator = mock_kilo_translator
        mock_universal_executor.execute_tool.side_effect = Exception("Execution failed")

        arguments = ToolArguments(payload={"file_path": "/tmp/test.txt"})
        result = await service.execute_proxy_tool(
            "__proxy_read_file", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert result.error == "Execution failed"
        assert "[read_file] Error:" in result.result

    @pytest.mark.asyncio
    async def test_execute_proxy_tool_no_formatting(
        self, service, mock_universal_executor
    ):
        """Test proxy tool execution without KiloToolTranslator formatting."""
        service._universal_executor = mock_universal_executor
        service._kilo_translator = None

        arguments = ToolArguments(payload={"file_path": "/tmp/test.txt"})
        result = await service.execute_proxy_tool(
            "__proxy_read_file", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "execution result" in result.result

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_success(
        self, service, mock_mcp_client, mock_kilo_translator
    ):
        """Test successful MCP tool execution."""
        service._mcp_client = mock_mcp_client
        service._kilo_translator = mock_kilo_translator

        arguments = ToolArguments(
            payload={"tool_name": "test_mcp_tool", "tool_arguments": {"param": "value"}}
        )
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        mock_mcp_client.call_tool.assert_called_once_with(
            "test_mcp_tool", {"param": "value"}
        )
        mock_kilo_translator.format_tool_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_missing_tool_name(self, service):
        """Test MCP tool execution with missing tool_name parameter."""
        arguments = ToolArguments(payload={"tool_arguments": {"param": "value"}})
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert (
            "tool_name" in result.error.lower()
            or "missing" in result.error.lower()
            or "invalid" in result.error.lower()
        )

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_invalid_tool_name(self, service):
        """Test MCP tool execution with invalid tool_name parameter."""
        arguments = ToolArguments(payload={"tool_name": None, "tool_arguments": {}})
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "tool_name" in result.error.lower() or "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_no_mcp_client(self, service):
        """Test MCP tool execution when MCP client is not available."""
        service._mcp_client = None

        arguments = ToolArguments(
            payload={"tool_name": "test_tool", "tool_arguments": {}}
        )
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "mcp" in result.error.lower() or "not available" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_timeout(self, service, mock_mcp_client):
        """Test MCP tool execution timeout handling."""
        import asyncio

        service._mcp_client = mock_mcp_client
        mock_mcp_client.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

        arguments = ToolArguments(
            payload={"tool_name": "test_tool", "tool_arguments": {}}
        )
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_execution_error(self, service, mock_mcp_client):
        """Test MCP tool execution error handling."""
        service._mcp_client = mock_mcp_client
        mock_mcp_client.call_tool = AsyncMock(
            side_effect=Exception("MCP execution failed")
        )

        arguments = ToolArguments(
            payload={"tool_name": "test_tool", "tool_arguments": {}}
        )
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is False
        assert "failed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_no_formatting(self, service, mock_mcp_client):
        """Test MCP tool execution without KiloToolTranslator formatting."""
        service._mcp_client = mock_mcp_client
        service._kilo_translator = None

        arguments = ToolArguments(
            payload={"tool_name": "test_tool", "tool_arguments": {}}
        )
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        assert "mcp result" in result.result

    @pytest.mark.asyncio
    async def test_execute_mcp_tool_missing_tool_arguments(
        self, service, mock_mcp_client
    ):
        """Test MCP tool execution with missing tool_arguments (should default to empty dict)."""
        service._mcp_client = mock_mcp_client

        arguments = ToolArguments(payload={"tool_name": "test_tool"})
        result = await service.execute_mcp_tool(
            "__proxy_use_mcp_tool", arguments, "test-session-123"
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.success is True
        mock_mcp_client.call_tool.assert_called_once_with("test_tool", {})
