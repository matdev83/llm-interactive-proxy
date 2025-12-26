"""Tool schema resolver for OpenAI Codex connector.

This module provides tool schema resolution with collision handling and format normalization.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from src.connectors.openai_codex.contracts import (
    CodexConnectorSettings,
    CodexRequestContext,
    CodexToolSchema,
)
from src.connectors.openai_codex.interfaces import (
    IToolExecutionService,
    IToolSchemaResolver,
)

logger = logging.getLogger(__name__)


class ToolSchemaResolver(IToolSchemaResolver):
    """Service for resolving tool schemas and handling collisions.

    Handles three schema modes: custom_only, merge_custom, codex_default.
    Implements collision detection using parameter signature comparison.
    """

    def __init__(
        self,
        settings: CodexConnectorSettings,
        tool_execution_service: IToolExecutionService | None = None,
        default_tools_provider: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        """Initialize the tool schema resolver.

        Args:
            settings: Connector settings containing custom tool schema defaults
            tool_execution_service: Service for executing tools (optional)
            default_tools_provider: Callable that returns default tool schemas (deprecated)
        """
        self._settings = settings
        self._tool_execution_service = tool_execution_service
        self._default_tools_provider = default_tools_provider

    def _get_default_tools(self) -> list[CodexToolSchema]:
        """Get the default tools from execution service and built-ins."""
        if self._default_tools_provider:
            # Maintain backward compatibility with deprecated provider returning dicts
            tools_dicts = self._default_tools_provider()
            return self._dict_tools_to_schemas(tools_dicts)

        from src.connectors.openai_codex.tool_schemas import get_codex_tool_schema

        tools: list[CodexToolSchema] = [
            CodexToolSchema(
                type="function",
                name="shell",
                description="Runs a shell command and returns its output.",
                parameters={
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "The command to execute",
                        },
                        "workdir": {
                            "type": "string",
                            "description": "The working directory to execute the command in",
                        },
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            ),
            CodexToolSchema(
                type="custom",
                name="apply_patch",
                description="Use the apply_patch tool to edit files using unified diff syntax.",
                format={
                    "type": "grammar",
                    "syntax": "lark",
                    "definition": (
                        "start: begin_patch hunk+ end_patch\n"
                        'begin_patch: "*** Begin Patch" LF\n'
                        'end_patch: "*** End Patch" LF?\n\n'
                        "hunk: add_hunk | delete_hunk | update_hunk\n"
                        'add_hunk: "*** Add File: " filename LF add_line+\n'
                        'delete_hunk: "*** Delete File: " filename LF\n'
                        'update_hunk: "*** Update File: " filename LF change_move? change?\n\n'
                        "filename: /(.+)/\n"
                        'add_line: "+" /(.*)/ LF -> line\n\n'
                        'change_move: "*** Move to: " filename LF\n'
                        "change: (change_context | change_line)+ eof_line?\n"
                        'change_context: ("@@" | "@@ " /(.+)/) LF\n'
                        'change_line: ("+" | "-" | " ") /(.*)/ LF\n'
                        'eof_line: "*** End of File" LF\n\n'
                        "%import common.LF\n"
                    ),
                },
            ),
            CodexToolSchema(
                type="function",
                name="view_image",
                description="Attach a local image (by filesystem path) to the conversation context for this turn.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Local filesystem path to an image file",
                        }
                    },
                    "required": ["path"],
                    "additionalProperties": False,
                },
            ),
        ]

        for tool_name in ("read_file", "list_dir", "grep_files"):
            schema = get_codex_tool_schema(tool_name)
            if schema:
                tools.append(schema)

        if self._tool_execution_service:
            try:
                universal_tool_schemas = (
                    self._tool_execution_service.get_available_tool_schemas()
                )
                tools.extend(self._dict_tools_to_schemas(universal_tool_schemas))
            except Exception as e:
                logger.warning("Failed to get universal tool schemas: %s", e)

        return tools

    def resolve_tool_schema(
        self, context: CodexRequestContext
    ) -> list[CodexToolSchema]:
        """Resolve tool schemas and handle collisions.

        Args:
            context: Request context with tools and capabilities

        Returns:
            List of resolved tool schemas
        """
        schema_mode = context.capabilities.tool_schema_mode or "codex_default"
        default_tools = self._get_default_tools()

        # Extract custom tools from request
        custom_tools_req = getattr(context.request, "tools", []) or []
        custom_tools: list[dict[str, Any]] = []

        for tool in custom_tools_req:
            # Convert tool to dict if needed
            if hasattr(tool, "model_dump"):
                tool_dict = tool.model_dump(exclude_none=True)
            elif isinstance(tool, dict):
                tool_dict = dict(tool)
            else:
                continue

            # Handle both formats:
            # - Codex format: {"name": "tool_name", "type": "function", ...}
            # - OpenAI format: {"type": "function", "function": {"name": "tool_name", ...}}
            name_value = tool_dict.get("name")
            if not name_value and isinstance(tool_dict.get("function"), dict):
                name_value = tool_dict["function"].get("name")
                # Normalize OpenAI format to Codex format
                if "name" not in tool_dict:
                    tool_dict["name"] = name_value
                # Move function properties to top level
                function_dict = tool_dict.pop("function", {})
                tool_dict.update(function_dict)

            if isinstance(name_value, str) and name_value.strip():
                custom_tools.append(tool_dict)
            else:
                logger.debug(
                    "Ignoring tool without valid name in request payload: %s", tool
                )

        # Merge custom tool schema defaults from settings
        custom_tool_schema_default = (
            self._settings.tool_schema.get("custom_tools") or []
        )
        if custom_tool_schema_default:
            existing_names = {
                t.get("name") for t in custom_tools if isinstance(t.get("name"), str)
            }
            for tool in custom_tool_schema_default:
                name_value = tool.get("name")
                if isinstance(name_value, str) and name_value not in existing_names:
                    custom_tools.append(deepcopy(tool))

        # Handle schema modes
        if schema_mode == "custom_only":
            # Return custom tools directly (matching original behavior)
            return self._dict_tools_to_schemas(
                [deepcopy(tool) for tool in custom_tools]
            )

        if schema_mode == "merge_custom":
            if not custom_tools:
                return self._dict_tools_to_schemas(default_tools)

            merged_tools: dict[str, CodexToolSchema | dict[str, Any]] = {}
            # Track parameter signatures to detect collisions
            tool_signatures: dict[str, str] = {}

            # Add default tools first
            for tool in default_tools:
                if isinstance(tool, CodexToolSchema):
                    name_value = tool.name
                    params = tool.parameters
                else:
                    name_value = tool.get("name")
                    params = tool.get("parameters", {})

                if isinstance(name_value, str):
                    merged_tools[name_value] = deepcopy(tool)
                    # Create signature from parameters for collision detection
                    tool_signatures[name_value] = json.dumps(params, sort_keys=True)

            # Merge custom tools with collision detection
            for tool in custom_tools:
                if isinstance(tool, CodexToolSchema):
                    name_value = tool.name
                    params = tool.parameters
                else:
                    name_value = tool.get("name")
                    params = tool.get("parameters", {})

                if isinstance(name_value, str):
                    # Check for parameter collision
                    if name_value in merged_tools:
                        new_sig = json.dumps(params, sort_keys=True)
                        if new_sig != tool_signatures.get(name_value):
                            if logger.isEnabledFor(logging.WARNING):
                                logger.warning(
                                    "Tool schema collision: tool '%s' defined with different parameters. "
                                    "Keeping default definition. Custom parameters: %s",
                                    name_value,
                                    json.dumps(params)[:200],
                                )
                            continue  # Keep default, skip custom
                    # No collision or same parameters - merge (custom overwrites)
                    merged_tools[name_value] = deepcopy(tool)
                    tool_signatures[name_value] = json.dumps(params, sort_keys=True)

            return self._dict_tools_to_schemas(list(merged_tools.values()))

        # Default: codex_default mode
        return self._dict_tools_to_schemas(default_tools)

    @staticmethod
    def _dict_tools_to_schemas(
        tools: Sequence[dict[str, Any] | CodexToolSchema],
    ) -> list[CodexToolSchema]:
        """Convert tool schemas to CodexToolSchema instances.

        Args:
            tools: List of tool dictionaries or models

        Returns:
            List of CodexToolSchema instances
        """
        schemas: list[CodexToolSchema] = []
        for tool in tools:
            if isinstance(tool, CodexToolSchema):
                schemas.append(tool)
                continue

            if isinstance(tool, dict):
                tool_dict = deepcopy(tool)
            elif isinstance(tool, BaseModel):
                tool_dict = tool.model_dump(mode="python")
            else:
                continue

            # Remove fields that are explicitly passed as keyword arguments
            name = tool_dict.pop("name", None)
            if not isinstance(name, str):
                continue

            description = tool_dict.pop("description", None)
            tool_type = tool_dict.pop("type", "function")
            parameters = tool_dict.pop("parameters", {})

            # Any remaining fields go into 'extra' via model_construct or **kwargs
            schemas.append(
                CodexToolSchema(
                    name=name,
                    description=description if isinstance(description, str) else None,
                    type=tool_type if isinstance(tool_type, str) else "function",
                    parameters=parameters if isinstance(parameters, dict) else {},
                    **tool_dict,
                )
            )
        return schemas
