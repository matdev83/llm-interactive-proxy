"""
Tool sanitization for Gemini Code Assist API.

This module provides functionality for converting various tool formats
(OpenAI, Anthropic, custom) to Gemini's function_declarations format.
"""

import logging
from typing import Any

from src.connectors.gemini_base.models import GeminiFunctionDeclaration
from src.core.domain.translation import Translation

logger = logging.getLogger(__name__)


def extract_function_declarations(
    source_tools: list[Any],
) -> list[GeminiFunctionDeclaration]:
    """Extract Gemini function declarations from various tool formats.

    Supports multiple tool formats:
    1. OpenAI format: {"type": "function", "function": {"name": ..., "parameters": ...}}
    2. Anthropic/direct format: {"name": ..., "input_schema": ...}
    3. Direct format: {"name": ..., "description": ..., "parameters": ...}
    4. Custom nested format: {"type": "custom", "custom": {"input_schema": ...}}

    Args:
        source_tools: List of tools in any supported format.

    Returns:
        List of GeminiFunctionDeclaration models.
    """
    declarations: list[GeminiFunctionDeclaration] = []
    for tool in source_tools:
        tool_dict = tool if isinstance(tool, dict) else None
        if tool_dict is None and hasattr(tool, "model_dump"):
            try:
                tool_dict = tool.model_dump()  # type: ignore[attr-defined]
            except Exception:
                tool_dict = None
        if not isinstance(tool_dict, dict):
            continue

        # Try to extract function declaration from various formats
        name: str = ""
        description: str = ""
        params: dict[str, Any] = {}

        # Format 1: OpenAI standard format - {"type": "function", "function": {...}}
        function = tool_dict.get("function")
        if isinstance(function, dict):
            name = function.get("name", "")
            description = function.get("description", "")
            params = function.get("parameters", {})
        # Format 2: Anthropic/direct format - {"name": ..., "input_schema": ...}
        elif tool_dict.get("name"):
            name = tool_dict.get("name", "")
            description = tool_dict.get("description", "")
            # Support both "parameters" and "input_schema" keys
            params = tool_dict.get("parameters") or tool_dict.get("input_schema") or {}
        # Format 3: Custom nested format - {"type": "custom", "custom": {"input_schema": ...}}
        elif tool_dict.get("type") == "custom":
            custom_data = tool_dict.get("custom")
            if isinstance(custom_data, dict):
                # Try to extract name from custom data or use a generated name
                name = custom_data.get("name", "")
                description = custom_data.get("description", "")
                params = (
                    custom_data.get("input_schema")
                    or custom_data.get("parameters")
                    or {}
                )
            # Skip custom tools without extractable function info
            if not name:
                logger.debug(
                    "Skipping custom tool without name: %s",
                    str(tool_dict)[:200],
                )
                continue

        # Skip tools without a name (can't create valid function declaration)
        if not name:
            continue

        sanitized_params = (
            Translation._sanitize_gemini_parameters(params)
            if isinstance(params, dict)
            else {}
        )
        declarations.append(
            GeminiFunctionDeclaration(
                name=name,
                description=description,
                parameters=sanitized_params,
            )
        )
    return declarations


def salvage_existing_function_declarations(
    code_assist_request: dict[str, Any],
) -> list[GeminiFunctionDeclaration]:
    """Extract existing function declarations from a Code Assist request.

    Used as fallback when canonical request has no tools but the request
    already has some function declarations.

    Args:
        code_assist_request: The Code Assist API request body.

    Returns:
        List of GeminiFunctionDeclaration models.
    """
    declarations: list[GeminiFunctionDeclaration] = []
    existing_tools = code_assist_request.get("tools")
    if isinstance(existing_tools, list):
        for entry in existing_tools:
            fd_list = None
            if isinstance(entry, dict):
                fd_list = entry.get("function_declarations")
            if isinstance(fd_list, list):
                for fd in fd_list:
                    if isinstance(fd, dict):
                        declarations.append(GeminiFunctionDeclaration(**fd))
    return declarations


def filter_allowed_function_names(
    code_assist_request: dict[str, Any],
    declared_names: set[str],
) -> None:
    """Filter allowedFunctionNames in toolConfig to match declared functions.

    Modifies code_assist_request in place.

    Args:
        code_assist_request: The Code Assist API request body.
        declared_names: Set of function names that are declared.
    """
    tool_config = code_assist_request.get("toolConfig", {})
    if isinstance(tool_config, dict):
        fcc = tool_config.get("functionCallingConfig")
        if isinstance(fcc, dict):
            allowed = fcc.get("allowedFunctionNames")
            if isinstance(allowed, list):
                filtered = [n for n in allowed if n in declared_names]
                if filtered:
                    fcc["allowedFunctionNames"] = filtered
                else:
                    fcc.pop("allowedFunctionNames", None)


def sanitize_code_assist_tools(
    canonical_request: Any,
    code_assist_request: dict[str, Any],
) -> None:
    """Ensure only Gemini-compatible function tools are sent.

    This method handles various tool formats from different clients
    and converts them all to Gemini function_declarations format.

    Modifies code_assist_request in place.

    Args:
        canonical_request: The canonical request with tools attribute.
        code_assist_request: The Code Assist API request body to modify.
    """
    tools = getattr(canonical_request, "tools", None) or []

    function_declarations = extract_function_declarations(tools)

    # Fallback: if canonical_request had no tools, try to salvage existing declarations
    if not function_declarations:
        function_declarations = salvage_existing_function_declarations(
            code_assist_request
        )

    if function_declarations:
        code_assist_request["tools"] = [
            {
                "function_declarations": [
                    fd.model_dump() for fd in function_declarations
                ]
            }
        ]

        # Filter allowedFunctionNames to declared functions
        declared_names = {fd.name for fd in function_declarations}
        filter_allowed_function_names(code_assist_request, declared_names)
    else:
        code_assist_request.pop("tools", None)
        # If no tools, drop toolConfig entirely to avoid invalid references
        code_assist_request.pop("toolConfig", None)



__all__ = [
    "extract_function_declarations",
    "filter_allowed_function_names",
    "salvage_existing_function_declarations",
    "sanitize_code_assist_tools",
]
