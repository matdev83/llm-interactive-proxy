"""ErrorHandler - User-friendly error message formatting for CLI.

This module provides the ErrorHandler class that classifies errors and formats
user-friendly messages with actionable guidance for different error types.

Requirements satisfied:
- 5.1: ErrorHandler formats user-friendly messages with actionable guidance
- 5.2: OAuth token expiration provides specific re-authentication instructions
- 5.3: API key errors list required environment variables
- 5.4: Unknown errors provide generic troubleshooting guidance
- 5.5: Error messages write to stderr with consistent formatting

Location: src/core/cli_support/error_handler.py
"""

from __future__ import annotations

import re
import sys
from enum import Enum
from typing import TextIO


class ErrorType(Enum):
    """Types of errors for specialized handling.

    Each error type has a corresponding format method in ErrorHandler
    that provides specific guidance for that type of error.
    """

    OAUTH_EXPIRED = "oauth_expired"
    OAUTH_MISSING = "oauth_missing"
    OAUTH_INVALID = "oauth_invalid"
    API_KEY_MISSING = "api_key_missing"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    PORT_IN_USE = "port_in_use"
    UNKNOWN = "unknown"


class ErrorHandler:
    """Formats user-friendly error messages with actionable guidance.

    This service classifies errors into categories and provides specialized
    message formatting for each category to help users resolve issues.

    Attributes:
        _output: The output stream for error messages (defaults to stderr).

    Example:
        >>> handler = ErrorHandler()
        >>> error_type = handler.classify_error("Token expired for gemini")
        >>> handler.handle_build_error("Stage 'backends' validation error: Token expired")
    """

    # Patterns for error classification
    _OAUTH_EXPIRED_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"token\s+expired", re.IGNORECASE),
        re.compile(r"token\s+has\s+expired", re.IGNORECASE),
        re.compile(r"access\s+token\s+expired", re.IGNORECASE),
        re.compile(r"refresh\s+token\s+expired", re.IGNORECASE),
    ]

    _OAUTH_MISSING_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"oauth_credentials_unavailable", re.IGNORECASE),
        re.compile(r"credentials\s+file\s+not\s+found", re.IGNORECASE),
        re.compile(r"failed\s+to\s+load\s+credentials", re.IGNORECASE),
        re.compile(r"oauth\s+credentials\s+not\s+found", re.IGNORECASE),
    ]

    _OAUTH_INVALID_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"oauth_credentials_invalid", re.IGNORECASE),
        re.compile(r"invalid\s+credentials", re.IGNORECASE),
        re.compile(r"credentials\s+are\s+corrupted", re.IGNORECASE),
    ]

    _API_KEY_MISSING_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"api_key\s+is\s+required", re.IGNORECASE),
        re.compile(r"api\s+key\s+is\s+required", re.IGNORECASE),
        re.compile(r"missing\s+api\s+key", re.IGNORECASE),
    ]

    _PORT_IN_USE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"port\s+\d+\s+is\s+already\s+in\s+use", re.IGNORECASE),
        re.compile(r"address\s+already\s+in\s+use", re.IGNORECASE),
        re.compile(r"port\s+in\s+use", re.IGNORECASE),
    ]

    _BACKEND_VALIDATION_PATTERN: re.Pattern[str] = re.compile(
        r"Stage 'backends' validation error", re.IGNORECASE
    )

    def __init__(self, output: TextIO | None = None) -> None:
        """Initialize ErrorHandler with optional output stream.

        Args:
            output: Output stream for error messages. Defaults to sys.stderr.
        """
        self._output: TextIO = output if output is not None else sys.stderr

    def classify_error(self, error_msg: str) -> ErrorType:
        """Classify error message into error type.

        Examines the error message for known patterns and returns the
        corresponding ErrorType. Returns UNKNOWN if no pattern matches.

        Args:
            error_msg: The error message to classify.

        Returns:
            The ErrorType classification for the error.
        """
        # Check OAuth expired patterns first (most specific)
        for pattern in self._OAUTH_EXPIRED_PATTERNS:
            if pattern.search(error_msg):
                return ErrorType.OAUTH_EXPIRED

        # Check OAuth invalid patterns
        for pattern in self._OAUTH_INVALID_PATTERNS:
            if pattern.search(error_msg):
                return ErrorType.OAUTH_INVALID

        # Check OAuth missing patterns
        for pattern in self._OAUTH_MISSING_PATTERNS:
            if pattern.search(error_msg):
                return ErrorType.OAUTH_MISSING

        # Check API key missing patterns
        for pattern in self._API_KEY_MISSING_PATTERNS:
            if pattern.search(error_msg):
                return ErrorType.API_KEY_MISSING

        # Check port in use patterns
        for pattern in self._PORT_IN_USE_PATTERNS:
            if pattern.search(error_msg):
                return ErrorType.PORT_IN_USE

        # Check for generic backend validation error
        if self._BACKEND_VALIDATION_PATTERN.search(error_msg):
            return ErrorType.BACKEND_UNAVAILABLE

        return ErrorType.UNKNOWN

    def handle_build_error(self, error_msg: str) -> None:
        """Handle application build errors with user-friendly messages.

        Classifies the error and writes a formatted message to the output
        stream with actionable guidance specific to the error type.

        Args:
            error_msg: The error message from the application build failure.
        """
        error_type = self.classify_error(error_msg)

        # Write header
        self._output.write("\n" + "=" * 60 + "\n")
        self._output.write("ERROR: Failed to start LLM Interactive Proxy\n")
        self._output.write("=" * 60 + "\n")

        # Check if this is a backends validation error
        if self._BACKEND_VALIDATION_PATTERN.search(error_msg):
            self._output.write(
                "\nThe application failed to start because no working backends were found.\n"
            )
            self._output.write("\nThis usually means one of the following:\n")
            self._output.write("  1. OAuth tokens have expired (most common)\n")
            self._output.write("  2. API keys are missing or invalid\n")
            self._output.write("  3. Network connectivity issues\n")

        # Format based on error type
        if error_type == ErrorType.OAUTH_EXPIRED:
            self._output.write(self.format_oauth_expired_message(error_msg))
        elif error_type == ErrorType.OAUTH_MISSING:
            self._output.write(self._format_oauth_missing_message(error_msg))
        elif error_type == ErrorType.OAUTH_INVALID:
            self._output.write(self._format_oauth_invalid_message(error_msg))
        elif error_type == ErrorType.API_KEY_MISSING:
            self._output.write(self.format_api_key_missing_message())
        elif error_type == ErrorType.PORT_IN_USE:
            self._output.write(self._format_port_in_use_message(error_msg))
        elif error_type == ErrorType.BACKEND_UNAVAILABLE:
            self._output.write(self._format_backend_unavailable_message(error_msg))
        else:
            self._output.write(self._format_unknown_message(error_msg))

        # Write footer
        self._output.write(
            "\nFor more help, see the documentation or check your configuration.\n"
        )
        self._output.write("=" * 60 + "\n")

    def handle_exception(self, exc: BaseException) -> None:
        """Handle an unexpected exception with consistent formatting."""
        message = str(exc) or exc.__class__.__name__
        self.handle_build_error(message)

    def format_oauth_expired_message(self, error_msg: str) -> str:
        """Format message for OAuth token expiration.

        Provides specific re-authentication instructions based on the
        backend mentioned in the error message.

        Args:
            error_msg: The error message containing backend information.

        Returns:
            Formatted message with re-authentication instructions.
        """
        lines: list[str] = []
        lines.append("\nDETECTED ISSUE: OAuth token has expired\n")
        lines.append("\nTo fix this:\n")

        if "gemini" in error_msg.lower():
            lines.append("  - Run: gemini auth\n")
            lines.append("  - Follow the authentication flow in your browser\n")
        elif "qwen" in error_msg.lower():
            lines.append("  - Run: qwen auth\n")
            lines.append("  - Follow the authentication flow in your browser\n")
        elif "anthropic" in error_msg.lower():
            lines.append("  - Re-authenticate with Claude Code\n")
            lines.append("  - Or authenticate with the Anthropic OAuth client\n")
        elif "openai" in error_msg.lower():
            lines.append("  - Run: codex login\n")
            lines.append("  - Follow the authentication flow in your browser\n")
        else:
            lines.append("  - Re-authenticate with the appropriate OAuth provider\n")
            lines.append("  - For Gemini: run 'gemini auth'\n")
            lines.append("  - For Qwen: run 'qwen auth'\n")
            lines.append("  - For OpenAI: run 'codex login'\n")
            lines.append("  - For Anthropic: authenticate with Claude Code\n")
        lines.append("  - Then try starting the proxy again\n")

        return "".join(lines)

    def _format_oauth_missing_message(self, error_msg: str) -> str:
        """Format message for missing OAuth credentials.

        Args:
            error_msg: The error message containing backend information.

        Returns:
            Formatted message with instructions for obtaining credentials.
        """
        lines: list[str] = []
        lines.append("\nDETECTED ISSUE: OAuth credentials not found\n")
        lines.append("\nTo fix this:\n")

        if "anthropic" in error_msg.lower():
            lines.append(
                "  - Authenticate using Claude Code or similar Anthropic OAuth client\n"
            )
            lines.append("  - Or provide a valid oauth_creds.json file\n")
            lines.append("  - Default location: ~/.anthropic/oauth_credentials.json\n")
        elif "openai" in error_msg.lower():
            lines.append("  - Run: codex login\n")
            lines.append("  - Or provide a valid auth.json file\n")
            lines.append("  - Default location: ~/.codex/auth.json\n")
        elif "gemini" in error_msg.lower():
            lines.append("  - Run: gemini auth\n")
            lines.append("  - This will create ~/.gemini/oauth_creds.json\n")
        elif "qwen" in error_msg.lower():
            lines.append("  - Run: qwen auth\n")
            lines.append("  - This will create ~/.qwen/oauth_creds.txt\n")
        else:
            lines.append("  - Authenticate with the appropriate OAuth provider\n")
            lines.append("  - For Gemini: run 'gemini auth'\n")
            lines.append("  - For Qwen: run 'qwen auth'\n")
            lines.append("  - For OpenAI: run 'codex login'\n")
            lines.append("  - For Anthropic: use Claude Code or similar OAuth client\n")

        return "".join(lines)

    def _format_oauth_invalid_message(self, error_msg: str) -> str:
        """Format message for invalid OAuth credentials.

        Args:
            error_msg: The error message containing backend information.

        Returns:
            Formatted message with instructions for refreshing credentials.
        """
        lines: list[str] = []
        lines.append("\nDETECTED ISSUE: OAuth credentials are invalid or corrupted\n")
        lines.append("\nTo fix this:\n")
        lines.append("  - Re-authenticate to refresh your credentials\n")
        lines.append("  - For Gemini: run 'gemini auth'\n")
        lines.append("  - For Qwen: run 'qwen auth'\n")
        lines.append("  - For OpenAI: run 'codex login'\n")
        lines.append("  - For Anthropic: re-authenticate with Claude Code\n")

        return "".join(lines)

    def format_api_key_missing_message(self) -> str:
        """Format message for missing API keys.

        Lists all required environment variables and suggests
        OAuth-based alternatives.

        Returns:
            Formatted message with environment variable instructions.
        """
        lines: list[str] = []
        lines.append("\nDETECTED ISSUE: Missing API keys\n")
        lines.append("\nTo fix this:\n")
        lines.append("  - Set the required environment variables:\n")
        lines.append("    * OPENROUTER_API_KEY for OpenRouter\n")
        lines.append("    * GEMINI_API_KEY for Gemini\n")
        lines.append("    * ANTHROPIC_API_KEY for Anthropic\n")
        lines.append("    * ZAI_API_KEY for ZAI\n")
        lines.append("  - Or configure a different backend with --default-backend\n")
        lines.append("  - Or use OAuth-based backends:\n")
        lines.append("    * gemini-oauth-plan (uses gemini CLI auth for paid tier)\n")
        lines.append("    * gemini-oauth-free (uses gemini CLI auth for free tier)\n")
        lines.append("    * qwen-oauth (uses qwen CLI auth)\n")
        lines.append("    * anthropic-oauth (uses Claude Code auth)\n")
        lines.append("    * openai-codex (uses codex CLI auth)\n")

        return "".join(lines)

    def _format_port_in_use_message(self, error_msg: str) -> str:
        """Format message for port in use errors.

        Args:
            error_msg: The error message containing port information.

        Returns:
            Formatted message with port usage instructions.
        """
        lines: list[str] = []
        lines.append("\nDETECTED ISSUE: Port already in use\n")
        lines.append("\nTo fix this:\n")
        lines.append("  - Use a different port with --port <number>\n")
        lines.append("  - Or stop the process using the current port\n")
        lines.append("  - Check for running proxy instances\n")

        return "".join(lines)

    def _format_backend_unavailable_message(self, error_msg: str) -> str:
        """Format message for generic backend unavailability.

        Args:
            error_msg: The error message.

        Returns:
            Formatted message with generic troubleshooting guidance.
        """
        lines: list[str] = []
        lines.append("\nTo fix this:\n")
        lines.append("  - Check your internet connection\n")
        lines.append("  - Verify your API keys are valid\n")
        lines.append("  - Try refreshing OAuth tokens:\n")
        lines.append("    * For Gemini: gemini auth\n")
        lines.append("    * For Qwen: qwen auth\n")
        lines.append("    * For OpenAI: codex login\n")
        lines.append("    * For Anthropic: re-authenticate with Claude Code\n")
        lines.append("  - Check the logs above for specific error details\n")

        return "".join(lines)

    def _format_unknown_message(self, error_msg: str) -> str:
        """Format message for unknown errors.

        Args:
            error_msg: The error message.

        Returns:
            Formatted message with generic troubleshooting guidance.
        """
        lines: list[str] = []
        lines.append(f"\nUnexpected error during startup: {error_msg}\n")
        lines.append("\nPlease check the logs above for more details.\n")

        return "".join(lines)
