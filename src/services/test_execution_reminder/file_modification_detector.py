"""File modification detection for test execution reminder system."""

from __future__ import annotations


class FileModificationDetector:
    """Detects tool calls that modify files.

    This detector identifies file modification operations by matching tool names
    against a comprehensive set of known file modification patterns. It supports
    case-insensitive matching with normalization to handle variations in tool
    naming conventions (underscores, slashes, etc.).
    """

    # Tool names that indicate file modifications
    FILE_MODIFICATION_TOOLS = {
        "write_file",
        "replace_lines",
        "replace_in_file",
        "write_to_file",
        "apply_diff",
        "apply_patch",
        "patch_file",
        "str_replace",
        "multiedit",
        "fs/write_text_file",
        "insert_content",
        "patch",
        "patchfile",
        "strreplace",
        "fswrite",
        "fs_write",
    }

    @classmethod
    def is_file_modification(cls, tool_name: str) -> bool:
        """Check if tool name indicates file modification.

        This method performs case-insensitive matching with normalization,
        removing underscores and slashes to handle various tool name formats.

        Args:
            tool_name: The name of the tool to check

        Returns:
            True if the tool modifies files, False otherwise

        Examples:
            >>> FileModificationDetector.is_file_modification("write_file")
            True
            >>> FileModificationDetector.is_file_modification("WriteFile")
            True
            >>> FileModificationDetector.is_file_modification("fs/write_text_file")
            True
            >>> FileModificationDetector.is_file_modification("read_file")
            False
        """
        if not tool_name:
            return False

        # Normalize the input tool name: lowercase, remove underscores and slashes
        normalized_input = tool_name.lower().replace("_", "").replace("/", "")

        # Check against all patterns with the same normalization
        for pattern in cls.FILE_MODIFICATION_TOOLS:
            normalized_pattern = pattern.replace("_", "").replace("/", "")
            if normalized_input == normalized_pattern:
                return True

        return False
