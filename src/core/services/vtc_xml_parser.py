"""
VTC XML Parser - Parse and serialize XML tool calls for Virtual Tool Calling clients.

This module provides utilities to:
1. Parse XML tool calls from Cline-like clients into internal format
2. Serialize internal tool calls back to XML format

Supported formats:
- <function_calls><invoke name="..."><parameter name="...">...</parameter></invoke></function_calls>
- <tool_name><param_name>value</param_name></tool_name>
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from src.core.domain.chat import FunctionCall, ToolCall

logger = logging.getLogger(__name__)


class ParsedParameters(BaseModel):
    """Parsed tool call parameters from XML.

    This represents a structured result of parsing XML parameter
    elements, with typed field access instead of dict lookups.
    """

    def __getitem__(self, key: str) -> Any:
        """Allow dict-like access for backward compatibility."""
        return getattr(self, key, None)

    def get(self, key: str, default: Any = None) -> Any:
        """Allow dict-like get for backward compatibility."""
        return getattr(self, key, default)

    def items(self):
        """Allow dict-like items() for backward compatibility."""
        return self.model_dump(exclude_none=True, exclude_unset=True).items()

    def keys(self):
        """Allow dict-like keys() for backward compatibility."""
        return self.model_dump(exclude_none=True, exclude_unset=True).keys()

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


# Pre-compiled patterns for parse_vtc_xml cleanup operations
_EMPTY_FUNCTION_CALLS_PATTERN = re.compile(
    r"<function_calls>\s*</function_calls>", re.DOTALL
)
_FUNCTION_CALLS_TAG_PATTERN = re.compile(r"</?function_calls>", re.DOTALL)
_EXCESSIVE_NEWLINES_PATTERN = re.compile(r"\n{3,}")


def parse_vtc_xml(
    content: str, allowed_tools: list[str] | None = None
) -> tuple[list[ToolCall], str]:
    """
    Parse XML tool calls from content and return structured tool calls.

    This function extracts tool calls in two formats:
    1. Cline format: <function_calls><invoke name="...">...</invoke></function_calls>
    2. Simple format: <tool_name>...</tool_name>

    Args:
        content: The text content potentially containing XML tool calls.
        allowed_tools: Optional whitelist of tool names. If provided, only these
            tools will be extracted. If None, all detected tools are extracted.

    Returns:
        Tuple of (extracted_tool_calls, cleaned_content).
        - extracted_tool_calls: List of ToolCall objects
        - cleaned_content: Content with XML tool calls removed
    """
    if not content:
        return [], content

    tool_calls: list[ToolCall] = []
    cleaned = content

    # First, try to extract <function_calls><invoke>...</invoke></function_calls> format
    invoke_tool_calls, cleaned = _extract_invoke_format(cleaned, allowed_tools)
    tool_calls.extend(invoke_tool_calls)

    # Then, try to extract <tool_name>...</tool_name> format
    simple_tool_calls, cleaned = _extract_simple_format(cleaned, allowed_tools)
    tool_calls.extend(simple_tool_calls)

    # Clean up any remaining empty function_calls wrappers
    cleaned = _EMPTY_FUNCTION_CALLS_PATTERN.sub("", cleaned)
    cleaned = _FUNCTION_CALLS_TAG_PATTERN.sub("", cleaned)

    # Clean up excessive whitespace
    cleaned = _EXCESSIVE_NEWLINES_PATTERN.sub("\n\n", cleaned)
    cleaned = cleaned.strip()

    return tool_calls, cleaned


def _extract_invoke_format(
    content: str, allowed_tools: list[str] | None
) -> tuple[list[ToolCall], str]:
    """
    Extract tool calls in <invoke name="...">...</invoke> format.

    Args:
        content: Text content to parse.
        allowed_tools: Optional whitelist of tool names.

    Returns:
        Tuple of (tool_calls, cleaned_content).
    """
    tool_calls: list[ToolCall] = []
    cleaned = content

    # Pattern for <invoke name="...">...</invoke>
    # Handle optional namespace prefixes like "antml:tool:"
    invoke_pattern = r'<invoke\s+name="([^"]+)"[^>]*>(.*?)</invoke>'

    for match in re.finditer(invoke_pattern, content, re.DOTALL):
        full_match = match.group(0)
        tool_name_raw = match.group(1)
        params_xml = match.group(2)

        # Extract tool name (strip prefix like "antml:tool:" or "ClientControls:")
        tool_name = tool_name_raw
        if ":" in tool_name:
            tool_name = tool_name.split(":")[-1]

        # Check whitelist
        if allowed_tools is not None and tool_name not in allowed_tools:
            logger.debug("Skipping tool %s - not in allowed_tools whitelist", tool_name)
            continue

        # Parse parameters
        params = _parse_parameters(params_xml)

        tool_call = _create_tool_call(tool_name, params)
        tool_calls.append(tool_call)

        # Remove the matched invoke block from content
        cleaned = cleaned.replace(full_match, "", 1)

        logger.debug("Extracted invoke-format tool call: %s", tool_name)

    return tool_calls, cleaned


def _extract_simple_format(
    content: str, allowed_tools: list[str] | None
) -> tuple[list[ToolCall], str]:
    """
    Extract tool calls in <tool_name>...</tool_name> format.

    If allowed_tools is provided, only extracts matching tool names.
    If allowed_tools is None, uses structural heuristics to detect tool calls
    (XML blocks with snake_case names and child elements).

    Args:
        content: Text content to parse.
        allowed_tools: Optional whitelist of tool names.

    Returns:
        Tuple of (tool_calls, cleaned_content).
    """
    tool_calls: list[ToolCall] = []
    cleaned = content

    if allowed_tools is not None:
        # Whitelist mode: only extract specified tools
        for tool_name in allowed_tools:
            extracted, cleaned = _extract_simple_tool(cleaned, tool_name)
            tool_calls.extend(extracted)
    else:
        # Structural detection mode: find XML blocks that look like tool calls
        # Pattern: <snake_case_name>...<child>...</child>...</snake_case_name>
        # Common VTC tool name patterns: execute_command, read_file, write_to_file, etc.
        tool_pattern = r"<([a-z][a-z0-9_]*(?:_[a-z0-9]+)*)(?:\s[^>]*)?>(.+?)</\1>"

        for match in re.finditer(tool_pattern, content, re.DOTALL):
            full_match = match.group(0)
            potential_tool_name = match.group(1)
            inner_content = match.group(2)

            # Skip common non-tool XML tags
            skip_tags = {
                "thinking",
                "thought",
                "think",
                "plan",
                "planning",
                "memory",
                "memory_bank",
                "brain_dump",
                "context",
                "summary",
                "observation",
                "reflection",
                "note",
                "code",
                "pre",
                "div",
                "span",
                "p",
                "br",
                "hr",
                "ul",
                "ol",
                "li",
                "a",
                "b",
                "i",
                "em",
                "strong",
            }
            if potential_tool_name.lower() in skip_tags:
                continue

            # Must have child elements (parameters)
            if not re.search(r"<[^>]+>", inner_content):
                continue

            # Parse parameters from child elements
            params = _parse_simple_parameters(inner_content)

            if params:
                tool_call = _create_tool_call(potential_tool_name, params)
                tool_calls.append(tool_call)

                # Remove the matched block from content, add space to prevent word concatenation
                cleaned = cleaned.replace(full_match, " ", 1)

                logger.debug(
                    "Extracted simple-format tool call (structural): %s",
                    potential_tool_name,
                )

    return tool_calls, cleaned


def _extract_simple_tool(content: str, tool_name: str) -> tuple[list[ToolCall], str]:
    """
    Extract a specific tool from content in simple format.

    Args:
        content: Text content to parse.
        tool_name: The tool name to extract.

    Returns:
        Tuple of (tool_calls, cleaned_content).
    """
    tool_calls: list[ToolCall] = []
    cleaned = content

    # Pattern for <tool_name>...</tool_name>
    pattern = rf"<{re.escape(tool_name)}(?:\s[^>]*)?>(.+?)</{re.escape(tool_name)}>"

    for match in re.finditer(pattern, content, re.DOTALL):
        full_match = match.group(0)
        inner_content = match.group(1)

        # Check if inner content has child elements (parameters)
        if not re.search(r"<[^>]+>", inner_content):
            continue

        # Parse parameters from child elements
        params = _parse_simple_parameters(inner_content)

        if params:
            tool_call = _create_tool_call(tool_name, params)
            tool_calls.append(tool_call)

            # Remove the matched block from content
            cleaned = cleaned.replace(full_match, " ", 1)

            logger.debug("Extracted simple-format tool call: %s", tool_name)

    return tool_calls, cleaned


def _parse_parameters(params_xml: str) -> ParsedParameters:
    """
    Parse <parameter name="...">...</parameter> elements.

    Args:
        params_xml: XML string containing parameter elements.

    Returns:
        ParsedParameters object with parameter name -> value mapping.
    """
    params: dict[str, Any] = {}

    param_pattern = r'<parameter\s+name="([^"]+)"[^>]*>(.*?)</parameter>'
    for param_match in re.finditer(param_pattern, params_xml, re.DOTALL):
        param_name = param_match.group(1)
        param_value = param_match.group(2).strip()

        params[param_name] = _parse_param_value(param_value)

    return ParsedParameters(**params)


def _parse_simple_parameters(inner_content: str) -> ParsedParameters:
    """
    Parse <param_name>value</param_name> elements.

    Args:
        inner_content: XML string containing parameter elements.

    Returns:
        ParsedParameters object with parameter name -> value mapping.
    """
    params: dict[str, Any] = {}

    # Pattern for <param_name>value</param_name>
    param_pattern = r"<([a-zA-Z_][a-zA-Z0-9_]*)(?:\s[^>]*)?>(.+?)</\1>"

    for param_match in re.finditer(param_pattern, inner_content, re.DOTALL):
        param_name = param_match.group(1)
        param_value = param_match.group(2).strip()

        params[param_name] = _parse_param_value(param_value)

    return ParsedParameters(**params)


def _parse_param_value(value: str) -> Any:
    """
    Parse a parameter value, attempting type conversion.

    Args:
        value: Raw string value.

    Returns:
        Parsed value (JSON object, int, bool, or string).
    """
    # Try to parse as JSON if it looks like JSON
    if value.startswith(("{", "[")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            pass

    # Try integer
    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        try:
            return int(value)
        except ValueError:
            pass

    # Try boolean
    if value.lower() in ("true", "false"):
        return value.lower() == "true"

    return value


def _create_tool_call(
    tool_name: str, params: dict[str, Any] | ParsedParameters
) -> ToolCall:
    """
    Create a tool call in OpenAI format.

    Args:
        tool_name: Name of the tool/function.
        params: Dictionary of parameters.

    Returns:
        ToolCall object.
    """
    params_dict: dict[str, Any]
    if isinstance(params, ParsedParameters):
        params_dict = params.model_dump(exclude_none=True, exclude_unset=True)
    else:
        params_dict = params
    return ToolCall(
        id=f"vtc_{uuid.uuid4().hex[:12]}",
        type="function",
        function=FunctionCall(
            name=tool_name,
            arguments=json.dumps(params_dict),
        ),
    )


def serialize_tool_calls_to_xml(
    tool_calls: Sequence[ToolCall | dict[str, Any]],
) -> str:
    """
    Serialize internal tool calls to XML format for VTC clients.

    Produces Cline-compatible format:
    <function_calls>
    <invoke name="tool_name">
    <parameter name="param1">value1</parameter>
    </invoke>
    </function_calls>

    Args:
        tool_calls: List of tool calls (ToolCall objects or OpenAI format dicts).

    Returns:
        XML string representation of the tool calls.
    """
    if not tool_calls:
        return ""

    invoke_blocks: list[str] = []

    for tool_call in tool_calls:
        # Extract function info
        if isinstance(tool_call, ToolCall):
            tool_name = tool_call.function.name
            args_str = tool_call.function.arguments
        else:
            function = tool_call.get("function", {})
            tool_name = function.get("name", "unknown")
            args_str = function.get("arguments", "{}")

        # Parse arguments
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {}

        # Build parameter elements
        param_elements: list[str] = []
        for param_name, param_value in args.items():
            # Serialize value
            if isinstance(param_value, dict | list):
                value_str = json.dumps(param_value)
            elif isinstance(param_value, bool):
                value_str = str(param_value).lower()
            else:
                value_str = str(param_value)

            # Escape XML entities
            value_str = _escape_xml(value_str)

            param_elements.append(
                f'<parameter name="{param_name}">{value_str}</parameter>'
            )

        # Build invoke block
        params_xml = "\n".join(param_elements)
        if params_xml:
            invoke_block = f'<invoke name="{tool_name}">\n{params_xml}\n</invoke>'
        else:
            invoke_block = f'<invoke name="{tool_name}"></invoke>'

        invoke_blocks.append(invoke_block)

    # Wrap in function_calls
    invokes_xml = "\n".join(invoke_blocks)
    return f"<function_calls>\n{invokes_xml}\n</function_calls>"


def _escape_xml(text: str) -> str:
    """
    Escape special XML characters.

    Args:
        text: Text to escape.

    Returns:
        XML-safe text.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def has_partial_xml_pattern(text: str) -> bool:
    """
    Check if text contains a partial/incomplete XML tool call pattern.

    This is used for buffering in streaming mode - we want to buffer
    content if it looks like an XML tag is being formed but isn't complete yet.

    Args:
        text: Text to check.

    Returns:
        True if text contains partial XML pattern that might become a tool call.
    """
    if not text:
        return False

    # Check for unclosed tags
    # Look for < followed by tag content but no closing >
    if re.search(r"<[^>]*$", text):
        return True

    # Check for opening tag without matching close
    # Simple heuristic: look for <function_calls> or <invoke without </
    if "<function_calls>" in text and "</function_calls>" not in text:
        return True

    if "<invoke " in text:
        # Count opens vs closes
        opens = len(re.findall(r"<invoke\s", text))
        closes = len(re.findall(r"</invoke>", text))
        if opens > closes:
            return True

    # Check for simple format opening tags without matching close
    # Look for <snake_case_tool> patterns (e.g., <execute_command>, <read_file>)
    simple_opens = re.findall(r"<([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\s[^>]*)?>", text)
    for tag_name in simple_opens:
        close_tag = f"</{tag_name}>"
        if close_tag not in text:
            return True

    return False


def detect_complete_tool_call(text: str) -> bool:
    """
    Check if text contains at least one complete XML tool call.

    Args:
        text: Text to check.

    Returns:
        True if text contains a complete tool call pattern.
    """
    if not text:
        return False

    # Check for complete invoke format
    if re.search(r'<invoke\s+name="[^"]+">.*?</invoke>', text, re.DOTALL):
        return True

    # Check for complete function_calls block
    if re.search(r"<function_calls>.*?</function_calls>", text, re.DOTALL):
        return True

    # Check for complete simple format: <snake_case_tool>...<param>...</param>...</snake_case_tool>
    # Pattern matches tool-like tags (snake_case with underscore) that have child elements
    simple_pattern = (
        r"<([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?:\s[^>]*)?>(?=.*?<[^>]+>).*?</\1>"
    )
    return bool(re.search(simple_pattern, text, re.DOTALL))
