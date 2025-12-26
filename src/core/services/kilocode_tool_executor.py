"""KiloCode tool execution service for Codex compatibility."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any

from src.core.domain.kilocode import KiloCodeToolResult

logger = logging.getLogger(__name__)


class KiloCodeToolExecutor:
    """Executes KiloCode-specific tools for Codex compatibility."""

    def __init__(self, working_directory: str | None = None) -> None:
        """Initialize the tool executor.

        Args:
            working_directory: Base working directory for file operations
        """
        self.working_directory = Path(working_directory or os.getcwd())

    async def execute_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> KiloCodeToolResult:
        """Execute a KiloCode tool and return the result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            KiloCodeToolResult containing the tool execution result
        """
        try:
            if tool_name == "read_file":
                return await self._execute_read_file(arguments)
            elif tool_name == "list_dir":
                return await self._execute_list_dir(arguments)
            elif tool_name == "grep_files":
                return await self._execute_grep_files(arguments)
            elif tool_name == "use_mcp_tool":
                return await self._execute_use_mcp_tool(arguments)
            elif tool_name == "completion_marker":
                return await self._execute_completion_marker(arguments)
            elif tool_name == "followup_marker":
                return await self._execute_followup_marker(arguments)
            else:
                return KiloCodeToolResult(
                    output=f"Unknown KiloCode tool: {tool_name}",
                    exit_code=1,
                    error=f"Tool '{tool_name}' is not supported",
                )
        except Exception as e:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    f"Error executing KiloCode tool {tool_name}: {e}", exc_info=True
                )
            return KiloCodeToolResult(
                output=f"Error executing {tool_name}: {e!s}",
                exit_code=1,
                error=str(e),
            )

    async def _execute_read_file(self, arguments: dict[str, Any]) -> KiloCodeToolResult:
        """Execute read_file tool."""
        file_path = arguments.get("file_path")
        if not file_path:
            return KiloCodeToolResult(
                output="Error: file_path is required",
                exit_code=1,
                error="Missing file_path parameter",
            )

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / file_path
            resolved_path = resolved_path.resolve()

            # Security check: ensure path is within working directory or its subdirectories
            try:
                resolved_path.relative_to(self.working_directory.resolve())
            except ValueError:
                return KiloCodeToolResult(
                    output=f"Error: Access denied. Path is outside working directory: {file_path}",
                    exit_code=1,
                    error=f"Access denied: {file_path}",
                )

            if not resolved_path.exists():
                return KiloCodeToolResult(
                    output=f"Error: File not found: {file_path}",
                    exit_code=1,
                    error=f"File does not exist: {file_path}",
                )

            if not resolved_path.is_file():
                return KiloCodeToolResult(
                    output=f"Error: Path is not a file: {file_path}",
                    exit_code=1,
                    error=f"Path is not a file: {file_path}",
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

            return KiloCodeToolResult(
                output=content,
                exit_code=0,
                file_path=str(resolved_path),
                size=len(content),
            )

        except UnicodeDecodeError:
            return KiloCodeToolResult(
                output=f"Error: Cannot read file as text (binary file?): {file_path}",
                exit_code=1,
                error="File appears to be binary or has encoding issues",
            )
        except PermissionError:
            return KiloCodeToolResult(
                output=f"Error: Permission denied reading file: {file_path}",
                exit_code=1,
                error="Permission denied",
            )
        except Exception as e:
            return KiloCodeToolResult(
                output=f"Error reading file {file_path}: {e!s}",
                exit_code=1,
                error=str(e),
            )

    async def _execute_list_dir(self, arguments: dict[str, Any]) -> KiloCodeToolResult:
        """Execute list_dir tool."""
        dir_path = arguments.get("dir_path", ".")
        recursive = arguments.get("recursive", False)
        include_hidden = arguments.get("include_hidden", False)

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / dir_path
            resolved_path = resolved_path.resolve()

            # Security check: ensure path is within working directory
            try:
                resolved_path.relative_to(self.working_directory.resolve())
            except ValueError:
                return KiloCodeToolResult(
                    output=f"Error: Access denied. Path is outside working directory: {dir_path}",
                    exit_code=1,
                    error=f"Access denied: {dir_path}",
                )

            if not resolved_path.exists():
                return KiloCodeToolResult(
                    output=f"Error: Directory not found: {dir_path}",
                    exit_code=1,
                    error=f"Directory does not exist: {dir_path}",
                )

            if not resolved_path.is_dir():
                return KiloCodeToolResult(
                    output=f"Error: Path is not a directory: {dir_path}",
                    exit_code=1,
                    error=f"Path is not a directory: {dir_path}",
                )

            entries = []

            if recursive:
                # Recursive listing
                for item in resolved_path.rglob("*"):
                    if not include_hidden and item.name.startswith("."):
                        continue

                    relative_path = item.relative_to(resolved_path)
                    entry_type = "directory" if item.is_dir() else "file"
                    entries.append(f"{entry_type}: {relative_path}")
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

            return KiloCodeToolResult(
                output=output,
                exit_code=0,
                directory=str(resolved_path),
                count=len(entries),
            )

        except PermissionError:
            return KiloCodeToolResult(
                output=f"Error: Permission denied accessing directory: {dir_path}",
                exit_code=1,
                error="Permission denied",
            )
        except Exception as e:
            return KiloCodeToolResult(
                output=f"Error listing directory {dir_path}: {e!s}",
                exit_code=1,
                error=str(e),
            )

    async def _execute_grep_files(
        self, arguments: dict[str, Any]
    ) -> KiloCodeToolResult:
        """Execute grep_files tool."""
        pattern = arguments.get("pattern")
        if not pattern:
            return KiloCodeToolResult(
                output="Error: pattern is required",
                exit_code=1,
                error="Missing pattern parameter",
            )

        search_path = arguments.get("path", ".")
        recursive = arguments.get("recursive", True)
        case_sensitive = arguments.get("case_sensitive", True)

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / search_path
            resolved_path = resolved_path.resolve()

            # Security check: ensure path is within working directory
            try:
                resolved_path.relative_to(self.working_directory.resolve())
            except ValueError:
                return KiloCodeToolResult(
                    output=f"Error: Access denied. Path is outside working directory: {search_path}",
                    exit_code=1,
                    error=f"Access denied: {search_path}",
                )

            if not resolved_path.exists():
                return KiloCodeToolResult(
                    output=f"Error: Path not found: {search_path}",
                    exit_code=1,
                    error=f"Path does not exist: {search_path}",
                )

            # Compile regex pattern
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return KiloCodeToolResult(
                    output=f"Error: Invalid regex pattern: {e}",
                    exit_code=1,
                    error=f"Invalid regex: {e}",
                )

            matches = []

            if resolved_path.is_file():
                # Search in single file
                matches.extend(await self._search_file(resolved_path, regex))
            else:
                # Search in directory
                if recursive:
                    pattern_glob = "**/*"
                else:
                    pattern_glob = "*"

                for file_path in resolved_path.glob(pattern_glob):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        try:
                            matches.extend(await self._search_file(file_path, regex))
                        except (UnicodeDecodeError, PermissionError):
                            # Skip binary files or files we can't read
                            continue

            if matches:
                output = "\n".join(matches)
            else:
                output = f"No matches found for pattern: {pattern}"

            return KiloCodeToolResult(
                output=output,
                exit_code=0,
                pattern=pattern,
                matches_count=len(matches),
            )

        except Exception as e:
            return KiloCodeToolResult(
                output=f"Error searching for pattern {pattern}: {e!s}",
                exit_code=1,
                error=str(e),
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

    async def _execute_use_mcp_tool(
        self, arguments: dict[str, Any]
    ) -> KiloCodeToolResult:
        """Execute use_mcp_tool (placeholder implementation)."""
        tool_name = arguments.get("tool_name")
        tool_arguments = arguments.get("arguments", "{}")

        # For now, return a placeholder response
        # In a full implementation, this would integrate with actual MCP servers
        return KiloCodeToolResult(
            output=f"MCP tool '{tool_name}' executed with arguments: {tool_arguments}",
            exit_code=0,
            tool_name=tool_name,
            note="MCP integration not yet implemented - this is a placeholder response",
        )

    async def _execute_completion_marker(
        self, arguments: dict[str, Any]
    ) -> KiloCodeToolResult:
        """Execute completion_marker tool."""
        result = arguments.get("result", "Task completed")

        return KiloCodeToolResult(
            output=f"[COMPLETION] {result}",
            exit_code=0,
            completion_result=result,
            marker_type="completion",
        )

    async def _execute_followup_marker(
        self, arguments: dict[str, Any]
    ) -> KiloCodeToolResult:
        """Execute followup_marker tool."""
        question = arguments.get("question", "Do you have any questions?")

        return KiloCodeToolResult(
            output=f"[FOLLOWUP] {question}",
            exit_code=0,
            followup_question=question,
            marker_type="followup",
        )
