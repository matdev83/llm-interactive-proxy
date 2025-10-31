from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class ToolCallRepairService:
    """
    A service to detect and repair tool calls embedded as text in LLM responses,
    converting them into a structured OpenAI-compatible tool_calls format.
    """

    # Pre-compiled regex patterns for performance optimization
    # These patterns are compiled once at class definition time instead of on every instance creation
    _JSON_PATTERN = re.compile(
        r"(\{?\s*\"(function_call|tool)\":\s*\{.*\}\s*\})", re.DOTALL
    )
    _TEXT_PATTERN = re.compile(
        r"(?:TOOL CALL|Function call|Call)\s*:\s*(\w+)\s*(.*)", re.IGNORECASE
    )
    _CODE_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\}\s*)\s*```", re.DOTALL)
    _XML_SNIPPET_PATTERN = re.compile(
        r"<([A-Za-z0-9_\-]+)(?:\s[^>]*)?>.*?</\1>", re.DOTALL
    )

    def __init__(self, max_buffer_bytes: int | None = None) -> None:
        self._tool_call_buffers: dict[str, str] = {}
        # Cap per-session buffer to guard against pathological streams
        self._max_buffer_bytes: int = max_buffer_bytes or (64 * 1024)  # default 64 KB

    @property
    def max_buffer_bytes(self) -> int:
        """Return the configured buffer cap in bytes."""

        return self._max_buffer_bytes

    def repair_tool_calls(self, response_content: str) -> dict[str, Any] | None:
        """
        Detects tool calls within the given response content (string) and converts
        them into an OpenAI-compatible tool_calls structure.

        Args:
            response_content: The string content of the LLM response.

        Returns:
            A dictionary representing the OpenAI-compatible tool_calls structure
            if a tool call is detected and successfully parsed, otherwise None.
        """
        if not response_content:
            return None

        # Fast-path checks to avoid expensive regex when not needed
        content = response_content

        # Attempt to detect using code block patterns only if backticks present
        if "```" in content:
            match = self._CODE_BLOCK_PATTERN.search(content)
            if match:
                return self._process_json_match(match.group(1))

        # Attempt to detect using JSON patterns only if likely keys present
        if '"function_call"' in content or '"tool"' in content:
            # Prefer fast balanced-object extraction over regex
            extracted = self._extract_json_object_near_key(content)
            if extracted:
                processed = self._process_json_match(extracted)
                if processed:
                    return processed
            # Fallback to regex if balanced extraction failed
            match = self._JSON_PATTERN.search(content)
            if match:
                return self._process_json_match(match.group(1))

        # Attempt to detect using XML patterns (Kilo MCP tool format)
        xml_tool_call = self._extract_xml_tool_call(content)
        if xml_tool_call:
            return xml_tool_call

        # Attempt to detect using textual patterns only if keywords present
        if (
            ("TOOL CALL" in content)
            or ("Function call" in content)
            or ("Call:" in content)
        ):
            match = self._TEXT_PATTERN.search(content)
            if match:
                return self._process_text_match(match.group(1), match.group(2))

        return None

    def _process_json_match(self, json_string: str) -> dict[str, Any] | None:
        """Helper to process a detected JSON string."""
        try:
            data = json.loads(json_string)
            if "function_call" in data and isinstance(data["function_call"], dict):
                return self._format_openai_tool_call(
                    data["function_call"].get("name") or "",  # Ensure name is str
                    data["function_call"].get("arguments"),
                )
            elif "tool" in data and isinstance(data["tool"], dict):
                return self._format_openai_tool_call(
                    data["tool"].get("name") or "",  # Ensure name is str
                    data["tool"].get("arguments"),
                )
            # Handle cases where the JSON is just the function call object directly
            elif "name" in data and "arguments" in data:
                return self._format_openai_tool_call(
                    data.get("name", ""), data["arguments"]
                )  # Ensure name is str
        except json.JSONDecodeError as e:
            logger.warning(
                f"Failed to decode JSON for tool call repair: {e}", exc_info=True
            )
        except KeyError as e:
            logger.warning(
                f"Missing expected key in JSON for tool call repair: {e}", exc_info=True
            )
        except TypeError as e:
            logger.warning(
                f"Type error while processing JSON for tool call repair: {e}",
                exc_info=True,
            )
        return None

    def _process_text_match(self, name: str, args_string: str) -> dict[str, Any] | None:
        """Helper to process a detected textual tool call."""
        try:
            # PERFORMANCE OPTIMIZATION: Avoid unnecessary JSON round-trip
            # Attempt to parse arguments as JSON, fallback to string if not
            stripped_args = args_string.strip()
            try:
                # Parse JSON to validate it, then use original string to avoid round-trip
                json.loads(stripped_args)
                arguments = (
                    stripped_args
                    if stripped_args.startswith(("{", "["))
                    else json.dumps({"args": stripped_args})
                )
            except json.JSONDecodeError:
                arguments = json.dumps(
                    {"args": stripped_args}
                )  # Wrap as a simple JSON object

            return self._format_openai_tool_call(name, arguments)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to encode arguments to JSON: {e}", exc_info=True)
        except (KeyError, TypeError) as e:
            logger.warning(f"Error processing text tool call match: {e}", exc_info=True)
        return None

    def _extract_json_object_near_key(self, text: str) -> str | None:
        """
        Attempt to extract a balanced JSON object that contains either
        "function_call" or "tool" key by scanning braces, ignoring braces within strings.

        This avoids expensive backtracking regex and is generally faster and more reliable
        for large buffers.
        """
        key_idx = text.find('"function_call"')
        if key_idx == -1:
            key_idx = text.find('"tool"')
        if key_idx == -1:
            return None

        # Find the opening '{' before the key
        start = key_idx
        while start >= 0 and text[start] != "{":
            start -= 1
        if start < 0:
            return None

        # Scan forward to find the matching '}' accounting for strings and escapes
        depth = 0
        in_string = False
        escape = False
        i = start
        while i < len(text):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start : i + 1]
            i += 1
        return None

    def _format_openai_tool_call(self, name: str, arguments: Any) -> dict[str, Any]:
        """Formats the detected tool call into an OpenAI-compatible structure."""
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        elif not isinstance(arguments, str):
            arguments = json.dumps(str(arguments))

        return {
            "id": f"call_{uuid4().hex}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }

    def _extract_xml_tool_call(self, content: str) -> dict[str, Any] | None:
        """Detect and convert XML-formatted tool calls."""
        stripped = content.strip()
        if not stripped.startswith("<") or "</" not in stripped:
            return None

        use_mcp_match = re.search(
            r"<use_mcp_tool(?:\s[^>]*)?>.*?</use_mcp_tool>", stripped, re.DOTALL
        )
        if use_mcp_match:
            candidate_snippets = [use_mcp_match.group(0)]
        else:
            matches = list(self._XML_SNIPPET_PATTERN.finditer(stripped))
            if not matches:
                return None
            candidate_snippets = [match.group(0) for match in matches]

        for xml_snippet in candidate_snippets:

            try:
                import xml.etree.ElementTree as ET

                root = ET.fromstring(xml_snippet)
            except Exception:
                continue

            if root.tag in {"tool_name", "tool_arguments"}:
                continue

            if root.tag == "use_mcp_tool":
                tool_name_element = root.find("tool_name")
                if tool_name_element is None or not tool_name_element.text:
                    continue
                arguments_element = root.find("tool_arguments")
                arguments = (
                    self._element_children_to_dict(arguments_element)
                    if arguments_element is not None
                    else {}
                )
                return self._format_openai_tool_call(
                    tool_name_element.text.strip(), arguments
                )

            arguments = self._element_children_to_dict(root)
            return self._format_openai_tool_call(root.tag, arguments)

        return None

    def _element_children_to_dict(self, element: Any) -> dict[str, Any] | str:
        """Convert XML element children into JSON-serializable objects."""
        if element is None:
            return {}

        children = list(element)
        text_content = element.text or ""

        if not children and not element.attrib:
            return text_content

        result: dict[str, Any] = {}

        if element.attrib:
            for attr, value in element.attrib.items():
                result[f"@{attr}"] = value

        if children:
            for child in children:
                child_value = self._element_children_to_dict(child)
                existing = result.get(child.tag)
                if existing is None:
                    result[child.tag] = child_value
                else:
                    if not isinstance(existing, list):
                        result[child.tag] = [existing]
                    result[child.tag].append(child_value)
        elif text_content:
            result["_text"] = text_content

        # Preserve meaningful mixed content
        if children and text_content.strip():
            result["_text"] = text_content

        if not result:
            return text_content

        if list(result.keys()) == ["_text"]:
            return result["_text"]

        return result
