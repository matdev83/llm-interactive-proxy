"""Codex tool schema definitions.

This module contains the built-in tool schemas for OpenAI Codex connector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.connectors.openai_codex.contracts import CodexToolSchema

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


def get_codex_tool_schema(tool_name: str) -> CodexToolSchema | None:
    """Return a registered Codex tool schema, if available.

    Args:
        tool_name: Name of the tool to retrieve

    Returns:
        CodexToolSchema instance, or None if not found
    """
    from src.connectors.openai_codex.contracts import CodexToolSchema

    schema_dict = CODEX_TOOL_SCHEMAS.get(tool_name)
    if not schema_dict:
        return None

    # Support both flat and OpenAI-style nested structures
    name = schema_dict.get("name")
    description = schema_dict.get("description")
    parameters = schema_dict.get("parameters", {})
    tool_type = schema_dict.get("type", "function")

    if not name and "function" in schema_dict:
        func = schema_dict["function"]
        name = func.get("name")
        description = func.get("description")
        parameters = func.get("parameters", {})

    if not name:
        return None

    return CodexToolSchema(
        name=str(name),
        description=str(description) if description else None,
        parameters=dict(parameters) if parameters else {},
        type=str(tool_type) if tool_type else "function",
    )

