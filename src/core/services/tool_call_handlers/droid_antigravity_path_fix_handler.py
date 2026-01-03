"""
Droid-Antigravity Path Fix Handler.

Internal debugging handler that fixes relative path formatting in tool calls
from Antigravity OAuth backend when used with the Droid agent.

This handler automatically converts relative paths like 'src/file.py' to
absolute Windows paths like '\\src\\file.py' to avoid round-trip errors.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallHandler,
    ToolCallContext,
    ToolCallReactionResult,
)

logger = logging.getLogger(__name__)


class DroidAntigravityPathFixHandler(IToolCallHandler):
    """Handler that fixes path formatting for Droid sessions.

    This is an internal debugging handler that activates only when:
    - User agent OR app title contains "droid" (case-insensitive)

    When activated, it transforms relative paths to absolute Windows paths:
    - Prepends backslash to paths not starting with \\ or /
    - Converts forward slashes to backslashes

    Example: 'src/connectors/base.py' → '\\src\\connectors\\base.py'
    """

    def __init__(self, enabled: bool = False) -> None:
        """Initialize the path fix handler.

        Args:
            enabled: Whether the handler is enabled (default: False)
        """
        self._enabled = enabled

    @property
    def name(self) -> str:
        return "droid_antigravity_path_fix_handler"

    @property
    def priority(self) -> int:
        # Medium priority - after dangerous commands but before most others
        return 50

    async def can_handle(self, context: ToolCallContext) -> bool:
        """Check if this handler should process the tool call.

        Returns True only if:
        1. Handler is enabled
        2. Agent contains "droid" or "factory" (case-insensitive)
           - "droid" is the agent name
           - "factory" is the company that builds Droid (factory-cli user agent)
        3. Tool arguments contain a path that needs fixing

        Args:
            context: The tool call context

        Returns:
            True if this handler can process the tool call
        """
        if not self._enabled:
            return False

        # Check agent name (from calling_agent or context)
        # Droid sends User-Agent: factory-cli/X.Y.Z so we also check for "factory"
        agent_name = context.calling_agent or ""
        agent_lower = agent_name.lower()
        if "droid" not in agent_lower and "factory" not in agent_lower:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DroidAntigravityPathFix: agent '%s' doesn't contain 'droid' or 'factory'",
                    agent_name,
                )
            return False

        # Check if there's a path that needs fixing
        path = self._extract_path(context.tool_arguments)
        if not path:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "DroidAntigravityPathFix: no path found in arguments %s",
                    context.tool_arguments,
                )
            return False

        # Only handle if the path needs fixing (is invalid/relative)
        needs_fix = self._needs_path_fix(path)
        if not needs_fix and logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "DroidAntigravityPathFix: path '%s' doesn't need fixing",
                path,
            )
        return needs_fix

    async def handle(self, context: ToolCallContext) -> ToolCallReactionResult:
        """Fix the path in tool arguments.

        Transforms relative paths to absolute Windows paths by:
        1. Prepending backslash if not already present
        2. Converting forward slashes to backslashes

        Args:
            context: The tool call context with arguments to modify

        Returns:
            ToolCallReactionResult with should_swallow=False (pass through)
        """
        if not self._enabled:
            return ToolCallReactionResult(should_swallow=False)

        path = self._extract_path(context.tool_arguments)
        if not path or not self._needs_path_fix(path):
            return ToolCallReactionResult(should_swallow=False)

        # Transform the path
        fixed_path = self._fix_path(path)

        # Update the arguments
        self._update_path(context.tool_arguments, fixed_path)

        logger.info(
            "Fixed path for Droid+Antigravity session %s: '%s' → '%s'",
            context.session_id,
            path,
            fixed_path,
        )

        # Don't swallow - let the tool call execute with fixed path
        return ToolCallReactionResult(
            should_swallow=False,
            metadata={
                "handler": self.name,
                "original_path": path,
                "fixed_path": fixed_path,
                "source": "droid_antigravity_path_fix",
            },
        )

    def _extract_path(self, arguments: Any) -> str | None:
        """Extract the path from tool arguments.

        Supports:
        - Dict with 'file_path', 'path', 'AbsolutePath', or similar keys
        - String arguments (treated as the path itself)

        Args:
            arguments: Tool call arguments

        Returns:
            Extracted path or None if not found
        """
        if isinstance(arguments, str):
            return arguments.strip() if arguments.strip() else None

        if isinstance(arguments, dict):
            # Try common path parameter names
            for key in ["file_path", "path", "AbsolutePath", "filepath", "File"]:
                value = arguments.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    def _needs_path_fix(self, path: str) -> bool:
        """Check if a path needs fixing.

        A path needs fixing if:
        1. It is relative (e.g. "src/file.py")
        2. It is absolute but lacks drive letter on Windows (e.g. "/src/file.py")

        Args:
            path: The path to check

        Returns:
            True if the path needs fixing
        """
        if not path:
            return False

        # If it has a drive letter, it's a full Windows path
        if re.match(r"^[a-zA-Z]:", path):
            return False

        # If it's a UNC path (starts with \\), assume it's valid
        return not path.startswith("\\\\")

    def _fix_path(self, path: str) -> str:
        """Fix a path to be an absolute Windows path relative to CWD.

        Transformation:
        1. Strip leading slashes/backslashes
        2. Join with current working directory
        3. Normalize separators

        Args:
            path: The path to fix

        Returns:
            Fixed absolute path including drive letter, or original path if
            traversal out of CWD is detected.
        """
        import os

        # Strip potential leading separators to ensure we append to CWD
        # instead of resolving to drive root
        cleaned_path = path.lstrip("/\\")

        # Join with CWD to get full path
        cwd = os.getcwd()
        full_path = os.path.join(cwd, cleaned_path)

        # Normalize (resolves .. and separators)
        resolved_path = os.path.abspath(full_path)

        # Security check: ensure resolved path is within CWD
        # We use os.path.commonpath to handle paths correctly
        try:
            if os.path.commonpath([cwd, resolved_path]) != cwd:
                logger.warning(
                    "DroidAntigravityPathFixHandler: Path traversal detected. "
                    "Resolved path '%s' is outside CWD '%s'. Returning original path.",
                    resolved_path,
                    cwd,
                )
                return path
        except ValueError:
            # Can happen if paths are on different drives
            logger.warning(
                "DroidAntigravityPathFixHandler: Path traversal detected (drive mismatch). "
                "Returning original path.",
                exc_info=True,
            )
            return path

        return resolved_path

    def _update_path(self, arguments: Any, fixed_path: str) -> None:
        """Update the path in tool arguments.

        Modifies the arguments in-place.

        Args:
            arguments: Tool call arguments to modify
            fixed_path: The fixed path to set
        """
        if isinstance(arguments, dict):
            # Update the path in the dict
            for key in ["file_path", "path", "AbsolutePath", "filepath", "File"]:
                if key in arguments:
                    arguments[key] = fixed_path
                    return

            # If no known key found, try to set file_path as default
            arguments["file_path"] = fixed_path
