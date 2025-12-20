"""Codex tool schema definitions.

This module contains the built-in tool schemas for OpenAI Codex connector.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Built-in Codex tool schemas
CODEX_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "read_file": {
        "type": "function",
        "name": "read_file",
        "function": {
            "name": "read_file",
            "description": "Read a file from the project workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Alias for path maintained for compatibility",
                    },
                    "start_line": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Optional starting line (0-indexed)",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Optional ending line (exclusive, 0-indexed)",
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    "list_dir": {
        "type": "function",
        "name": "list_dir",
        "function": {
            "name": "list_dir",
            "description": "List files in a directory within the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                    },
                    "dir_path": {
                        "type": "string",
                        "description": "Alias for path maintained for compatibility",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to list directories recursively",
                    },
                    "depth": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Maximum recursion depth when recursive is true",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    "grep_files": {
        "type": "function",
        "name": "grep_files",
        "function": {
            "name": "grep_files",
            "description": "Search across files in the workspace using a pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Search pattern or query",
                    },
                    "path": {
                        "type": "string",
                        "description": "Optional base path for the search",
                    },
                    "include": {
                        "type": "string",
                        "description": "Glob pattern to include specific files",
                    },
                    "exclude": {
                        "type": "string",
                        "description": "Glob pattern to exclude files",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "Whether to search recursively",
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether the pattern is case-sensitive",
                    },
                },
                "required": ["pattern"],
                "additionalProperties": False,
            },
        },
    },
}


def get_codex_tool_schema(tool_name: str) -> dict[str, Any] | None:
    """Return a deep copy of the registered Codex tool schema, if available.

    Args:
        tool_name: Name of the tool to retrieve

    Returns:
        Deep copy of the tool schema dict, or None if not found
    """
    schema = CODEX_TOOL_SCHEMAS.get(tool_name)
    return deepcopy(schema) if schema else None
