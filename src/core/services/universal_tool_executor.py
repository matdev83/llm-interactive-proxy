"""Universal tool execution service for dynamic tool compatibility."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

from src.core.domain.tool_results import UniversalToolResult
from src.core.services.universal_mcp_client import UniversalMCPClient

logger = logging.getLogger(__name__)


class UniversalToolExecutor:
    """Universal tool executor that handles any tool dynamically without hardcoding.

    This executor can handle:
    - Built-in file system operations
    - MCP tools from any server
    - Custom tool implementations
    - Workflow markers and control tools
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
        self.mcp_client = UniversalMCPClient()
        self._custom_tool_handlers: dict[
            str, Callable[[dict[str, Any]], Awaitable[UniversalToolResult]]
        ] = {}
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
                "shell": self._execute_shell,
                "execute_command": self._execute_shell,  # Alias
                "completion_marker": self._execute_completion_marker,
                "attempt_completion": self._execute_completion_marker,  # Alias
                "__proxy_attempt_completion": self._execute_completion_marker,  # Proxy alias
                "followup_marker": self._execute_followup_marker,
                "ask_followup_question": self._execute_followup_marker,  # Alias
                "__proxy_ask_followup_question": self._execute_followup_marker,  # Proxy alias
                "__proxy_search_and_replace": self._execute_search_and_replace,
                "__proxy_write_to_file": self._execute_write_to_file,
                "__proxy_insert_content": self._execute_insert_content,
                "__proxy_edit_file": self._execute_edit_file,
                "__proxy_use_mcp_tool": self._execute_generic_mcp_tool,
                "__proxy_access_mcp_resource": self._execute_access_mcp_resource,
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
        2. MCP tools from connected servers
        3. Generic MCP tool execution via use_mcp_tool pattern
        4. Error for unknown tools

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            UniversalToolResult containing the tool execution result
        """
        try:
            # 1. Check for custom registered handlers first
            if tool_name in self._custom_tool_handlers:
                handler = self._custom_tool_handlers[tool_name]
                result = await handler(arguments)
                if isinstance(result, UniversalToolResult):
                    return result
                return self._format_result_from_dict(tool_name, result)

            # 2. Check if it's an MCP tool from connected servers
            if self.mcp_client.is_mcp_tool(tool_name):
                mcp_result = await self.mcp_client.execute_tool(tool_name, arguments)
                return self._format_result_from_dict(tool_name, mcp_result)

            # 3. Handle generic MCP tool execution pattern
            if tool_name == "use_mcp_tool":
                generic_result = await self._execute_generic_mcp_tool(arguments)
                if isinstance(generic_result, UniversalToolResult):
                    return generic_result
                return self._format_result_from_dict(tool_name, generic_result)

            # 4. Unknown tool - return error
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
        output = result.pop("output", "")
        exit_code = result.pop("exit_code", 0)
        error = result.pop("error", None)
        # Remove tool_name from result if present to avoid conflict
        result.pop("tool_name", None)
        return self._format_result(
            output=output,
            exit_code=exit_code,
            tool_name=tool_name,
            error=error,
            **result,
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
            logger.debug(f"Registered custom handler for tool: {tool_name}")

    def get_available_tools(self) -> list[str]:
        """Get list of all available tools.

        Returns:
            List of available tool names
        """
        available_tools = list(self._custom_tool_handlers.keys())
        available_tools.extend(
            [tool.name for tool in self.mcp_client.get_available_tools()]
        )
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

            >>> executor.format_result_for_kilocode("shell", {
            ...     "error": "Command not found",
            ...     "exit_code": 1
            ... })
            "[shell] Error: Command not found"
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

    async def connect_mcp_server(
        self, server_name: str, server_config: dict[str, Any]
    ) -> bool:
        """Connect to an MCP server to make its tools available.

        Args:
            server_name: Unique name for the server
            server_config: Server configuration

        Returns:
            True if connection successful, False otherwise
        """
        return await self.mcp_client.connect_to_server(server_name, server_config)

    async def _execute_generic_mcp_tool(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute a generic MCP tool via the use_mcp_tool pattern.

        This handles the KiloCode pattern: <use_mcp_tool tool_name="..." ...>
        Includes schema translation for MCP tool parameters.
        """
        tool_name = arguments.get("tool_name")
        if not tool_name:
            return self._format_result(
                output="Error: tool_name is required for use_mcp_tool",
                exit_code=1,
                error="Missing tool_name parameter",
                tool_name="use_mcp_tool",
            )

        # Extract tool arguments
        tool_arguments = arguments.get("tool_arguments", {})
        if not tool_arguments and "arguments" in arguments:
            raw_args = arguments["arguments"]
            if isinstance(raw_args, str):
                try:
                    tool_arguments = json.loads(raw_args)
                except json.JSONDecodeError:
                    tool_arguments = {"content": raw_args}
            elif isinstance(raw_args, Mapping):
                tool_arguments = dict(raw_args)
        if isinstance(tool_arguments, str):
            try:
                tool_arguments = json.loads(tool_arguments)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as raw string content
                tool_arguments = {"content": tool_arguments}

        # Add any other parameters as tool arguments (excluding known meta parameters)
        for key, value in arguments.items():
            if key not in ["tool_name", "tool_arguments", "arguments"]:
                tool_arguments[key] = value

        # Perform schema translation if needed
        # This translates KiloCode parameter names to MCP parameter names
        translated_arguments = self._translate_mcp_tool_schema(
            tool_name, tool_arguments
        )

        # Check if MCP tool is available
        if not self.mcp_client.is_mcp_tool(tool_name):
            # Tool not found in connected MCP servers
            available_tools = [
                tool.name for tool in self.mcp_client.get_available_tools()
            ]
            error_msg = (
                f"MCP tool '{tool_name}' is not available. "
                f"Available MCP tools: {', '.join(available_tools) if available_tools else 'none'}"
            )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=f"MCP tool '{tool_name}' not found",
                tool_name="use_mcp_tool",
            )

        # Execute the MCP tool
        try:
            result = await self.mcp_client.execute_tool(tool_name, translated_arguments)

            # Format result in KiloCode's expected format
            if self.result_format == "kilo_standard":
                # Ensure output is formatted with tool name prefix
                output = result.get("output", "")
                if not output.startswith(f"[{tool_name}]"):
                    result["output"] = f"[{tool_name}] Result:\n{output}"

            return self._format_result_from_dict(tool_name, result)

        except Exception as e:
            error_msg = f"Error executing MCP tool '{tool_name}': {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "MCP tool execution failed: %s",
                    e,
                    exc_info=True,
                    extra={"tool_name": tool_name, "arguments": translated_arguments},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="use_mcp_tool",
            )

    def _translate_mcp_tool_schema(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Translate KiloCode parameter names to MCP parameter names.

        This handles common parameter name differences between KiloCode and MCP tools.

        Args:
            tool_name: Name of the MCP tool
            arguments: Original arguments from KiloCode

        Returns:
            Translated arguments for MCP tool
        """
        # Common parameter name mappings
        # KiloCode name -> MCP name
        common_mappings = {
            "file_path": "path",
            "dir_path": "path",
            "search_pattern": "pattern",
            "search_query": "query",
        }

        translated = {}
        for key, value in arguments.items():
            # Check if this parameter needs translation
            translated_key = common_mappings.get(key, key)
            translated[translated_key] = value

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Translated MCP tool parameters for '%s': %s -> %s",
                tool_name,
                arguments,
                translated,
            )

        return translated

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
        except PermissionError:
            error_msg = f"Error: Permission denied reading file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="read_file",
            )
        except Exception as e:
            error_msg = f"Error reading file {file_path}: {e!s}"
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

            # Compile regex pattern
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
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
        except (UnicodeDecodeError, PermissionError):
            # Skip files we can't read
            pass

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

    async def _execute_shell(self, arguments: dict[str, Any]) -> UniversalToolResult:
        """Execute shell command with output capture and exit code handling.

        Args:
            arguments: Dictionary containing:
                - command: Command string to execute
                - working_dir: Optional working directory
                - timeout: Optional timeout in seconds

        Returns:
            Dictionary with output, exit_code, and error information
        """
        command = arguments.get("command")
        if not command:
            error_msg = "Error: command is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing command parameter",
                tool_name="shell",
            )

        working_dir = arguments.get("working_dir")
        timeout = arguments.get("timeout", self.default_timeout)

        # Resolve working directory
        if working_dir:
            resolved_working_dir = self.working_directory / working_dir
            resolved_working_dir = resolved_working_dir.resolve()
        else:
            resolved_working_dir = self.working_directory

        try:
            # Ensure working directory exists
            if not resolved_working_dir.exists():
                error_msg = f"Error: Working directory not found: {working_dir}"
                return self._format_result(
                    output=error_msg,
                    exit_code=1,
                    error=f"Working directory does not exist: {working_dir}",
                    tool_name="shell",
                )

            # Execute command with timeout
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Executing shell command: %s (timeout: %ds, cwd: %s)",
                    command,
                    timeout,
                    working_dir,
                )

            # Run command in executor to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(  # nosec: B602 - Intentional shell execution for shell tool functionality
                    command,
                    shell=True,
                    capture_output=True,
                    cwd=str(resolved_working_dir),
                    timeout=timeout,
                    text=True,
                    errors="replace",
                ),
            )

            # Decode output
            stdout_text = result.stdout.strip() if result.stdout else ""
            stderr_text = result.stderr.strip() if result.stderr else ""

            # Combine stdout and stderr
            output_parts = []
            if stdout_text:
                output_parts.append(stdout_text)
            if stderr_text:
                output_parts.append(f"STDERR:\n{stderr_text}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            exit_code = result.returncode

            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Command completed with exit code %d (output length: %d bytes)",
                    exit_code,
                    len(output),
                )

            return self._format_result(
                output=output,
                exit_code=exit_code,
                tool_name="shell",
                command=command,
                working_directory=str(resolved_working_dir),
            )

        except subprocess.TimeoutExpired:
            error_msg = f"Error: Command timed out after {timeout} seconds"
            return self._format_result(
                output=error_msg,
                exit_code=124,  # Standard timeout exit code
                error=f"Command execution timed out after {timeout}s",
                tool_name="shell",
            )
        except FileNotFoundError as e:
            error_msg = f"Error: Command not found: {command}"
            return self._format_result(
                output=error_msg,
                exit_code=127,  # Standard "command not found" exit code
                error=str(e),
                tool_name="shell",
            )
        except PermissionError:
            error_msg = f"Error: Permission denied executing command: {command}"
            return self._format_result(
                output=error_msg,
                exit_code=126,  # Standard "permission denied" exit code
                error="Permission denied",
                tool_name="shell",
            )
        except Exception as e:
            error_msg = f"Error executing command: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Unexpected error executing shell command: %s", e, exc_info=True
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="shell",
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
            # Skip if output already has a tool name prefix (e.g., from MCP tools)
            output = f"[{tool_name}] Result:\n{output}"

        return UniversalToolResult(
            output=output,
            exit_code=exit_code,
            error=kwargs.pop("error", None),
            metadata=kwargs,
        )

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible schemas for all available tools.

        Returns:
            List of OpenAI function schemas for built-in and MCP tools
        """
        schemas = []

        # Add MCP tool schemas
        schemas.extend(self.mcp_client.get_tool_schemas())

        # Note: Built-in tools don't need schemas as they're handled internally
        # The tool discovery should come from the actual backend/client capabilities

        return schemas

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
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="search_and_replace",
            )

    async def _execute_write_to_file(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute write_to_file tool to write content to a file.

        Args:
            arguments: Dictionary containing:
                - path: File path
                - content: Content to write

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
                tool_name="write_to_file",
            )

        if content is None:
            error_msg = "Error: content is required"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing content parameter",
                tool_name="write_to_file",
            )

        try:
            resolved_path = self._validate_path(file_path)

            # Create parent directories if they don't exist
            resolved_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content to file
            await asyncio.to_thread(
                lambda: resolved_path.write_text(content, encoding="utf-8")
            )

            output = f"Successfully wrote {len(content)} bytes to {file_path}"

            return self._format_result(
                output=output,
                exit_code=0,
                tool_name="write_to_file",
                file_path=str(resolved_path),
                size=len(content),
            )

        except PermissionError:
            error_msg = f"Error: Permission denied writing to file: {file_path}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Permission denied",
                tool_name="write_to_file",
            )
        except Exception as e:
            error_msg = f"Error writing to file {file_path}: {e!s}"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="write_to_file",
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
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="edit_file",
            )

    async def _execute_access_mcp_resource(
        self, arguments: dict[str, Any]
    ) -> UniversalToolResult:
        """Execute access_mcp_resource to read an MCP resource.

        Args:
            arguments: Dictionary containing:
                - uri: Resource URI to access

        Returns:
            Dictionary with output, exit_code, and metadata
        """
        uri = arguments.get("uri")
        if not uri:
            error_msg = "Error: uri is required for access_mcp_resource"
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error="Missing uri parameter",
                tool_name="access_mcp_resource",
            )

        try:
            # Access the MCP resource
            result = await self.mcp_client.read_resource(uri)

            # Format the result
            if isinstance(result, dict):
                # If result is a dict, extract content or convert to string
                content = result.get("content", str(result))
            else:
                content = str(result)

            return self._format_result(
                output=content,
                exit_code=0,
                tool_name="access_mcp_resource",
                uri=uri,
            )

        except Exception as e:
            error_msg = f"Error accessing MCP resource {uri}: {e!s}"
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to access MCP resource: %s",
                    e,
                    exc_info=True,
                    extra={"uri": uri},
                )
            return self._format_result(
                output=error_msg,
                exit_code=1,
                error=str(e),
                tool_name="access_mcp_resource",
            )

    async def cleanup(self) -> None:
        """Clean up resources and disconnect from MCP servers."""
        await self.mcp_client.disconnect_all()
