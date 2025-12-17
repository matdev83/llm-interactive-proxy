"""
Droid/Antigravity path normalization fixup.

This fixup normalizes relative paths emitted by Droid/Factory agents to absolute
paths relative to the current working directory, preventing "absolute path required"
errors when the dedicated DroidAntigravityPathFixHandler is not active.
"""

from __future__ import annotations

import os
import re
from typing import Any

from src.core.common.logging_utils import get_logger

logger = get_logger(__name__)


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
        path, key = self._extract_path(arguments)
        if not path:
            return arguments, False

        # Check if path needs fixing
        if not self._needs_fix(path):
            return arguments, False

        # Fix the path
        fixed_path = self._fix_path(path)
        if fixed_path == path:
            return arguments, False

        # Update arguments
        new_args = dict(arguments)
        if key:
            new_args[key] = fixed_path
        else:
            # No key found, set file_path as default
            new_args["file_path"] = fixed_path

        return new_args, True

    def _extract_path(self, arguments: dict[str, Any]) -> tuple[str | None, str | None]:
        """Extract path value from arguments dict.

        Args:
            arguments: The arguments dict to search.

        Returns:
            Tuple of (path_value, key_name) or (None, None) if not found.
        """
        for key in self.PATH_KEYS:
            val = arguments.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip(), key
        return None, None

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
            Fixed absolute path including drive letter.
        """
        # Strip potential leading separators to ensure we append to CWD
        # instead of resolving to drive root
        cleaned_path = path.lstrip("/\\")

        # Join with CWD to get full path
        full_path = os.path.join(os.getcwd(), cleaned_path)

        # Normalize (resolves .. and separators)
        return os.path.abspath(full_path)
