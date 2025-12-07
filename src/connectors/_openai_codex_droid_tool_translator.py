"""Droid to Codex tool translator.

Translates Factory Droid tool calls to OpenAI Codex format.

Tool Mapping:
    Droid Tool       -> Codex Tool         Notes
    ---------------------------------------------------------------------------
    Read             -> read_file          Map file_path->path, offset/limit->start_line/end_line
    LS               -> list_dir           Map directory_path->path
    Execute          -> shell              Convert command string to array
    Edit             -> apply_patch        Generate unified diff from old_str/new_str
    Grep             -> grep_files         Direct parameter mapping
    Glob             -> grep_files         Use --files mode with patterns
    Create           -> apply_patch        Create as "Add File" patch
    TodoWrite        -> __proxy_*          Handle proxy-side (no Codex equivalent)
    WebSearch        -> __proxy_*          Handle proxy-side (no Codex equivalent)
    FetchUrl         -> __proxy_*          Handle proxy-side (no Codex equivalent)
    ExitSpecMode     -> __proxy_*          Handle proxy-side (conversation control)
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of a tool call translation."""

    codex_tool_name: str
    codex_arguments: dict[str, Any]
    is_proxy_side: bool = False
    original_tool_name: str = ""


class DroidToolTranslator:
    """Translates Factory Droid tool calls to Codex format.

    This class handles the bidirectional translation between:
    - Factory Droid's tool format (OpenAI function-calling style)
    - OpenAI Codex's native tool format

    It also identifies tools that should be handled proxy-side
    (e.g., TodoWrite, WebSearch) when there's no Codex equivalent.
    """

    # Tools that map directly to Codex native tools (Droid -> Codex)
    CODEX_NATIVE_TOOLS = {
        "Read": "read_file",
        "LS": "list_dir",
        "Execute": "shell",
        "Grep": "grep_files",
        "Edit": "apply_patch",
        "Create": "apply_patch",
        "Glob": "grep_files",
    }

    # Reverse mapping: Codex tool names -> Droid tool names
    # Used to translate tool calls FROM Codex backend responses TO Droid client
    CODEX_TO_DROID_TOOLS = {
        "read_file": "Read",
        "list_dir": "LS",
        "shell": "Execute",
        "grep_files": "Grep",
        "apply_patch": "Edit",
        "view_image": "Read",  # Map view_image to Read as fallback
    }

    # Tools that should be handled proxy-side
    PROXY_SIDE_TOOLS = {
        "TodoWrite": "__proxy_todo_write",
        "WebSearch": "__proxy_web_search",
        "FetchUrl": "__proxy_fetch_url",
        "ExitSpecMode": "__proxy_exit_spec_mode",
    }

    def translate_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate a Droid tool call to Codex format.

        Args:
            tool_name: The Droid tool name (e.g., "Read", "Execute")
            arguments: The tool arguments from Droid

        Returns:
            Tuple of (codex_tool_name, codex_arguments)

        Raises:
            ValueError: If the tool is not recognized
        """
        # Check if it's a native Codex tool
        if tool_name in self.CODEX_NATIVE_TOOLS:
            translator_method = getattr(self, f"_translate_{tool_name.lower()}", None)
            if translator_method:
                return cast(tuple[str, dict[str, Any]], translator_method(arguments))
            # Fallback for tools without specific translators
            codex_name = self.CODEX_NATIVE_TOOLS[tool_name]
            return codex_name, arguments

        # Check if it's a proxy-side tool
        if tool_name in self.PROXY_SIDE_TOOLS:
            return self.PROXY_SIDE_TOOLS[tool_name], arguments

        # Unknown tool
        logger.warning(f"Unknown Droid tool: {tool_name}")
        raise ValueError(f"Unknown Droid tool: {tool_name}")

    def translate_codex_to_droid(
        self, codex_tool_name: str, codex_arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate a Codex tool call back to Droid format.

        Used when processing backend responses to translate tool calls
        from Codex format to Droid format.

        Args:
            codex_tool_name: The Codex tool name (e.g., "shell", "read_file")
            codex_arguments: The tool arguments from Codex

        Returns:
            Tuple of (droid_tool_name, droid_arguments)
        """
        droid_tool_name = self.CODEX_TO_DROID_TOOLS.get(codex_tool_name)
        if not droid_tool_name:
            # Unknown Codex tool - pass through as-is
            logger.debug(
                "Unknown Codex tool '%s', passing through without translation",
                codex_tool_name,
            )
            return codex_tool_name, codex_arguments

        # Get reverse translator if exists
        translator_method = getattr(self, f"_reverse_translate_{codex_tool_name}", None)
        if translator_method:
            return cast(tuple[str, dict[str, Any]], translator_method(codex_arguments))

        # Default: just map the name, keep arguments as-is
        return droid_tool_name, codex_arguments

    def _reverse_translate_read_file(
        self, codex_args: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate read_file back to Read.

        Codex read_file:
            - path: File path
            - start_line: Optional start line
            - end_line: Optional end line

        Droid Read:
            - file_path: Absolute path to file
            - offset: Optional line offset
            - limit: Optional number of lines
        """
        droid_args: dict[str, Any] = {
            "file_path": codex_args.get("path") or codex_args.get("file_path", ""),
        }

        start_line = codex_args.get("start_line")
        end_line = codex_args.get("end_line")

        if start_line is not None:
            droid_args["offset"] = start_line

        if end_line is not None and start_line is not None:
            droid_args["limit"] = end_line - start_line
        elif end_line is not None:
            droid_args["limit"] = end_line

        return "Read", droid_args

    def _reverse_translate_shell(
        self, codex_args: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate shell back to Execute.

        Codex shell:
            - command: Array of command parts

        Droid Execute:
            - command: Full command string
        """
        command = codex_args.get("command", [])
        if isinstance(command, list):
            # Join command parts with proper quoting
            command_str = shlex.join(command)
        else:
            command_str = str(command)

        return "Execute", {"command": command_str}

    def _reverse_translate_list_dir(
        self, codex_args: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate list_dir back to LS.

        Codex list_dir:
            - path: Directory path

        Droid LS:
            - directory_path: Directory path
        """
        return "LS", {"directory_path": codex_args.get("path", ".")}

    def _reverse_translate_grep_files(
        self, codex_args: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate grep_files back to Grep.

        Codex grep_files:
            - pattern: Search pattern
            - path: Optional search path
            - options: Optional array of grep options

        Droid Grep:
            - pattern: Search pattern
            - path: Optional path
            - type: Optional file type filter
            - glob: Optional glob pattern
        """
        droid_args: dict[str, Any] = {
            "pattern": codex_args.get("pattern", ""),
        }

        if "path" in codex_args:
            droid_args["path"] = codex_args["path"]

        return "Grep", droid_args

    def _reverse_translate_apply_patch(
        self, codex_args: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate apply_patch back to Edit.

        This is a complex translation - Codex uses diff format while
        Droid uses old_str/new_str format. For now, we pass through
        the patch content and let the client handle it.

        Codex apply_patch:
            - file_path: Target file
            - content: Diff/patch content
            - is_new_file: Whether creating new file

        Droid Edit:
            - file_path: Target file
            - old_str: String to find
            - new_str: Replacement string
        """
        file_path = codex_args.get("file_path", "")

        # If it's a new file creation, map to Create tool behavior
        if codex_args.get("is_new_file"):
            return "Create", {
                "file_path": file_path,
                "content": codex_args.get("content", ""),
            }

        # For edits, we pass through as-is since the diff format
        # is complex to reverse-engineer
        return "Edit", {
            "file_path": file_path,
            "old_str": "",  # Placeholder - actual diff handling needed
            "new_str": codex_args.get("content", ""),
        }

    def _translate_read(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate Read tool to read_file.

        Droid Read:
            - file_path: Absolute path to file
            - offset: Optional line offset (1-based)
            - limit: Optional number of lines to read

        Codex read_file:
            - path: File path
            - start_line: Optional start line
            - end_line: Optional end line
        """
        codex_args: dict[str, Any] = {
            "path": arguments["file_path"],
        }

        offset = arguments.get("offset")
        limit = arguments.get("limit")

        if offset is not None:
            codex_args["start_line"] = offset

        if limit is not None:
            if offset is not None:
                codex_args["end_line"] = offset + limit
            else:
                # If only limit is specified, read from start
                codex_args["end_line"] = limit

        return "read_file", codex_args

    def _translate_ls(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate LS tool to list_dir.

        Droid LS:
            - directory_path: Optional directory path (defaults to cwd)
            - ignorePatterns: Optional patterns to ignore

        Codex list_dir:
            - path: Directory path
            - depth: Optional recursion depth
        """
        codex_args: dict[str, Any] = {}

        codex_args["path"] = arguments.get("directory_path", ".")

        # Note: ignorePatterns is not directly supported by Codex list_dir
        # It could be handled proxy-side if needed

        return "list_dir", codex_args

    def _translate_execute(
        self, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate Execute tool to shell.

        Droid Execute:
            - command: Command string
            - timeout: Optional timeout in seconds
            - cwd: Optional working directory

        Codex shell:
            - command: Command as array
            - workdir: Optional working directory
        """
        command_str = arguments.get("command", "")

        # Split command string into array using shlex
        try:
            command_array = shlex.split(command_str)
        except ValueError:
            # If shlex fails, fall back to simple split
            command_array = command_str.split()

        codex_args: dict[str, Any] = {
            "command": command_array,
        }

        if "cwd" in arguments:
            codex_args["workdir"] = arguments["cwd"]

        # Note: timeout is not directly supported by Codex shell
        # It should be handled by the executor

        return "shell", codex_args

    def _translate_grep(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate Grep tool to grep_files.

        Droid Grep:
            - pattern: Search pattern
            - path: Optional search path
            - type: Optional file type filter
            - glob: Optional glob pattern
            - include: Optional include patterns
            - exclude: Optional exclude patterns

        Codex grep_files:
            - pattern: Search pattern
            - path: Optional search path
            - include: Optional include patterns
            - exclude: Optional exclude patterns
        """
        codex_args: dict[str, Any] = {
            "pattern": arguments["pattern"],
        }

        if "path" in arguments:
            codex_args["path"] = arguments["path"]

        if "include" in arguments:
            codex_args["include"] = arguments["include"]

        if "exclude" in arguments:
            codex_args["exclude"] = arguments["exclude"]

        # Handle type -> include conversion
        if "type" in arguments and "include" not in arguments:
            file_type = arguments["type"]
            codex_args["include"] = f"*.{file_type}"

        # Handle glob -> include conversion
        if "glob" in arguments and "include" not in arguments:
            codex_args["include"] = arguments["glob"]

        return "grep_files", codex_args

    def _translate_glob(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate Glob tool to grep_files (files-only mode).

        Droid Glob:
            - patterns: Array of glob patterns
            - excludePatterns: Optional exclude patterns

        Codex grep_files:
            - pattern: Empty string (files-only mode)
            - include: Glob patterns
            - exclude: Exclude patterns
        """
        patterns = arguments.get("patterns", [])

        codex_args: dict[str, Any] = {
            "pattern": "",  # Empty pattern for files-only mode
            "include": ",".join(patterns) if isinstance(patterns, list) else patterns,
        }

        if "excludePatterns" in arguments:
            exclude = arguments["excludePatterns"]
            codex_args["exclude"] = (
                ",".join(exclude) if isinstance(exclude, list) else exclude
            )

        return "grep_files", codex_args

    def _translate_edit(self, arguments: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Translate Edit tool to apply_patch.

        Droid Edit:
            - file_path: Path to file
            - old_str: Text to find
            - new_str: Replacement text
            - change_all: Optional flag to replace all occurrences

        Codex apply_patch:
            - Uses unified diff format (grammar-based)
        """
        # For MVP, we'll generate a simple patch format
        # Full unified diff generation would require reading the file
        codex_args: dict[str, Any] = {
            "file_path": arguments["file_path"],
            "old_str": arguments["old_str"],
            "new_str": arguments["new_str"],
            "change_all": arguments.get("change_all", False),
        }

        return "apply_patch", codex_args

    def _translate_create(
        self, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Translate Create tool to apply_patch.

        Droid Create:
            - file_path: Path for new file
            - content: File content

        Codex apply_patch:
            - Uses "Add File" grammar format
        """
        codex_args: dict[str, Any] = {
            "file_path": arguments["file_path"],
            "content": arguments["content"],
            "is_new_file": True,
        }

        return "apply_patch", codex_args

    def format_result(self, codex_result: dict[str, Any], _original_tool: str) -> str:
        """Format a Codex result back to Droid format.

        Droid expects tool results as plain strings:
        - Success: The output content
        - Error: "Error: <message>"

        Args:
            codex_result: The result from Codex tool execution
            _original_tool: The original Droid tool name (currently unused)

        Returns:
            Formatted string result for Droid
        """
        # Check for error
        if "error" in codex_result:
            return f"Error: {codex_result['error']}"

        # Extract output based on result structure
        if "output" in codex_result:
            return str(codex_result["output"])

        if "content" in codex_result:
            return str(codex_result["content"])

        if "result" in codex_result:
            return str(codex_result["result"])

        # Fallback to string representation
        return str(codex_result)
