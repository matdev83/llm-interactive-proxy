"""Universal tool execution service for dynamic tool compatibility.

Subprocess hygiene (Phase 3 audit, ``src/``):
- ``os.system``: none in this module.
- ``subprocess`` / local shell execution: **not used** here; ``shell`` / ``execute_command``
  are rejected at :meth:`execute_tool` entry so the proxy process never runs model-driven
  shells. ACP and other connectors use their own ``subprocess.Popen(..., shell=False)``
  paths where needed.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from src.core.domain.openai_function_schema import OpenAIFunctionSchema
from src.core.domain.tool_results import UniversalToolResult

logger = logging.getLogger(__name__)


class UniversalToolExecutor:
    """Universal tool executor that handles any tool dynamically without hardcoding.

    This executor can handle:
    - Built-in file system operations
    - Custom tool implementations
    - Workflow markers and control tools

    MCP is not executed in the proxy process; configure MCP in the upstream agent.
    """

    def __init__(
        self,
        working_directory: str | None = None,
        default_timeout: int = 30,
        result_format: str = "kilo_standard",
    ) -> None:
        """Initialize the universal tool executor.

        Args:
            working_directory: Base working directory for file operations
            default_timeout: Default timeout in seconds for long-running operations
            result_format: Result formatting style ("kilo_standard" or "default")
        """
        self.working_directory = Path(working_directory or os.getcwd())
        self.default_timeout = default_timeout
        self.result_format = result_format
        self._custom_tool_handlers: dict[
            str, Callable[[dict[str, Any]], Awaitable[UniversalToolResult]]
        ] = {}
        # Cache for compiled regex patterns to avoid repeated compilation
        self._regex_cache: dict[tuple[str, int], re.Pattern[str]] = {}
        self._register_built_in_handlers()

    def _register_built_in_handlers(self) -> None:
        """Register built-in tool handlers for common operations."""
        self._custom_tool_handlers.update(
            {
                "read_file": self._execute_read_file,
                "list_dir": self._execute_list_dir,
                "list_files": self._execute_list_dir,  # Alias
                "grep_files": self._execute_grep_files,
                "codebase_search": self._execute_grep_files,  # Alias
                "search_files": self._execute_grep_files,  # Alias
                "completion_marker": self._execute_completion_marker,
                "attempt_completion": self._execute_completion_marker,  # Alias
                "__proxy_attempt_completion": self._execute_completion_marker,  # Proxy alias
                "followup_marker": self._execute_followup_marker,
                "ask_followup_question": self._execute_followup_marker,  # Alias
                "__proxy_ask_followup_question": self._execute_followup_marker,  # Proxy alias
                "__proxy_search_and_replace": self._execute_search_and_replace,
                "__proxy_insert_content": self._execute_insert_content,
                "__proxy_edit_file": self._execute_edit_file,
            }
        )

    def _validate_path(
        self,
        path_str: str,
        check_exists: bool = False,
        must_be_file: bool = False,
        must_be_dir: bool = False,
    ) -> Path:
        """Resolve and validate path is within working directory.

        Args:
            path_str: The relative path string
            check_exists: If True, raise if path doesn't exist
            must_be_file: If True, raise if path exists but is not a file
            must_be_dir: If True, raise if path exists but is not a directory

        Returns:
            Resolved absolute path

        Raises:
            ValueError: If path is outside working directory
            FileNotFoundError: If check_exists is True and file missing
            IsADirectoryError: If must_be_file is True and path is dir
            NotADirectoryError: If must_be_dir is True and path is file
        """
        # Resolve path relative to working directory
        resolved_path = (self.working_directory / path_str).resolve()

        # Security check: ensure path is within working directory
        try:
            resolved_path.relative_to(self.working_directory.resolve())
        except ValueError:
            raise ValueError(
                f"Access denied: Path '{path_str}' is outside working directory"
            )

        if check_exists and not resolved_path.exists():
            raise FileNotFoundError(f"File not found: {path_str}")

        if must_be_file and resolved_path.exists() and not resolved_path.is_file():
            raise IsADirectoryError(f"Path is not a file: {path_str}")

        if must_be_dir and resolved_path.exists() and not resolved_path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {path_str}")

        return resolved_path

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute any tool dynamically without hardcoding assumptions.

        This method handles tools in the following priority order:
        1. Custom registered handlers (built-in file operations, markers, etc.)
        2. Error for unknown tools

        MCP tool names are rejected: MCP runs in the agent, not in this proxy.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            UniversalToolResult containing the tool execution result
        """
        try:
            # Never run arbitrary shell commands in the proxy process (model/client driven).
            if tool_name in ("shell", "execute_command"):
                return self._format_result(
                    output=(
                        "Local shell/execute_command execution is disabled on this proxy. "
                        "Use your Codex or ACP client / upstream backend for terminal commands."
                    ),
                    exit_code=1,
                    error="local_shell_execution_disabled",
                    tool_name=tool_name,
                )

            if tool_name in ("write_to_file", "__proxy_write_to_file"):
                return self._format_result(
                    output=(
                        "Local write_to_file execution is disabled on this proxy. "
                        "Use your Codex or ACP agent or IDE to write files."
                    ),
                    exit_code=1,
                    error="local_write_to_file_disabled",
                    tool_name=tool_name,
                )

            if tool_name in (
                "use_mcp_tool",
                "access_mcp_resource",
                "__proxy_use_mcp_tool",
                "__proxy_access_mcp_resource",
            ):
                return self._format_result(
                    output=(
                        "MCP tools are not executed by this proxy. Configure MCP in your "
                        "Codex or ACP agent (or other upstream client) so the model invokes "
                        "MCP there instead of proxy-side."
                    ),
                    exit_code=1,
                    error="mcp_execution_not_supported_in_proxy",
                    tool_name=tool_name,
                )

            # 1. Check for custom registered handlers first
            if tool_name in self._custom_tool_handlers:
                handler = self._custom_tool_handlers[tool_name]
                result = await handler(arguments)
                if isinstance(result, UniversalToolResult):
                    return result
                return self._format_result_from_dict(tool_name, result)

            # 2. Unknown tool - return error
            available_tools = self.get_available_tools()
            return self._format_result(
                output=f"Unknown tool: {tool_name}. Available tools: {available_tools}",
                exit_code=1,
                error=f"Tool '{tool_name}' is not available",
                tool_name=tool_name,
            )

        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return self._format_result(
                output=f"Error executing {tool_name}: {e!s}",
                exit_code=1,
                error=str(e),
                tool_name=tool_name,
            )

    def _format_result_from_dict(
        self, tool_name: str, result: dict[str, Any]
    ) -> UniversalToolResult:
        """Convert a dictionary result to a UniversalToolResult."""
        result_dict = dict(result)

        output = result_dict.pop("output", "")
        exit_code = result_dict.pop("exit_code", 0)
        error = result_dict.pop("error", None)
        # Remove tool_name from result if present to avoid conflict
        result_dict.pop("tool_name", None)
        return self._format_result(
            output=output,
            exit_code=exit_code,
            tool_name=tool_name,
            error=error,
            **result_dict,
        )

    def register_tool_handler(
        self,
        tool_name: str,
        handler: Callable[[dict[str, Any]], Awaitable[UniversalToolResult]],
    ) -> None:
        """Register a custom tool handler.

        Args:
            tool_name: Name of the tool
            handler: Async function that takes arguments dict and returns result dict
        """
        self._custom_tool_handlers[tool_name] = handler
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Registered custom handler for tool: %s", tool_name)

    def get_available_tools(self) -> list[str]:
        """Get list of all available tools.

        Returns:
            List of available tool names
        """
        available_tools = list(self._custom_tool_handlers.keys())
        return sorted(available_tools)

    def format_result_for_kilocode(self, tool_name: str, result: dict[str, Any]) -> str:
        """Format tool execution result in KiloCode format.

        This is a public method for external callers (like KiloToolTranslator)
        to format tool results consistently with KiloCode client expectations.

        Args:
            tool_name: Name of the tool that was executed
            result: Tool execution result dictionary containing:
                - output or content: The result content
                - error: Error message if execution failed
                - exit_code: Exit code (0 for success, non-zero for error)
                - success: Boolean success flag (optional)

        Returns:
            Formatted result string in KiloCode format:
            - Success: "[tool_name] Result:\\n<content>"
            - Error: "[tool_name] Error: <error_message>"
            - Timeout: "[tool_name] Error: Execution timed out"

        Examples:
            >>> executor.format_result_for_kilocode("read_file", {
            ...     "output": "file content",
            ...     "exit_code": 0
            ... })
            "[read_file] Result:\\nfile content"

            >>> executor.format_result_for_kilocode("grep_files", {
            ...     "error": "Invalid regex",
            ...     "exit_code": 1
            ... })
            "[grep_files] Error: Invalid regex"
        """
        # Check for explicit success flag
        if "success" in result:
            is_success = result["success"]
        else:
            # Infer success from exit_code
            is_success = result.get("exit_code", 0) == 0

        if is_success:
            # Extract content from various possible fields
            content = (
                result.get("output")
                or result.get("content")
                or result.get("result")
                or ""
            )
            return f"[{tool_name}] Result:\n{content}"
        else:
            # Extract error message
            error = result.get("error") or result.get("output") or "Unknown error"

            # Check for timeout-specific error
            if "timed out" in str(error).lower() or "timeout" in str(error).lower():
                return f"[{tool_name}] Error: Execution timed out"

            return f"[{tool_name}] Error: {error}"

    async def _execute_read_file(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute read_file tool with error handling for invalid paths."""
        # Support both 'file_path' and 'path' parameter names
        file_path = arguments.get("file_path") or arguments.get("path")
        if not file_path:
            error_msg = "Error: file_path is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing file_path parameter",
                tool_name="read_file",
            )

        try:
            resolved_path = self._validate_path(
                file_path, check_exists=True, must_be_file=True
            )

            # Read file content
            content = await asyncio.to_thread(
                lambda: resolved_path.read_text(encoding="utf-8", errors="replace")
            )

            # Handle line range if specified
            start_line = arguments.get("start_line")
            end_line = arguments.get("end_line")

            if start_line is not None or end_line is not None:
                lines = content.splitlines()
                start_idx = (start_line - 1) if start_line is not None else 0
                end_idx = end_line if end_line is not None else len(lines)

                # Clamp indices
                start_idx = max(0, start_idx)
                end_idx = min(len(lines), end_idx)

                if start_idx < end_idx:
                    selected_lines = lines[start_idx:end_idx]
                    content = "\n".join(selected_lines)
                else:
                    content = ""

            return self._format_result(
                output=content,
                exit_code=0,
                tool_name="read_file",
                file_path=str(resolved_path),
                size=len(content),
            )

        except UnicodeDecodeError:
            error_msg = f"Error: Cannot read file as text (binary file?): {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="File appears to be binary or has encoding issues",
                tool_name="read_file",
            )
        except FileNotFoundError:
            error_msg = f"Error: File not found: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="File not found",
                tool_name="read_file",
            )
        except PermissionError:
            error_msg = f"Error: Permission denied reading file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="read_file",
            )
        except OSError as e:
            # OSError includes FileNotFoundError, PermissionError, and other OS-level errors
            error_msg = f"Error reading file {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "OS error reading file: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="read_file",
            )
        except ValueError as e:
            # ValueError can occur during path validation or line range processing
            error_msg = f"Error reading file {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Value error reading file: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="read_file",
            )
        except Exception as e:
            error_msg = f"Error reading file {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error reading file: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="read_file",
            )

    async def _execute_list_dir(self, arguments: dict[str, Any]) -> UniversalToolResult:
        """Execute list_dir tool with recursive traversal support."""
        # Support both 'dir_path' and 'path' parameter names
        dir_path = arguments.get("dir_path") or arguments.get("path", ".")
        recursive = arguments.get("recursive", False)
        depth = arguments.get("depth")
        include_hidden = arguments.get("include_hidden", False)

        # If depth is specified, enable recursive mode
        if depth is not None:
            recursive = True

        try:
            resolved_path = self._validate_path(
                dir_path, check_exists=True, must_be_dir=True
            )

            entries = []

            if recursive:
                # Recursive listing with optional depth limit
                max_depth = depth if depth is not None else float("inf")
                for item in resolved_path.rglob("*"):
                    if not include_hidden and item.name.startswith("."):
                        continue

                    # Check depth
                    try:
                        relative_path = item.relative_to(resolved_path)
                        item_depth = len(relative_path.parts)
                        if item_depth > max_depth:
                            continue

                        entry_type = "directory" if item.is_dir() else "file"
                        entries.append(f"{entry_type}: {relative_path}")
                    except ValueError:
                        continue
            else:
                # Non-recursive listing
                for item in resolved_path.iterdir():
                    if not include_hidden and item.name.startswith("."):
                        continue

                    entry_type = "directory" if item.is_dir() else "file"
                    entries.append(f"{entry_type}: {item.name}")

            # Sort entries for consistent output
            entries.sort()

            output = "\n".join(entries) if entries else "Directory is empty"

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="list_dir",
                directory=str(resolved_path),
                count=len(entries),
            )

        except PermissionError:
            error_msg = f"Error: Permission denied accessing directory: {dir_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="list_dir",
            )
        except Exception as e:
            error_msg = f"Error listing directory {dir_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error listing directory: %s",
                    e,
                    exc_info=True,
                    extra={"dir_path": dir_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="list_dir",
            )

    async def _execute_grep_files(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute grep_files tool with include/exclude glob pattern support."""
        pattern = arguments.get("pattern")
        if not pattern:
            error_msg = "Error: pattern is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing pattern parameter",
                tool_name="grep_files",
            )

        search_path = arguments.get("path", ".")
        recursive = arguments.get("recursive", True)
        case_sensitive = arguments.get("case_sensitive", True)
        include_pattern = arguments.get("include")
        exclude_pattern = arguments.get("exclude")

        try:
            resolved_path = self._validate_path(search_path, check_exists=True)

            # Compile regex pattern (use cache to avoid repeated compilation)
            flags = 0 if case_sensitive else re.IGNORECASE
            cache_key = (pattern, flags)
            regex = self._regex_cache.get(cache_key)
            if regex is None:
                try:
                    regex = re.compile(pattern, flags)
                    # Cache compiled pattern (bounded to prevent unbounded growth)
                    if len(self._regex_cache) < 100:  # Limit cache size
                        self._regex_cache[cache_key] = regex
                except re.error as e:
                    error_msg = f"Error: Invalid regex pattern: {e}"
                    return self._format_result(
                        output=error_msg,
                        exit_code=1,
                        error=f"Invalid regex: {e}",
                        tool_name="grep_files",
                    )

            matches = []

            if resolved_path.is_file():
                # Search in single file
                if self._should_include_file(
                    resolved_path, include_pattern, exclude_pattern
                ):
                    matches.extend(await self._search_file(resolved_path, regex))
            else:
                # Search in directory
                if recursive:
                    pattern_glob = "**/*"
                else:
                    pattern_glob = "*"

                for file_path in resolved_path.glob(pattern_glob):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        # Apply include/exclude filters
                        if not self._should_include_file(
                            file_path, include_pattern, exclude_pattern
                        ):
                            continue

                        try:
                            matches.extend(await self._search_file(file_path, regex))
                        except (UnicodeDecodeError, PermissionError):
                            # Skip binary files or files we can't read
                            continue

            if matches:
                output = "\n".join(matches)
            else:
                output = f"No matches found for pattern: {pattern}"

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="grep_files",
                pattern=pattern,
                matches_count=len(matches),
            )

        except Exception as e:
            error_msg = f"Error searching for pattern {pattern}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error searching for pattern: %s",
                    e,
                    exc_info=True,
                    extra={"pattern": pattern, "search_path": search_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="grep_files",
            )

    async def _search_file(self, file_path: Path, regex: re.Pattern[str]) -> list[str]:
        """Search for pattern in a single file."""
        matches = []
        try:
            content = await asyncio.to_thread(
                lambda: file_path.read_text(encoding="utf-8", errors="replace")
            )
            lines = content.splitlines()

            for line_num, line in enumerate(lines, 1):
                if regex.search(line):
                    # Format: filename:line_number:line_content
                    relative_path = file_path.relative_to(self.working_directory)
                    matches.append(f"{relative_path}:{line_num}:{line.strip()}")
        except (UnicodeDecodeError, PermissionError) as e:
            # Skip files we can't read, but log at DEBUG level for visibility
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Skipping file %s due to read error (binary or permission issue): %s",
                    file_path,
                    e,
                    exc_info=True,
                )

        return matches

    def _should_include_file(
        self, file_path: Path, include_pattern: str | None, exclude_pattern: str | None
    ) -> bool:
        """Check if file should be included based on glob patterns.

        Args:
            file_path: Path to the file
            include_pattern: Glob pattern for files to include (e.g., "*.py")
            exclude_pattern: Glob pattern for files to exclude (e.g., "*.log")

        Returns:
            True if file should be included, False otherwise
        """
        try:
            # Security check: ensure file is within working directory
            file_path.relative_to(self.working_directory)

            # Check exclude pattern first (takes precedence)
            if exclude_pattern and file_path.match(exclude_pattern):
                return False

            # Check include pattern
            if include_pattern:
                return file_path.match(include_pattern)

            # No patterns specified, include by default
            return True

        except ValueError:
            # File is outside working directory
            return False

    async def _execute_completion_marker(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute completion_marker tool."""
        result = arguments.get("result", "Task completed")

        return self._format_result(
            output=f"[COMPLETION] {result}",
            exit_code=0,
            completion_result=result,
            marker_type="completion",
            tool_name="completion_marker",
        )

    async def _execute_followup_marker(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute followup_marker tool."""
        question = arguments.get("question", "Do you have any questions?")

        return self._format_result(
            output=f"[FOLLOWUP] {question}",
            exit_code=0,
            followup_question=question,
            marker_type="followup",
            tool_name="followup_marker",
        )

    def _format_result(
        self, output: str, exit_code: int, tool_name: str, **kwargs: Any
    ) -> UniversalToolResult:
        """Format tool execution result in KiloCode's expected format.

        Args:
            output: Tool output text
            exit_code: Exit code (0 for success, non-zero for error)
            tool_name: Name of the tool that was executed
            **kwargs: Additional metadata to include in result

        Returns:
            UniversalToolResult containing formatted result
        """
        # Apply KiloCode formatting if enabled
        if self.result_format == "kilo_standard" and not output.startswith("["):
            # Format output with [tool_name] Result: prefix
            # Skip if output already has a tool name prefix
            output = f"[{tool_name}] Result:\n{output}"

        return UniversalToolResult(
            output=output,
            exit_code=exit_code,
            error=kwargs.pop("error", None),
            metadata=kwargs,
        )

    def get_tool_schemas(self) -> list[OpenAIFunctionSchema]:
        """Get OpenAI-compatible schemas advertised by this executor.

        Built-in proxy tools are handled without separate schemas here; discovery
        comes from the upstream Codex/agent capabilities.
        """
        return []

    async def _execute_search_and_replace(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute search_and_replace tool to replace text in a file.

        Args:
            arguments: Dictionary containing:
                - path: File path
                - search: Text to search for
                - replace: Text to replace with

        Returns:
            Dictionary with output, exit_code, and metadata
        """
        file_path = arguments.get("path")
        search_text = arguments.get("search")
        replace_text = arguments.get("replace")

        if not file_path:
            error_msg = "Error: path is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing path parameter",
                tool_name="search_and_replace",
            )

        if search_text is None:
            error_msg = "Error: search is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing search parameter",
                tool_name="search_and_replace",
            )

        if replace_text is None:
            error_msg = "Error: replace is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing replace parameter",
                tool_name="search_and_replace",
            )

        try:
            resolved_path = self._validate_path(
                file_path, check_exists=True, must_be_file=True
            )

            # Read file content
            content = await asyncio.to_thread(
                lambda: resolved_path.read_text(encoding="utf-8", errors="replace")
            )

            # Perform replacement
            if search_text not in content:
                error_msg = f"Error: Search text not found in file: {file_path}"
                return self._format_result(
                    output=error_msg,
                    exit_code=1,
                    error="Search text not found",
                    tool_name="search_and_replace",
                )

            # Count occurrences
            occurrences = content.count(search_text)

            # Replace all occurrences
            new_content = content.replace(search_text, replace_text)

            # Write back to file
            await asyncio.to_thread(
                lambda: resolved_path.write_text(new_content, encoding="utf-8")
            )

            output = f"Successfully replaced {occurrences} occurrence(s) in {file_path}"

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="search_and_replace",
                file_path=str(resolved_path),
                occurrences=occurrences,
            )

        except PermissionError:
            error_msg = f"Error: Permission denied writing to file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="search_and_replace",
            )
        except Exception as e:
            error_msg = f"Error performing search and replace in {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error performing search and replace: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="search_and_replace",
            )

    async def _execute_insert_content(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute insert_content tool to insert content at a position in a file.

        Args:
            arguments: Dictionary containing:
                - path: File path
                - content: Content to insert
                - position: Optional line number to insert at (0-based)

        Returns:
            Dictionary with output, exit_code, and metadata
        """
        file_path = arguments.get("path")
        content = arguments.get("content")
        position = arguments.get("position")

        if not file_path:
            error_msg = "Error: path is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing path parameter",
                tool_name="insert_content",
            )

        if content is None:
            error_msg = "Error: content is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing content parameter",
                tool_name="insert_content",
            )

        try:
            resolved_path = self._validate_path(
                file_path, check_exists=True, must_be_file=True
            )

            # Read file content
            existing_content = await asyncio.to_thread(
                lambda: resolved_path.read_text(encoding="utf-8", errors="replace")
            )
            lines = existing_content.splitlines(keepends=True)

            # Insert content at position
            if position is not None:
                # Clamp position to valid range
                insert_pos = max(0, min(position, len(lines)))
                lines.insert(
                    insert_pos, content if content.endswith("\n") else content + "\n"
                )
                output = (
                    f"Successfully inserted content at line {insert_pos} in {file_path}"
                )
            else:
                # Append to end if no position specified
                lines.append(content if content.endswith("\n") else content + "\n")
                output = f"Successfully appended content to {file_path}"

            # Write back to file
            new_content = "".join(lines)
            await asyncio.to_thread(
                lambda: resolved_path.write_text(new_content, encoding="utf-8")
            )

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="insert_content",
                file_path=str(resolved_path),
                position=position,
            )

        except PermissionError:
            error_msg = f"Error: Permission denied writing to file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="insert_content",
            )
        except Exception as e:
            error_msg = f"Error inserting content in {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error inserting content: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="insert_content",
            )

    async def _execute_edit_file(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute edit_file tool to edit a file.

        This is a generic editing tool that can perform various operations.
        If content is provided, it replaces the entire file content.

        Args:
            arguments: Dictionary containing:
                - path: File path
                - content: Optional new content for the file

        Returns:
            Dictionary with output, exit_code, and metadata
        """
        file_path = arguments.get("path")
        content = arguments.get("content")

        if not file_path:
            error_msg = "Error: path is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing path parameter",
                tool_name="edit_file",
            )

        try:
            resolved_path = self._validate_path(
                file_path, check_exists=True, must_be_file=True
            )

            if content is not None:
                # Replace entire file content
                await asyncio.to_thread(
                    lambda: resolved_path.write_text(content, encoding="utf-8")
                )
                output = f"Successfully edited {file_path} ({len(content)} bytes)"
            else:
                # No content provided - just verify file exists
                output = f"File {file_path} is ready for editing"

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="edit_file",
                file_path=str(resolved_path),
            )

        except PermissionError:
            error_msg = f"Error: Permission denied editing file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="edit_file",
            )
        except Exception as e:
            error_msg = f"Error editing file {file_path}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error editing file: %s",
                    e,
                    exc_info=True,
                    extra={"file_path": file_path},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="edit_file",
            )

    async def cleanup(self) -> None:
        """Release executor resources (no-op; MCP is not hosted in-proxy)."""
        return
