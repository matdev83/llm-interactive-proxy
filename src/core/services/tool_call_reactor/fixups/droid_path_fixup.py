"""
Droid/Antigravity path normalization fixup.

This fixup normalizes relative paths emitted by Droid/Factory agents to absolute
paths relative to the current working directory, preventing "absolute path required"
errors when the dedicated DroidAntigravityPathFixHandler is not active.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, NamedTuple

from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)


class PathExtractionResult(NamedTuple):
    """Result of extracting a path from tool arguments."""

    path: str | None
    """The extracted path value, or None if not found."""

    key: str | None
    """The key name that contained the path, or None if not found."""


class DroidPathFixup:
    """Fixup for normalizing relative paths from Droid/Factory agents.

    This fixup applies to any backend when the calling agent is "droid" or
    "factory" (Droid sends User-Agent: factory-cli/X.Y.Z). It normalizes
    relative paths to absolute paths relative to CWD.

    The fixup handles:
    - String arguments containing paths
    - Dict arguments with path keys: file_path, path, AbsolutePath, filepath, File
    """

    # Path keys to check in dict arguments
    PATH_KEYS = ["file_path", "path", "AbsolutePath", "filepath", "File"]

    def should_apply(self, calling_agent: str | None) -> bool:
        """Check if this fixup should apply based on calling agent.

        Args:
            calling_agent: The User-Agent or agent identifier.

        Returns:
            True if the agent contains "droid" or "factory" (case-insensitive).
        """
        if not calling_agent:
            return False
        agent = calling_agent.lower()
        return "droid" in agent or "factory" in agent

    def apply(
        self, arguments: dict[str, Any], calling_agent: str | None
    ) -> tuple[dict[str, Any], bool]:
        """Apply path normalization fixup.

        Args:
            arguments: The normalized arguments dict to fix.
            calling_agent: The calling agent identifier.

        Returns:
            Tuple of (possibly_modified_arguments, was_modified).
        """
        if not self.should_apply(calling_agent):
            return arguments, False

        # Extract path from arguments
        result = self._extract_path(arguments)
        if not result.path:
            return arguments, False

        # Check if path needs fixing
        if not self._needs_fix(result.path):
            return arguments, False

        # Fix the path
        fixed_path = self._fix_path(result.path)
        if fixed_path == result.path:
            return arguments, False

        # Update arguments
        new_args = dict(arguments)
        if result.key:
            new_args[result.key] = fixed_path
        else:
            # No key found, set file_path as default
            new_args["file_path"] = fixed_path

        return new_args, True

    def _extract_path(self, arguments: dict[str, Any]) -> PathExtractionResult:
        """Extract path value from arguments dict.

        Args:
            arguments: The arguments dict to search.

        Returns:
            PathExtractionResult with path value and key name, or (None, None) if not found.
        """
        for key in self.PATH_KEYS:
            val = arguments.get(key)
            if isinstance(val, str) and val.strip():
                return PathExtractionResult(path=val.strip(), key=key)
        return PathExtractionResult(path=None, key=None)

    def _needs_fix(self, path: str) -> bool:
        """Check if a path needs fixing.

        A path needs fixing if it's relative (not absolute). Absolute paths
        include Windows drive letters (C:) and UNC paths (\\).

        Args:
            path: The path to check.

        Returns:
            True if the path is relative and needs fixing.
        """
        # If it has a drive letter, it's a full Windows path
        if re.match(r"^[a-zA-Z]:", path):
            return False

        # If it's a UNC path (starts with \\), assume it's valid
        # Otherwise, it's relative and needs fixing
        return not path.startswith("\\\\")

    def _fix_path(self, path: str) -> str:
        """Fix a path to be absolute relative to CWD.

        Transformation:
        1. Strip leading separators to ensure we append to CWD
        2. Join with current working directory
        3. Normalize to absolute path

        Args:
            path: The relative path to fix.

        Returns:
            Fixed absolute path including drive letter, or original path if
            traversal out of CWD is detected.
        """
        # Strip potential leading separators to ensure we append to CWD
        # instead of resolving to drive root
        cleaned_path = path.lstrip("/\\")

        # Join with CWD to get full path
        cwd = os.getcwd()
        full_path = os.path.join(cwd, cleaned_path)

        # Normalize (resolves .. and separators)
        resolved_path = os.path.abspath(full_path)

        # Security check: ensure resolved path is within CWD
        try:
            if os.path.commonpath([cwd, resolved_path]) != cwd:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "DroidPathFixup: Path traversal detected. "
                        "Resolved path '%s' is outside CWD '%s'. Returning original path.",
                        resolved_path,
                        cwd,
                    )
                return path
        except ValueError:
            # Can happen if paths are on different drives
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    "DroidPathFixup: Path traversal detected (drive mismatch). "
                    "Returning original path.",
                    exc_info=True,
                )
            return path

        return resolved_path
