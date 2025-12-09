"""
Tool constants and categories for the application.

This module defines standardized lists of tool names used across various
reactors and security handlers to ensure consistency.
"""

from typing import Final


class ShellExecutionTools:
    """Tools that execute code or shell commands on the client side."""

    BASH: Final[str] = "bash"
    EXECUTE: Final[str] = "Execute"
    SHELL_TOOL: Final[str] = "ShellTool"
    EXEC_COMMAND: Final[str] = "exec_command"
    EXECUTE_COMMAND: Final[str] = "execute_command"
    RUN_SHELL_COMMAND: Final[str] = "run_shell_command"
    RUN_TERMINAL_COMMAND: Final[str] = "run_terminal_command"
    SHELL: Final[str] = "shell"
    LOCAL_SHELL: Final[str] = "local_shell"
    CONTAINER_EXEC: Final[str] = "container.exec"

    # Regex pattern for matching shell tool names
    PATTERN: Final[str] = (
        r"\bexecute\b|execute_command|run_shell_command|run_terminal_command|exec_command|\bshell\b|\bbash\b|local_shell|container\.exec"
    )

    @classmethod
    def get_all(cls) -> list[str]:
        """Get list of all shell execution tool names."""
        return [
            cls.BASH,
            cls.EXECUTE,
            cls.SHELL_TOOL,
            cls.EXEC_COMMAND,
            cls.EXECUTE_COMMAND,
            cls.RUN_SHELL_COMMAND,
            cls.RUN_TERMINAL_COMMAND,
            cls.SHELL,
            cls.LOCAL_SHELL,
            cls.CONTAINER_EXEC,
        ]


class FileEditingTools:
    """Tools that create, edit, or delete files."""

    WRITE_TO_FILE: Final[str] = "write_to_file"
    WRITE_FILE: Final[str] = "write_file"
    FS_WRITE: Final[str] = "fsWrite"
    REPLACE_IN_FILE: Final[str] = "replace_in_file"
    STR_REPLACE: Final[str] = "str_replace"
    STR_REPLACE_CAMEL: Final[str] = "strReplace"
    EDIT_FILE: Final[str] = "edit_file"
    PATCH_FILE: Final[str] = "patch_file"
    APPLY_DIFF: Final[str] = "apply_diff"
    APPLY_PATCH: Final[str] = "apply_patch"
    DELETE_FILE: Final[str] = "delete_file"
    DELETE_FILE_CAMEL: Final[str] = "deleteFile"
    REMOVE_FILE: Final[str] = "remove_file"
    CREATE_FILE: Final[str] = "create_file"
    MOVE_FILE: Final[str] = "move_file"
    RENAME_FILE: Final[str] = "rename_file"
    COPY_FILE: Final[str] = "copy_file"
    INSERT_CONTENT: Final[str] = "insert_content"
    SEARCH_AND_REPLACE: Final[str] = "search_and_replace"
    GENERATE_IMAGE: Final[str] = "generate_image"

    @classmethod
    def get_all_patterns(cls) -> list[str]:
        """Get regex patterns for all file editing tools."""
        return [
            r"write_to_file",
            r"write_file",
            r"fsWrite",
            r"replace_in_file",
            r"str_replace",
            r"strReplace",
            r"edit_file",
            r"patch_file",
            r"apply_diff",
            r"apply_patch",
            r"delete_file",
            r"deleteFile",
            r"remove_file",
            r"create_file",
            r"move_file",
            r"rename_file",
            r"copy_file",
            r"insert_content",
            r"search_and_replace",
            r"generate_image",
        ]
