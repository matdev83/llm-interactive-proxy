"""Universal tool execution service for dynamic tool compatibility."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict

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

    def __init__(self, working_directory: str | None = None) -> None:
        """Initialize the universal tool executor.
        
        Args:
            working_directory: Base working directory for file operations
        """
        self.working_directory = Path(working_directory or os.getcwd())
        self.mcp_client = UniversalMCPClient()
        self._custom_tool_handlers: Dict[str, Callable] = {}
        self._register_built_in_handlers()

    def _register_built_in_handlers(self) -> None:
        """Register built-in tool handlers for common operations."""
        self._custom_tool_handlers.update({
            "read_file": self._execute_read_file,
            "list_dir": self._execute_list_dir,
            "list_files": self._execute_list_dir,  # Alias
            "grep_files": self._execute_grep_files,
            "codebase_search": self._execute_grep_files,  # Alias
            "search_files": self._execute_grep_files,  # Alias
            "completion_marker": self._execute_completion_marker,
            "attempt_completion": self._execute_completion_marker,  # Alias
            "followup_marker": self._execute_followup_marker,
            "ask_followup_question": self._execute_followup_marker,  # Alias
        })

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
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
            Dictionary containing the tool execution result
        """
        try:
            # 1. Check for custom registered handlers first
            if tool_name in self._custom_tool_handlers:
                handler = self._custom_tool_handlers[tool_name]
                return await handler(arguments)
            
            # 2. Check if it's an MCP tool from connected servers
            if self.mcp_client.is_mcp_tool(tool_name):
                return await self.mcp_client.execute_tool(tool_name, arguments)
            
            # 3. Handle generic MCP tool execution pattern
            if tool_name == "use_mcp_tool":
                return await self._execute_generic_mcp_tool(arguments)
            
            # 4. Unknown tool - return error
            return {
                "output": f"Unknown tool: {tool_name}",
                "exit_code": 1,
                "error": f"Tool '{tool_name}' is not available. Available tools: {self.get_available_tools()}"
            }
            
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}", exc_info=True)
            return {
                "output": f"Error executing {tool_name}: {str(e)}",
                "exit_code": 1,
                "error": str(e)
            }

    def register_tool_handler(self, tool_name: str, handler: Callable) -> None:
        """Register a custom tool handler.
        
        Args:
            tool_name: Name of the tool
            handler: Async function that takes arguments dict and returns result dict
        """
        self._custom_tool_handlers[tool_name] = handler
        logger.debug(f"Registered custom handler for tool: {tool_name}")

    def get_available_tools(self) -> list[str]:
        """Get list of all available tools.
        
        Returns:
            List of available tool names
        """
        available_tools = list(self._custom_tool_handlers.keys())
        available_tools.extend([tool.name for tool in self.mcp_client.get_available_tools()])
        return sorted(available_tools)

    async def connect_mcp_server(self, server_name: str, server_config: dict[str, Any]) -> bool:
        """Connect to an MCP server to make its tools available.
        
        Args:
            server_name: Unique name for the server
            server_config: Server configuration
            
        Returns:
            True if connection successful, False otherwise
        """
        return await self.mcp_client.connect_to_server(server_name, server_config)

    async def _execute_generic_mcp_tool(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a generic MCP tool via the use_mcp_tool pattern.
        
        This handles the KiloCode pattern: <use_mcp_tool tool_name="..." ...>
        """
        tool_name = arguments.get("tool_name")
        if not tool_name:
            return {
                "output": "Error: tool_name is required for use_mcp_tool",
                "exit_code": 1,
                "error": "Missing tool_name parameter"
            }

        # Extract tool arguments
        tool_arguments = arguments.get("arguments", {})
        if isinstance(tool_arguments, str):
            try:
                tool_arguments = json.loads(tool_arguments)
            except json.JSONDecodeError:
                # If it's not valid JSON, treat as raw string content
                tool_arguments = {"content": tool_arguments}

        # Add any other parameters as tool arguments
        for key, value in arguments.items():
            if key not in ["tool_name", "arguments"]:
                tool_arguments[key] = value

        # Execute the MCP tool
        return await self.mcp_client.execute_tool(tool_name, tool_arguments)

    async def _execute_read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute read_file tool."""
        file_path = arguments.get("file_path")
        if not file_path:
            return {
                "output": "Error: file_path is required",
                "exit_code": 1,
                "error": "Missing file_path parameter"
            }

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / file_path
            resolved_path = resolved_path.resolve()
            
            # Security check: ensure path is within working directory or its subdirectories
            try:
                resolved_path.relative_to(self.working_directory.resolve())
            except ValueError:
                # Allow reading files outside working directory for now (Codex behavior)
                # In production, you might want to restrict this
                pass

            if not resolved_path.exists():
                return {
                    "output": f"Error: File not found: {file_path}",
                    "exit_code": 1,
                    "error": f"File does not exist: {file_path}"
                }

            if not resolved_path.is_file():
                return {
                    "output": f"Error: Path is not a file: {file_path}",
                    "exit_code": 1,
                    "error": f"Path is not a file: {file_path}"
                }

            # Read file content
            content = resolved_path.read_text(encoding="utf-8", errors="replace")
            
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

            return {
                "output": content,
                "exit_code": 0,
                "file_path": str(resolved_path),
                "size": len(content)
            }

        except UnicodeDecodeError:
            return {
                "output": f"Error: Cannot read file as text (binary file?): {file_path}",
                "exit_code": 1,
                "error": "File appears to be binary or has encoding issues"
            }
        except PermissionError:
            return {
                "output": f"Error: Permission denied reading file: {file_path}",
                "exit_code": 1,
                "error": "Permission denied"
            }
        except Exception as e:
            return {
                "output": f"Error reading file {file_path}: {str(e)}",
                "exit_code": 1,
                "error": str(e)
            }

    async def _execute_list_dir(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute list_dir tool."""
        dir_path = arguments.get("dir_path", ".")
        recursive = arguments.get("recursive", False)
        include_hidden = arguments.get("include_hidden", False)

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / dir_path
            resolved_path = resolved_path.resolve()

            if not resolved_path.exists():
                return {
                    "output": f"Error: Directory not found: {dir_path}",
                    "exit_code": 1,
                    "error": f"Directory does not exist: {dir_path}"
                }

            if not resolved_path.is_dir():
                return {
                    "output": f"Error: Path is not a directory: {dir_path}",
                    "exit_code": 1,
                    "error": f"Path is not a directory: {dir_path}"
                }

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
            
            return {
                "output": output,
                "exit_code": 0,
                "directory": str(resolved_path),
                "count": len(entries)
            }

        except PermissionError:
            return {
                "output": f"Error: Permission denied accessing directory: {dir_path}",
                "exit_code": 1,
                "error": "Permission denied"
            }
        except Exception as e:
            return {
                "output": f"Error listing directory {dir_path}: {str(e)}",
                "exit_code": 1,
                "error": str(e)
            }

    async def _execute_grep_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute grep_files tool."""
        pattern = arguments.get("pattern")
        if not pattern:
            return {
                "output": "Error: pattern is required",
                "exit_code": 1,
                "error": "Missing pattern parameter"
            }

        search_path = arguments.get("path", ".")
        recursive = arguments.get("recursive", True)
        case_sensitive = arguments.get("case_sensitive", True)

        try:
            # Resolve path relative to working directory
            resolved_path = self.working_directory / search_path
            resolved_path = resolved_path.resolve()

            if not resolved_path.exists():
                return {
                    "output": f"Error: Path not found: {search_path}",
                    "exit_code": 1,
                    "error": f"Path does not exist: {search_path}"
                }

            # Compile regex pattern
            flags = 0 if case_sensitive else re.IGNORECASE
            try:
                regex = re.compile(pattern, flags)
            except re.error as e:
                return {
                    "output": f"Error: Invalid regex pattern: {e}",
                    "exit_code": 1,
                    "error": f"Invalid regex: {e}"
                }

            matches = []
            
            if resolved_path.is_file():
                # Search in single file
                matches.extend(self._search_file(resolved_path, regex))
            else:
                # Search in directory
                if recursive:
                    pattern_glob = "**/*"
                else:
                    pattern_glob = "*"
                
                for file_path in resolved_path.glob(pattern_glob):
                    if file_path.is_file() and not file_path.name.startswith("."):
                        try:
                            matches.extend(self._search_file(file_path, regex))
                        except (UnicodeDecodeError, PermissionError):
                            # Skip binary files or files we can't read
                            continue

            if matches:
                output = "\n".join(matches)
            else:
                output = f"No matches found for pattern: {pattern}"

            return {
                "output": output,
                "exit_code": 0,
                "pattern": pattern,
                "matches_count": len(matches)
            }

        except Exception as e:
            return {
                "output": f"Error searching for pattern {pattern}: {str(e)}",
                "exit_code": 1,
                "error": str(e)
            }

    def _search_file(self, file_path: Path, regex: re.Pattern[str]) -> list[str]:
        """Search for pattern in a single file."""
        matches = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
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

    async def _execute_completion_marker(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute completion_marker tool."""
        result = arguments.get("result", "Task completed")
        
        return {
            "output": f"[COMPLETION] {result}",
            "exit_code": 0,
            "completion_result": result,
            "marker_type": "completion"
        }

    async def _execute_followup_marker(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute followup_marker tool."""
        question = arguments.get("question", "Do you have any questions?")
        
        return {
            "output": f"[FOLLOWUP] {question}",
            "exit_code": 0,
            "followup_question": question,
            "marker_type": "followup"
        }

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

    async def cleanup(self) -> None:
        """Clean up resources and disconnect from MCP servers."""
        await self.mcp_client.disconnect_all()