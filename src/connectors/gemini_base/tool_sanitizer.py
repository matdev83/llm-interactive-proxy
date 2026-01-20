"""
Tool sanitization for Gemini Code Assist API.

This module provides functionality for converting various tool formats
(OpenAI, Anthropic, custom) to Gemini's function_declarations format.
"""

import logging
import re
from typing import Any

from src.connectors.gemini_base.models import GeminiFunctionDeclaration
from src.core.domain.translation import Translation


def _coerce_properties_list(items: list[Any]) -> dict[str, Any] | None:
    mapped: dict[str, Any] = {}
    for item in items:
        if isinstance(item, dict):
            key = item.get("key") or item.get("name")
            if "value" in item:
                value = item.get("value")
            else:
                value = item.get("schema")
        elif isinstance(item, list | tuple) and len(item) == 2:
            key, value = item
        else:
            return None
        if not isinstance(key, str) or not key:
            return None
        mapped[key] = value
    return mapped


def _normalize_schema_properties(schema: Any) -> Any:
    if isinstance(schema, dict):
        normalized: dict[str, Any] = {}
        for key, value in schema.items():
            if key == "properties" and isinstance(value, list):
                coerced = _coerce_properties_list(value)
                if coerced is not None:
                    normalized[key] = {
                        prop_key: _normalize_schema_properties(prop_val)
                        for prop_key, prop_val in coerced.items()
                    }
                else:
                    normalized[key] = {}
                continue
            normalized[key] = _normalize_schema_properties(value)
        return normalized
    if isinstance(schema, list):
        return [_normalize_schema_properties(item) for item in schema]
    return schema


def _sanitize_parameters(params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        return {}
    normalized = _normalize_schema_properties(params)
    if not isinstance(normalized, dict):
        return {}
    result = Translation._sanitize_gemini_parameters(normalized)
    # #region agent log
    _log_path = r"c:\Users\Mateusz\source\repos\llm-interactive-proxy\.cursor\debug.log"
    import json as _json_debug
    # Check if this schema has $defs or $ref related fields
    _has_defs = "$defs" in str(params) or "definitions" in str(params) or "$ref" in str(params)
    if _has_defs:
        with open(_log_path, "a", encoding="utf-8") as _f:
            _f.write(_json_debug.dumps({"location": "tool_sanitizer.py:_sanitize_parameters", "message": "Schema with refs/defs detected", "data": {"input_preview": str(params)[:1500], "output_preview": str(result)[:1500]}, "timestamp": __import__("time").time(), "hypothesisId": "F"}) + "\n")
    # #endregion
    return result


logger = logging.getLogger(__name__)

_FUNCTION_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$")


def _is_valid_function_name(name: str) -> bool:
    return bool(_FUNCTION_NAME_RE.match(name))


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
            except Exception as e:
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Failed to serialize tool with model_dump(), skipping: type=%s, error: %s",
                        type(tool).__name__,
                        e,
                        exc_info=True,
                    )
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

        if not _is_valid_function_name(name):
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Skipping invalid function name for Gemini: %s", name)
            continue

        sanitized_params = _sanitize_parameters(params)
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
        # PERFORMANCE: Avoid model_dump() if already dict
        # Code Assist uses a list of tool blocks with function_declarations.
        normalized_declarations: list[dict[str, Any]] = []
        for fd in function_declarations:
            if isinstance(fd, dict):
                fd_dict = dict(fd)
            else:
                fd_dict = fd.model_dump()
            fd_dict["parameters"] = _sanitize_parameters(fd_dict.get("parameters", {}))
            normalized_declarations.append(fd_dict)

        code_assist_request["tools"] = [
            {"function_declarations": normalized_declarations}
        ]

        # Filter allowedFunctionNames to declared functions
        declared_names: set[str] = set()
        for fd in function_declarations:
            if isinstance(fd, dict):
                name = fd.get("name")  # type: ignore[assignment]
            else:
                name = fd.name
            if name:
                declared_names.add(name)
        filter_allowed_function_names(code_assist_request, declared_names)
    else:
        if logger.isEnabledFor(logging.DEBUG) and (
            "tools" in code_assist_request or "toolConfig" in code_assist_request
        ):
            logger.debug("Removing empty tools/toolConfig from Code Assist request")
        code_assist_request.pop("tools", None)
        # If no tools, drop toolConfig entirely to avoid invalid references
        code_assist_request.pop("toolConfig", None)


def normalize_code_assist_request_tools(request_body: dict[str, Any]) -> None:
    """Normalize tools in Code Assist request bodies before sending."""
    request_section = request_body.get("request")
    if not isinstance(request_section, dict):
        return

    tools = request_section.get("tools")
    if not isinstance(tools, list):
        return

    for entry in tools:
        if not isinstance(entry, dict):
            continue
        declarations = entry.get("function_declarations")
        if not isinstance(declarations, list):
            continue
        for fd in declarations:
            if not isinstance(fd, dict):
                continue
            params = fd.get("parameters", {})
            if (
                isinstance(params, dict)
                and isinstance(params.get("properties"), list)
                and logger.isEnabledFor(logging.DEBUG)
            ):
                logger.debug(
                    "Normalizing list-based tool properties for %s",
                    fd.get("name", "unknown"),
                )
            fd["parameters"] = _sanitize_parameters(params)


__all__ = [
    "extract_function_declarations",
    "filter_allowed_function_names",
    "salvage_existing_function_declarations",
    "sanitize_code_assist_tools",
    "normalize_code_assist_request_tools",
]
