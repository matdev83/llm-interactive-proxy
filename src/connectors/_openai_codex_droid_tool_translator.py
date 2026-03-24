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
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TranslationResult:
    """Result of a tool call translation."""

    codex_tool_name: str
    codex_arguments: dict[str, Any]
    is_proxy_side: bool = False
    original_tool_name: str = ""

    def __iter__(self):
        """Allow unpacking for backward compatibility."""
        yield self.codex_tool_name
        yield self.codex_arguments


@dataclass
class ReverseTranslationResult:
    """Result of a Codex tool call translation back to Droid format."""

    droid_tool_name: str
    droid_arguments: dict[str, Any]

    def __iter__(self):
        """Allow unpacking for backward compatibility."""
        yield self.droid_tool_name
        yield self.droid_arguments


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
        "bash": "Execute",
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
    ) -> TranslationResult:
        """Translate a Droid tool call to Codex format.

        Args:
            tool_name: The Droid tool name (e.g., "Read", "Execute")
            arguments: The tool arguments from Droid

        Returns:
            TranslationResult object

        Raises:
            ValueError: If tool is not recognized
        """
        # Check if it's a native Codex tool
        if tool_name in self.CODEX_NATIVE_TOOLS:
            translator_method = getattr(self, f"_translate_{tool_name.lower()}", None)
            if translator_method:
                result: TranslationResult = translator_method(arguments)
                result.original_tool_name = tool_name
                return result
            # Fallback for tools without specific translators
            codex_name = self.CODEX_NATIVE_TOOLS[tool_name]
            return TranslationResult(
                codex_tool_name=codex_name,
                codex_arguments=arguments,
                original_tool_name=tool_name,
            )

        # Check if it's a proxy-side tool
        if tool_name in self.PROXY_SIDE_TOOLS:
            return TranslationResult(
                codex_tool_name=self.PROXY_SIDE_TOOLS[tool_name],
                codex_arguments=arguments,
                is_proxy_side=True,
                original_tool_name=tool_name,
            )

        # Unknown tool
        if logger.isEnabledFor(logging.WARNING):
            logger.warning("Unknown Droid tool: %s", tool_name)
        raise ValueError(f"Unknown Droid tool: {tool_name}")

    def translate_codex_to_droid(
        self, codex_tool_name: str, codex_arguments: dict[str, Any]
    ) -> ReverseTranslationResult:
        """Translate a Codex tool call back to Droid format.

        Used when processing backend responses to translate tool calls
        from Codex format to Droid format.

        Args:
            codex_tool_name: The Codex tool name (e.g., "shell", "read_file")
            codex_arguments: The tool arguments from Codex

        Returns:
            ReverseTranslationResult object
        """
        droid_tool_name = self.CODEX_TO_DROID_TOOLS.get(codex_tool_name)
        if not droid_tool_name:
            # Unknown Codex tool - pass through as-is
            logger.debug(
                "Unknown Codex tool '%s', passing through without translation",
                codex_tool_name,
            )
            return ReverseTranslationResult(
                droid_tool_name=codex_tool_name, droid_arguments=codex_arguments
            )

        # Get reverse translator if exists
        translator_method = getattr(self, f"_reverse_translate_{codex_tool_name}", None)
        if translator_method:
            result: ReverseTranslationResult = translator_method(codex_arguments)
            return result

        # Default: just map name, keep arguments as-is
        return ReverseTranslationResult(
            droid_tool_name=droid_tool_name, droid_arguments=codex_arguments
        )

    def _reverse_translate_read_file(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
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

        return ReverseTranslationResult(
            droid_tool_name="Read",
            droid_arguments=droid_args,
        )

    def _reverse_translate_shell(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
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

        return ReverseTranslationResult(
            droid_tool_name="Execute",
            droid_arguments={"command": command_str},
        )

    def _reverse_translate_bash(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
        """Same as shell; streaming layer may emit ``bash`` for OpenCode-style clients."""
        return self._reverse_translate_shell(codex_args)

    def _reverse_translate_list_dir(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
        """Translate list_dir back to LS.

        Codex list_dir:
            - path: Directory path

        Droid LS:
            - directory_path: Directory path
        """
        return ReverseTranslationResult(
            droid_tool_name="LS",
            droid_arguments={"directory_path": codex_args.get("path", ".")},
        )

    def _reverse_translate_grep_files(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
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

        return ReverseTranslationResult(
            droid_tool_name="Grep",
            droid_arguments=droid_args,
        )

    def _reverse_translate_apply_patch(
        self, codex_args: dict[str, Any]
    ) -> ReverseTranslationResult:
        """Translate apply_patch back to Edit.

        This is a complex translation - Codex uses diff format while
        Droid uses old_str/new_str format. For now, we pass through
        patch content and let client handle it.

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
            return ReverseTranslationResult(
                droid_tool_name="Create",
                droid_arguments={
                    "file_path": file_path,
                    "content": codex_args.get("content", ""),
                },
            )

        # For edits, we pass through as-is since diff format
        # is complex to reverse-engineer
        return ReverseTranslationResult(
            droid_tool_name="Edit",
            droid_arguments={
                "file_path": file_path,
                "old_str": "",  # Placeholder - actual diff handling needed
                "new_str": codex_args.get("content", ""),
            },
        )

        # For edits, we pass through as-is since the diff format
        # is complex to reverse-engineer
        return "Edit", {
            "file_path": file_path,
            "old_str": "",  # Placeholder - actual diff handling needed
            "new_str": codex_args.get("content", ""),
        }

    def _translate_read(self, arguments: dict[str, Any]) -> TranslationResult:
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

        return TranslationResult(
            codex_tool_name="read_file",
            codex_arguments=codex_args,
            original_tool_name="Read",
        )

    def _translate_ls(self, arguments: dict[str, Any]) -> TranslationResult:
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

        return TranslationResult(
            codex_tool_name="list_dir",
            codex_arguments=codex_args,
            original_tool_name="LS",
        )

    def _translate_execute(self, arguments: dict[str, Any]) -> TranslationResult:
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

        return TranslationResult(
            codex_tool_name="shell",
            codex_arguments=codex_args,
            original_tool_name="Execute",
        )

    def _translate_grep(self, arguments: dict[str, Any]) -> TranslationResult:
        """Translate Grep tool to grep_files.

        Droid Grep:
            - pattern: Search pattern
            - file_pattern: Optional file pattern
            - max_results: Optional max results
            - path: Optional search path

        Codex grep_files:
            - pattern: Search pattern
            - file_patterns: Optional file patterns
            - max_results: Optional max results
            - path: Optional search path
        """
        codex_args: dict[str, Any] = {"pattern": arguments["pattern"]}

        if "file_pattern" in arguments:
            codex_args["file_patterns"] = [arguments["file_pattern"]]

        if "max_results" in arguments:
            codex_args["max_results"] = arguments["max_results"]

        if "path" in arguments:
            codex_args["path"] = arguments["path"]

        return TranslationResult(
            codex_tool_name="grep_files",
            codex_arguments=codex_args,
            original_tool_name="Grep",
        )

    def _translate_glob(self, arguments: dict[str, Any]) -> TranslationResult:
        """Translate Glob tool to grep_files.

        Droid Glob:
            - pattern: Glob pattern
            - max_results: Optional max results

        Codex grep_files:
            - pattern: Search pattern (in --files mode)
            - file_patterns: Glob patterns
            - max_results: Optional max results
        """
        codex_args: dict[str, Any] = {"pattern": arguments["pattern"]}

        codex_args["file_patterns"] = [arguments["pattern"]]

        if "max_results" in arguments:
            codex_args["max_results"] = arguments["max_results"]

        return TranslationResult(
            codex_tool_name="grep_files",
            codex_arguments=codex_args,
            original_tool_name="Glob",
        )

    def _translate_edit(self, arguments: dict[str, Any]) -> TranslationResult:
        """Translate Edit tool to apply_patch.

        Droid Edit:
            - file_path: Path to file
            - old_str: String to replace
            - new_str: Replacement string

        Codex apply_patch:
            - patch: Unified diff
        """
        codex_args: dict[str, Any] = {
            "file_path": arguments["file_path"],
            "old_str": "",  # Placeholder - actual diff handling needed
            "new_str": arguments.get("content", ""),
        }

        return TranslationResult(
            codex_tool_name="apply_patch",
            codex_arguments=codex_args,
            original_tool_name="Edit",
        )

    def _translate_create(self, arguments: dict[str, Any]) -> TranslationResult:
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

        return TranslationResult(
            codex_tool_name="apply_patch",
            codex_arguments=codex_args,
            original_tool_name="Create",
        )

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
