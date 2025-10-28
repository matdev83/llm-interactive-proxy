"""Unit tests for OpenAI Codex compatibility layer error handling."""

import logging
from unittest.mock import MagicMock

import pytest
from src.connectors._openai_codex_compatibility_errors import (
    CompatibilityErrorCode,
    TranslationError,
    create_mcp_bridge_error,
    create_parameter_validation_error,
    create_tool_execution_error,
    create_unsupported_tool_error,
    create_xml_parse_error,
    format_error_response,
    log_translation_error,
)


class TestCompatibilityErrorCode:
    """Test CompatibilityErrorCode enum."""

    def test_error_codes_defined(self):
        """Test that all error codes are properly defined."""
        assert CompatibilityErrorCode.UNSUPPORTED_TOOL.value == "COMPAT_E001"
        assert CompatibilityErrorCode.INVALID_XML_SYNTAX.value == "COMPAT_E002"
        assert CompatibilityErrorCode.PARAMETER_VALIDATION_FAILED.value == "COMPAT_E003"
        assert CompatibilityErrorCode.TOOL_EXECUTION_FAILED.value == "COMPAT_E004"
        assert CompatibilityErrorCode.MCP_BRIDGE_ERROR.value == "COMPAT_E005"
        assert CompatibilityErrorCode.DETECTION_FAILED.value == "COMPAT_E006"
        assert CompatibilityErrorCode.TRANSLATION_TIMEOUT.value == "COMPAT_E007"


class TestTranslationError:
    """Test TranslationError exception class."""

    def test_translation_error_basic(self):
        """Test basic TranslationError creation."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E001",
        )

        assert str(error) == "Test error"
        assert error.tool_name == "test_tool"
        assert error.error_code == "COMPAT_E001"
        assert error.original_xml is None
        assert error.session_id is None
        assert error.details == {}

    def test_translation_error_with_enum(self):
        """Test TranslationError with enum error code."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code=CompatibilityErrorCode.UNSUPPORTED_TOOL,
        )

        assert error.error_code == "COMPAT_E001"

    def test_translation_error_with_all_fields(self):
        """Test TranslationError with all fields."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E003",
            original_xml="<test>xml</test>",
            session_id="session123",
            details={"key": "value"},
        )

        assert error.original_xml == "<test>xml</test>"
        assert error.session_id == "session123"
        assert error.details == {"key": "value"}

    def test_translation_error_to_dict(self):
        """Test TranslationError.to_dict() method."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E001",
            original_xml="<test>xml</test>",
            session_id="session123",
            details={"key": "value"},
        )

        result = error.to_dict()

        assert result["error"] is True
        assert result["error_code"] == "COMPAT_E001"
        assert result["message"] == "Test error"
        assert result["tool_name"] == "test_tool"
        assert result["original_xml"] == "<test>xml</test>"
        assert result["session_id"] == "session123"
        assert result["details"] == {"key": "value"}


class TestFormatErrorResponse:
    """Test error response formatting."""

    def test_format_error_response_basic(self):
        """Test basic error response formatting."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code=CompatibilityErrorCode.UNSUPPORTED_TOOL,
        )

        response = format_error_response(error)

        assert response["error"] is True
        assert response["error_code"] == "COMPAT_E001"
        assert response["message"] == "Test error"
        assert response["tool_name"] == "test_tool"
        assert "timestamp" in response
        assert "suggestions" in response

    def test_format_error_response_without_suggestions(self):
        """Test error response formatting without suggestions."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code=CompatibilityErrorCode.UNSUPPORTED_TOOL,
        )

        response = format_error_response(error, include_suggestions=False)

        assert "suggestions" not in response

    def test_format_error_response_unsupported_tool(self):
        """Test error response for unsupported tool includes suggestions."""
        error = create_unsupported_tool_error(
            tool_name="browser_action",
            original_xml="<browser_action>test</browser_action>",
        )

        response = format_error_response(error)

        assert response["error_code"] == "COMPAT_E001"
        assert "suggestions" in response
        assert len(response["suggestions"]) > 0
        # Should suggest codebase_search for browser actions
        assert any("codebase_search" in s for s in response["suggestions"])

    def test_format_error_response_invalid_xml(self):
        """Test error response for invalid XML includes suggestions."""
        error = create_xml_parse_error(
            message="Failed to parse XML",
            original_xml="<read_file>unclosed",
        )

        response = format_error_response(error)

        assert response["error_code"] == "COMPAT_E002"
        assert "suggestions" in response
        assert any("properly closed" in s for s in response["suggestions"])

    def test_format_error_response_parameter_validation(self):
        """Test error response for parameter validation includes details."""
        error = create_parameter_validation_error(
            tool_name="read_file",
            message="Missing required parameters",
            missing_parameters=["path"],
            invalid_parameters={"start_line": "must be integer"},
        )

        response = format_error_response(error)

        assert response["error_code"] == "COMPAT_E003"
        assert "suggestions" in response
        # Should mention missing parameters
        assert any("path" in s for s in response["suggestions"])
        # Should mention invalid parameters
        assert any("start_line" in s for s in response["suggestions"])

    def test_format_error_response_tool_execution(self):
        """Test error response for tool execution failure includes exit code."""
        error = create_tool_execution_error(
            tool_name="execute_command",
            message="Command failed",
            exit_code=1,
            stderr="Error output",
        )

        response = format_error_response(error)

        assert response["error_code"] == "COMPAT_E004"
        assert "suggestions" in response
        # Should mention exit code
        assert any("Exit code: 1" in s for s in response["suggestions"])
        # Should mention error output
        assert any("Error output" in s for s in response["suggestions"])

    def test_format_error_response_mcp_bridge(self):
        """Test error response for MCP bridge error includes MCP details."""
        error = create_mcp_bridge_error(
            tool_name="use_mcp_tool",
            message="MCP tool failed",
            mcp_error="Tool not found",
            mcp_tool_name="patch_file",
        )

        response = format_error_response(error)

        assert response["error_code"] == "COMPAT_E005"
        assert "suggestions" in response
        # Should mention MCP error
        assert any("Tool not found" in s for s in response["suggestions"])


class TestLogTranslationError:
    """Test error logging functionality."""

    def test_log_translation_error_basic(self):
        """Test basic error logging."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E001",
        )

        mock_logger = MagicMock(spec=logging.Logger)

        log_translation_error(error, mock_logger)

        # Verify logger.error was called
        assert mock_logger.error.called
        call_args = mock_logger.error.call_args

        # Check message format - args[0] contains format string and args
        # The actual values are in args[1], args[2], etc.
        assert "Translation error" in call_args[0][0]
        # Check that error code is passed as argument
        assert call_args[0][1] == "COMPAT_E001"
        assert call_args[0][3] == "test_tool"

        # Check extra context
        assert "extra" in call_args[1]
        extra = call_args[1]["extra"]
        assert extra["error_code"] == "COMPAT_E001"
        assert extra["tool_name"] == "test_tool"

    def test_log_translation_error_with_context(self):
        """Test error logging includes all context."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E003",
            original_xml="<test>xml</test>",
            session_id="session123",
            details={"key": "value"},
        )

        mock_logger = MagicMock(spec=logging.Logger)

        log_translation_error(error, mock_logger)

        call_args = mock_logger.error.call_args
        extra = call_args[1]["extra"]

        assert extra["original_xml"] == "<test>xml</test>"
        assert extra["session_id"] == "session123"
        assert extra["details"] == {"key": "value"}

    def test_log_translation_error_with_stack_trace(self):
        """Test error logging includes stack trace."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E001",
        )

        mock_logger = MagicMock(spec=logging.Logger)

        log_translation_error(error, mock_logger, include_stack_trace=True)

        call_args = mock_logger.error.call_args
        assert call_args[1]["exc_info"] is True

    def test_log_translation_error_without_stack_trace(self):
        """Test error logging without stack trace."""
        error = TranslationError(
            message="Test error",
            tool_name="test_tool",
            error_code="COMPAT_E001",
        )

        mock_logger = MagicMock(spec=logging.Logger)

        log_translation_error(error, mock_logger, include_stack_trace=False)

        call_args = mock_logger.error.call_args
        assert call_args[1]["exc_info"] is False


class TestErrorCreationHelpers:
    """Test error creation helper functions."""

    def test_create_unsupported_tool_error(self):
        """Test creating unsupported tool error."""
        error = create_unsupported_tool_error(
            tool_name="browser_action",
            original_xml="<browser_action>test</browser_action>",
            session_id="session123",
            supported_tools=["read_file", "list_files"],
        )

        assert error.error_code == "COMPAT_E001"
        assert error.tool_name == "browser_action"
        assert error.original_xml == "<browser_action>test</browser_action>"
        assert error.session_id == "session123"
        assert error.details["supported_tools"] == ["read_file", "list_files"]

    def test_create_parameter_validation_error(self):
        """Test creating parameter validation error."""
        error = create_parameter_validation_error(
            tool_name="read_file",
            message="Missing required parameters",
            original_xml="<read_file></read_file>",
            session_id="session123",
            missing_parameters=["path"],
            invalid_parameters={"start_line": "must be integer"},
        )

        assert error.error_code == "COMPAT_E003"
        assert error.tool_name == "read_file"
        assert error.details["missing_parameters"] == ["path"]
        assert error.details["invalid_parameters"] == {"start_line": "must be integer"}

    def test_create_tool_execution_error(self):
        """Test creating tool execution error."""
        error = create_tool_execution_error(
            tool_name="execute_command",
            message="Command failed",
            original_xml="<execute_command>ls</execute_command>",
            session_id="session123",
            exit_code=1,
            stderr="Error output",
            stdout="Standard output",
        )

        assert error.error_code == "COMPAT_E004"
        assert error.tool_name == "execute_command"
        assert error.details["exit_code"] == 1
        assert error.details["stderr"] == "Error output"
        assert error.details["stdout"] == "Standard output"

    def test_create_mcp_bridge_error(self):
        """Test creating MCP bridge error."""
        error = create_mcp_bridge_error(
            tool_name="use_mcp_tool",
            message="MCP tool failed",
            original_xml="<use_mcp_tool>test</use_mcp_tool>",
            session_id="session123",
            mcp_error="Tool not found",
            mcp_tool_name="patch_file",
        )

        assert error.error_code == "COMPAT_E005"
        assert error.tool_name == "use_mcp_tool"
        assert error.details["mcp_error"] == "Tool not found"
        assert error.details["mcp_tool_name"] == "patch_file"

    def test_create_xml_parse_error(self):
        """Test creating XML parse error."""
        error = create_xml_parse_error(
            message="Failed to parse XML",
            original_xml="<read_file>unclosed",
            session_id="session123",
        )

        assert error.error_code == "COMPAT_E002"
        assert error.tool_name == "unknown"
        assert error.original_xml == "<read_file>unclosed"
        assert error.session_id == "session123"


class TestErrorsNotSuppressed:
    """Test that translation errors are never suppressed."""

    @pytest.mark.asyncio
    async def test_translation_error_propagates(self):
        """Test that TranslationError is not caught and suppressed."""
        from src.connectors._openai_codex_kilo_tool_translator import (
            KiloToolTranslator,
        )

        mock_connector = MagicMock()
        translator = KiloToolTranslator(mock_connector)

        # Malformed XML should raise TranslationError
        # Empty path tag will be caught by XML parser
        with pytest.raises(TranslationError) as exc_info:
            await translator.translate_tool_invocation(
                "<read_file><path></path></read_file>"
            )

        # Verify error has proper context
        error = exc_info.value
        assert error.error_code == "COMPAT_E002"

    @pytest.mark.asyncio
    async def test_parameter_validation_error_propagates(self):
        """Test that parameter validation errors are not suppressed."""
        from src.connectors._openai_codex_kilo_tool_translator import (
            KiloToolTranslator,
        )

        mock_connector = MagicMock()
        translator = KiloToolTranslator(mock_connector)

        # Missing required parameter should raise TranslationError
        # The XML parser will catch this as XMLParseError which gets wrapped
        with pytest.raises(TranslationError) as exc_info:
            await translator.translate_tool_invocation("<read_file></read_file>")

        # Verify error has proper context
        # This is caught by XML parser, so it's COMPAT_E002
        error = exc_info.value
        assert error.error_code == "COMPAT_E002"


class TestActionableErrorMessages:
    """Test that error messages are actionable."""

    def test_unsupported_tool_message_actionable(self):
        """Test unsupported tool error has actionable message."""
        error = create_unsupported_tool_error(
            tool_name="browser_action",
            supported_tools=["read_file", "list_files"],
        )

        response = format_error_response(error)

        # Should have multiple suggestions
        assert len(response["suggestions"]) >= 2

        # Should mention the tool is not supported
        assert any("not currently supported" in s for s in response["suggestions"])

        # Should list supported tools
        assert any("read_file" in s for s in response["suggestions"])

    def test_parameter_validation_message_actionable(self):
        """Test parameter validation error has actionable message."""
        error = create_parameter_validation_error(
            tool_name="read_file",
            message="Missing required parameters",
            missing_parameters=["path"],
        )

        response = format_error_response(error)

        # Should mention missing parameters
        assert any("path" in s for s in response["suggestions"])

    def test_tool_execution_message_actionable(self):
        """Test tool execution error has actionable message."""
        error = create_tool_execution_error(
            tool_name="execute_command",
            message="Command failed",
            exit_code=127,
            stderr="command not found",
        )

        response = format_error_response(error)

        # Should mention exit code and error output
        assert any("127" in s for s in response["suggestions"])
        assert any("command not found" in s for s in response["suggestions"])
