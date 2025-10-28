"""Error handling for OpenAI Codex-KiloCode compatibility layer."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CompatibilityErrorCode(Enum):
    """Error codes for compatibility layer failures."""

    UNSUPPORTED_TOOL = "COMPAT_E001"
    INVALID_XML_SYNTAX = "COMPAT_E002"
    PARAMETER_VALIDATION_FAILED = "COMPAT_E003"
    TOOL_EXECUTION_FAILED = "COMPAT_E004"
    MCP_BRIDGE_ERROR = "COMPAT_E005"
    DETECTION_FAILED = "COMPAT_E006"
    TRANSLATION_TIMEOUT = "COMPAT_E007"


class TranslationError(Exception):
    """Raised when tool translation fails.

    This exception is never suppressed and always includes full context
    for debugging and user feedback.
    """

    def __init__(
        self,
        message: str,
        tool_name: str,
        error_code: str | CompatibilityErrorCode,
        original_xml: str | None = None,
        session_id: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        """Initialize translation error.

        Args:
            message: Human-readable error message
            tool_name: Name of the tool that failed translation
            error_code: Error code (string or enum value)
            original_xml: Original XML that caused the error
            session_id: Session ID for tracking
            details: Additional context details
        """
        super().__init__(message)
        self.tool_name = tool_name
        self.error_code = (
            error_code.value
            if isinstance(error_code, CompatibilityErrorCode)
            else error_code
        )
        self.original_xml = original_xml
        self.session_id = session_id
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert error to dictionary for serialization.

        Returns:
            Dictionary representation of the error
        """
        return {
            "error": True,
            "error_code": self.error_code,
            "message": str(self),
            "tool_name": self.tool_name,
            "original_xml": self.original_xml,
            "session_id": self.session_id,
            "details": self.details,
        }


def format_error_response(
    error: TranslationError,
    include_suggestions: bool = True,
) -> dict[str, Any]:
    """Format error response with actionable messages.

    Args:
        error: The translation error to format
        include_suggestions: Whether to include suggestions for resolution

    Returns:
        Formatted error response dictionary
    """
    response = error.to_dict()

    # Add timestamp
    import time

    response["timestamp"] = time.time()

    # Add actionable suggestions based on error code
    if include_suggestions:
        suggestions = _get_error_suggestions(error)
        if suggestions:
            response["suggestions"] = suggestions

    return response


def _get_error_suggestions(error: TranslationError) -> list[str]:
    """Get actionable suggestions based on error code.

    Args:
        error: The translation error

    Returns:
        List of suggestion strings
    """
    suggestions = []

    if error.error_code == CompatibilityErrorCode.UNSUPPORTED_TOOL.value:
        suggestions.append(
            f"The tool '{error.tool_name}' is not currently supported by the compatibility layer."
        )
        suggestions.append(
            "Supported tools include: read_file, list_files, execute_command, "
            "codebase_search, search_files, use_mcp_tool, access_mcp_resource, "
            "attempt_completion, ask_followup_question, and editing tools."
        )
        if "browser" in error.tool_name.lower():
            suggestions.append(
                "For browser-related tasks, consider using codebase_search to find relevant code patterns."
            )

    elif error.error_code == CompatibilityErrorCode.INVALID_XML_SYNTAX.value:
        suggestions.append("Check that your XML tags are properly closed and nested.")
        suggestions.append(
            "Ensure all required parameters are provided within the XML tags."
        )
        if error.original_xml:
            suggestions.append(f"Problematic XML: {error.original_xml[:200]}...")

    elif error.error_code == CompatibilityErrorCode.PARAMETER_VALIDATION_FAILED.value:
        suggestions.append(
            f"The tool '{error.tool_name}' is missing required parameters or has invalid parameter values."
        )
        if error.details:
            missing_params = error.details.get("missing_parameters", [])
            if missing_params:
                suggestions.append(f"Missing parameters: {', '.join(missing_params)}")
            invalid_params = error.details.get("invalid_parameters", {})
            if invalid_params:
                for param, reason in invalid_params.items():
                    suggestions.append(f"Invalid parameter '{param}': {reason}")

    elif error.error_code == CompatibilityErrorCode.TOOL_EXECUTION_FAILED.value:
        suggestions.append(f"The tool '{error.tool_name}' failed during execution.")
        if error.details:
            exit_code = error.details.get("exit_code")
            if exit_code is not None:
                suggestions.append(f"Exit code: {exit_code}")
            stderr = error.details.get("stderr")
            if stderr:
                suggestions.append(f"Error output: {stderr[:200]}")

    elif error.error_code == CompatibilityErrorCode.MCP_BRIDGE_ERROR.value:
        suggestions.append("Failed to communicate with MCP server or execute MCP tool.")
        suggestions.append(
            "Verify that the MCP server is running and the tool is available."
        )
        if error.details:
            mcp_error = error.details.get("mcp_error")
            if mcp_error:
                suggestions.append(f"MCP error: {mcp_error}")

    elif error.error_code == CompatibilityErrorCode.DETECTION_FAILED.value:
        suggestions.append(
            "Failed to detect client type. This may indicate a configuration issue."
        )
        suggestions.append(
            "Ensure that agent metadata or User-Agent headers are properly set."
        )

    elif error.error_code == CompatibilityErrorCode.TRANSLATION_TIMEOUT.value:
        suggestions.append(
            "Translation operation timed out. This may indicate a performance issue."
        )
        suggestions.append(
            "Consider simplifying the request or checking for infinite loops."
        )

    return suggestions


def log_translation_error(
    error: TranslationError,
    logger_instance: logging.Logger | None = None,
    include_stack_trace: bool = True,
) -> None:
    """Log translation error with full context.

    Args:
        error: The translation error to log
        logger_instance: Logger to use (defaults to module logger)
        include_stack_trace: Whether to include stack trace
    """
    log = logger_instance or logger

    # Build log context
    extra = {
        "error_code": error.error_code,
        "tool_name": error.tool_name,
        "session_id": error.session_id,
        "original_xml": error.original_xml,
        "details": error.details,
    }

    # Log the error
    log.error(
        "Translation error [%s]: %s (tool: %s, session: %s)",
        error.error_code,
        str(error),
        error.tool_name,
        error.session_id or "unknown",
        exc_info=include_stack_trace,
        extra=extra,
    )


def create_unsupported_tool_error(
    tool_name: str,
    original_xml: str | None = None,
    session_id: str | None = None,
    supported_tools: list[str] | None = None,
) -> TranslationError:
    """Create an error for unsupported tools.

    Args:
        tool_name: Name of the unsupported tool
        original_xml: Original XML that contained the tool
        session_id: Session ID for tracking
        supported_tools: List of supported tool names

    Returns:
        TranslationError with appropriate context
    """
    details = {}
    if supported_tools:
        details["supported_tools"] = supported_tools

    return TranslationError(
        message=f"Unknown conversation control tool: {tool_name}",
        tool_name=tool_name,
        error_code=CompatibilityErrorCode.UNSUPPORTED_TOOL,
        original_xml=original_xml,
        session_id=session_id,
        details=details,
    )


def create_parameter_validation_error(
    tool_name: str,
    message: str,
    original_xml: str | None = None,
    session_id: str | None = None,
    missing_parameters: list[str] | None = None,
    invalid_parameters: dict[str, str] | None = None,
) -> TranslationError:
    """Create an error for parameter validation failures.

    Args:
        tool_name: Name of the tool with invalid parameters
        message: Error message
        original_xml: Original XML that contained the tool
        session_id: Session ID for tracking
        missing_parameters: List of missing parameter names
        invalid_parameters: Dict of parameter name to validation error

    Returns:
        TranslationError with appropriate context
    """
    details: dict[str, Any] = {}
    if missing_parameters:
        details["missing_parameters"] = missing_parameters
    if invalid_parameters:
        details["invalid_parameters"] = invalid_parameters

    return TranslationError(
        message=message,
        tool_name=tool_name,
        error_code=CompatibilityErrorCode.PARAMETER_VALIDATION_FAILED,
        original_xml=original_xml,
        session_id=session_id,
        details=details,
    )


def create_tool_execution_error(
    tool_name: str,
    message: str,
    original_xml: str | None = None,
    session_id: str | None = None,
    exit_code: int | None = None,
    stderr: str | None = None,
    stdout: str | None = None,
) -> TranslationError:
    """Create an error for tool execution failures.

    Args:
        tool_name: Name of the tool that failed
        message: Error message
        original_xml: Original XML that contained the tool
        session_id: Session ID for tracking
        exit_code: Exit code from command execution
        stderr: Standard error output
        stdout: Standard output

    Returns:
        TranslationError with appropriate context
    """
    details: dict[str, Any] = {}
    if exit_code is not None:
        details["exit_code"] = exit_code
    if stderr:
        details["stderr"] = stderr
    if stdout:
        details["stdout"] = stdout

    return TranslationError(
        message=message,
        tool_name=tool_name,
        error_code=CompatibilityErrorCode.TOOL_EXECUTION_FAILED,
        original_xml=original_xml,
        session_id=session_id,
        details=details,
    )


def create_mcp_bridge_error(
    tool_name: str,
    message: str,
    original_xml: str | None = None,
    session_id: str | None = None,
    mcp_error: str | None = None,
    mcp_tool_name: str | None = None,
) -> TranslationError:
    """Create an error for MCP bridge failures.

    Args:
        tool_name: Name of the tool that failed
        message: Error message
        original_xml: Original XML that contained the tool
        session_id: Session ID for tracking
        mcp_error: Error message from MCP server
        mcp_tool_name: Name of the MCP tool that failed

    Returns:
        TranslationError with appropriate context
    """
    details = {}
    if mcp_error:
        details["mcp_error"] = mcp_error
    if mcp_tool_name:
        details["mcp_tool_name"] = mcp_tool_name

    return TranslationError(
        message=message,
        tool_name=tool_name,
        error_code=CompatibilityErrorCode.MCP_BRIDGE_ERROR,
        original_xml=original_xml,
        session_id=session_id,
        details=details,
    )


def create_xml_parse_error(
    message: str,
    original_xml: str | None = None,
    session_id: str | None = None,
) -> TranslationError:
    """Create an error for XML parsing failures.

    Args:
        message: Error message
        original_xml: Original XML that failed to parse
        session_id: Session ID for tracking

    Returns:
        TranslationError with appropriate context
    """
    return TranslationError(
        message=message,
        tool_name="unknown",
        error_code=CompatibilityErrorCode.INVALID_XML_SYNTAX,
        original_xml=original_xml,
        session_id=session_id,
    )
