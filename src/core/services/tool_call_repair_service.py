from __future__ import annotations

import json
import logging
import re
from typing import Any
from uuid import uuid4

from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
    ToolCallRepairResult,
)
from src.core.utils.message_processing_utils import (
    find_last_assistant_message,
    is_message_processed,
    mark_message_processed,
)

logger = logging.getLogger(__name__)


class ToolCallRepairService(IToolCallRepairService):
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

    def repair_tool_calls(
        self,
        response_content: str,
        force_reprocess: bool = False,
        allowed_tools: list[str] | None = None,
    ) -> ToolCallRepairResult | None:
        """
        Detects tool calls within the given response content (string) and converts
        them into an OpenAI-compatible tool_calls structure.

        Args:
            response_content: The string content of the LLM response.
            force_reprocess: If True, bypass processing marker checks and force
                           reprocessing. Useful for debugging scenarios.
            allowed_tools: Optional list of allowed tool names to prioritize during detection.

        Returns:
            A ToolCallRepairResult containing the parsed tool call and the original
            text snippet if a tool call is detected, otherwise None.
        """
        if not response_content:
            return None

        # Fast-path checks to avoid expensive regex when not needed
        content = response_content

        # Attempt to detect using code block patterns only if backticks present
        if "```" in content:
            match = self._CODE_BLOCK_PATTERN.search(content)
            if match:
                return self._process_json_match(match.group(1), match.group(0))

        # Attempt to detect using JSON patterns only if likely keys present
        if '"function_call"' in content or '"tool"' in content:
            # Prefer fast balanced-object extraction over regex
            extracted = self._extract_json_object_near_key(content)
            if extracted:
                processed = self._process_json_match(extracted, extracted)
                if processed:
                    return processed
            # Fallback to regex if balanced extraction failed
            match = self._JSON_PATTERN.search(content)
            if match:
                return self._process_json_match(match.group(1), match.group(0))

        # Attempt to detect using XML patterns (Kilo MCP tool format)
        xml_tool_call = self._extract_xml_tool_call(content, allowed_tools)
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
                return self._process_text_match(
                    match.group(1), match.group(2), match.group(0)
                )

        return None

    def repair_tool_calls_in_messages(
        self, messages: list[Any], force_reprocess: bool = False
    ) -> list[Any]:
        """
        Repair tool calls in a list of messages, skipping already processed ones.

        This method processes tool calls in messages while respecting processing
        markers to avoid redundant processing of historical messages. Only new
        messages (those without processing markers) will have their tool calls
        repaired.

        Args:
            messages: List of messages to process. Each message can be a dict
                     or an object with message attributes.
            force_reprocess: If True, bypass processing marker checks and force
                           reprocessing of all messages. Useful for debugging.

        Returns:
            List of messages with repaired tool calls. Historical messages are
            returned unchanged, while new messages have their tool calls repaired
            and are marked as processed.

        Examples:
            >>> service = ToolCallRepairService()
            >>> messages = [
            ...     {"role": "user", "content": "Hello"},
            ...     {"role": "assistant", "content": "Hi there"}
            ... ]
            >>> repaired = service.repair_tool_calls_in_messages(messages)
            >>> len(repaired) == 2
            True
        """
        if not messages:
            return []

        repaired_messages = []
        last_assistant_idx = find_last_assistant_message(messages)

        for idx, message in enumerate(messages):
            # Skip if already processed (unless forced)
            if not force_reprocess and is_message_processed(message):
                logger.log(
                    5, "Skipping tool call repair for already processed message"
                )  # TRACE level
                repaired_messages.append(message)
                continue

            # Get message role
            role = self._get_message_role(message)

            # Only process assistant messages
            if role != "assistant":
                repaired_messages.append(message)
                continue

            # Fallback: Only process last assistant message if no marker
            if (
                not force_reprocess
                and last_assistant_idx is not None
                and idx != last_assistant_idx
            ):
                logger.log(
                    5,
                    f"Skipping tool call repair for historical assistant message at index {idx}",
                )  # TRACE level
                repaired_messages.append(message)
                continue

            # Repair tool calls in this message
            repaired = self._repair_message_tool_calls(message, force_reprocess)

            # Mark as processed
            if not force_reprocess:
                mark_message_processed(repaired)
                logger.log(
                    5, f"Marked message at index {idx} as processed"
                )  # TRACE level

            repaired_messages.append(repaired)

        return repaired_messages

    def _get_message_role(self, message: Any) -> str | None:
        """Extract the role from a message (dict or object).

        Args:
            message: The message to extract role from.

        Returns:
            The role string, or None if not found.
        """
        if isinstance(message, dict):
            return message.get("role")
        return getattr(message, "role", None)

    def _repair_message_tool_calls(
        self, message: Any, force_reprocess: bool = False
    ) -> Any:
        """Repair tool calls within a single message.

        Args:
            message: The message to repair (dict or object).
            force_reprocess: If True, force reprocessing even if already processed.

        Returns:
            The message with repaired tool calls.
        """
        # Get message content
        if isinstance(message, dict):
            content = message.get("content", "")
            # Create a copy to avoid modifying the original
            repaired_message = dict(message)
        else:
            content = getattr(message, "content", "")
            # For objects, we'll modify in place (backward compatible)
            repaired_message = message

        if not content or not isinstance(content, str):
            return repaired_message

        # Attempt to repair tool calls
        result = self.repair_tool_calls(content, force_reprocess)

        if result:
            repaired_tool_call = result.tool_call
            # Add tool_calls to message if repair was successful
            if isinstance(repaired_message, dict):
                if "tool_calls" not in repaired_message:
                    repaired_message["tool_calls"] = []
                repaired_message["tool_calls"].append(repaired_tool_call)
            else:
                existing_tool_calls = getattr(repaired_message, "tool_calls", None)
                if existing_tool_calls is None:
                    repaired_message.tool_calls = [repaired_tool_call]
                else:
                    existing_tool_calls.append(repaired_tool_call)

        return repaired_message

    def _process_json_match(
        self, json_string: str, snippet: str
    ) -> ToolCallRepairResult | None:
        """Helper to process a detected JSON string."""
        try:
            data = json.loads(json_string)
            if "function_call" in data and isinstance(data["function_call"], dict):
                return self._format_openai_tool_call(
                    data["function_call"].get("name") or "",  # Ensure name is str
                    data["function_call"].get("arguments"),
                    snippet,
                )
            elif "tool" in data and isinstance(data["tool"], dict):
                return self._format_openai_tool_call(
                    data["tool"].get("name") or "",  # Ensure name is str
                    data["tool"].get("arguments"),
                    snippet,
                )
            # Handle cases where the JSON is just the function call object directly
            elif "name" in data and "arguments" in data:
                return self._format_openai_tool_call(
                    data.get("name", ""), data["arguments"], snippet
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

    def _process_text_match(
        self, name: str, args_string: str, snippet: str
    ) -> ToolCallRepairResult | None:
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

            return self._format_openai_tool_call(name, arguments, snippet)
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

    def _format_openai_tool_call(
        self, name: str, arguments: Any, snippet: str
    ) -> ToolCallRepairResult:
        """Formats the detected tool call into an OpenAI-compatible structure."""
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        elif not isinstance(arguments, str):
            arguments = json.dumps(str(arguments))

        tool_call = {
            "id": f"call_{uuid4().hex}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        }
        return ToolCallRepairResult(tool_call=tool_call, snippet=snippet)

    def _extract_xml_tool_call(
        self, content: str, allowed_tools: list[str] | None = None
    ) -> ToolCallRepairResult | None:
        """Detect and convert XML-formatted tool calls."""
        # Use content directly to ensure snippets match original text for removal
        if "<" not in content or "</" not in content:
            return None

        # Priority matching for known tool tags (to avoid matching inner tags like <command>)
        # Use allowed_tools if provided, otherwise fallback to known_tools
        target_tools = (
            allowed_tools
            if allowed_tools is not None
            else [
                "use_mcp_tool",
                "execute_command",
                "patch_file",
                "ask_followup_question",
                "attempt_completion",
                "read_file",
                "list_files",
                "codebase_search",
                "search_files",
                "access_mcp_resource",
            ]
        )

        candidate_snippets = []
        for tool_tag in target_tools:
            pattern = rf"<{tool_tag}(?:\s[^>]*)?>.*?</{tool_tag}>"
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                candidate_snippets.append(match.group(0))
                break  # Use first matching known tool

        # If no known tool matched, fall back to generic XML pattern
        if not candidate_snippets:
            matches = list(self._XML_SNIPPET_PATTERN.finditer(content))
            if not matches:
                return None
            candidate_snippets = [match.group(0) for match in matches]

        for xml_snippet in candidate_snippets:

            try:
                import xml.etree.ElementTree as ElementTree

                root = ElementTree.fromstring(xml_snippet)
            except Exception:
                fallback = self._parse_lenient_tool_call(xml_snippet)
                if fallback:
                    return fallback
                continue

            # Skip inner/child tags that are NOT actual tool calls
            # These are typically parameter tags inside tool calls
            if root.tag in {
                "tool_name",
                "tool_arguments",
                "path",
                "diff",
                "patch_content",
                "patch",
                "content",
                "arguments",
                "args",
                "command",  # Inner tag of <execute_command>
                "file",  # Inner tag of <read_file>, <write_to_file>
                "question",  # Inner tag of <ask_followup_question>
                "result",  # Inner tag of <attempt_completion>
                "regex",  # Inner tag of <search_files>
                "query",  # Inner tag of <codebase_search>
                "uri",  # Inner tag of <access_mcp_resource>
                "server_name",  # Inner tag of various MCP tools
                "directory",  # Inner tag of <list_files>
                "recursive",  # Inner tag of <list_files>
            }:
                continue

            if root.tag == "use_mcp_tool":
                tool_name_candidate = (
                    root.attrib.get("tool_name") or root.attrib.get("name") or ""
                )
                tool_name_element = root.find("tool_name")
                if not tool_name_candidate and tool_name_element is not None:
                    tool_name_candidate = tool_name_element.text or ""
                tool_name_candidate = tool_name_candidate.strip()
                if not tool_name_candidate:
                    continue

                arguments_element = None
                for candidate_tag in ("tool_arguments", "arguments", "args"):
                    arguments_element = root.find(candidate_tag)
                    if arguments_element is not None:
                        break

                if arguments_element is not None:
                    arguments_raw = self._element_children_to_dict(arguments_element)
                else:
                    arguments_raw = {}
                    for child in list(root):
                        if child.tag in {"tool_name", "name"}:
                            continue
                        arguments_raw[child.tag] = self._element_children_to_dict(child)

                # Try to parse as JSON if arguments_raw is a string (common KiloCode format)
                if not isinstance(arguments_raw, dict):
                    if isinstance(arguments_raw, str) and arguments_raw.strip():
                        try:
                            parsed = json.loads(arguments_raw.strip())
                            if isinstance(parsed, dict):
                                arguments_raw = parsed
                            else:
                                arguments_raw = {"content": parsed}
                        except json.JSONDecodeError:
                            arguments_raw = (
                                {"content": arguments_raw} if arguments_raw else {}
                            )
                    else:
                        arguments_raw = (
                            {"content": arguments_raw} if arguments_raw else {}
                        )

                arguments = self._normalize_tool_arguments(
                    tool_name_candidate,
                    arguments_raw,
                )
                return self._format_openai_tool_call(
                    tool_name_candidate, arguments, xml_snippet
                )

            arguments_raw = self._element_children_to_dict(root)
            if not isinstance(arguments_raw, dict):
                arguments_raw = {"content": arguments_raw} if arguments_raw else {}
            arguments = self._normalize_tool_arguments(root.tag, arguments_raw)
            return self._format_openai_tool_call(root.tag, arguments, xml_snippet)

        return None

    # Property last_tool_snippet removed as it is no longer needed

    def _parse_lenient_tool_call(self, xml_snippet: str) -> ToolCallRepairResult | None:
        """Best-effort parser for malformed XML that still resembles tool calls."""
        snippet = xml_snippet.strip()
        if not snippet.startswith("<"):
            return None

        tag_match = re.match(r"<([A-Za-z0-9_\-]+)", snippet)
        if not tag_match:
            return None

        root_tag = tag_match.group(1)
        if root_tag == "use_mcp_tool":
            return self._parse_lenient_use_mcp_tool(snippet)
        if root_tag == "patch_file":
            return self._parse_lenient_patch_file(snippet)
        return None

    def _parse_lenient_use_mcp_tool(self, snippet: str) -> ToolCallRepairResult | None:
        tool_name = None
        attr_match = re.search(
            r'(?:name|tool_name)\s*=\s*["\']([^"\']+)["\']', snippet, re.IGNORECASE
        )
        if attr_match:
            tool_name = attr_match.group(1).strip()
        else:
            element_match = re.search(
                r"<tool_name>(.*?)</tool_name>", snippet, re.IGNORECASE | re.DOTALL
            )
            if element_match:
                tool_name = element_match.group(1).strip()

        if not tool_name:
            return None

        # First, try to extract the <arguments> block and parse it as JSON
        # This handles the common KiloCode format: <arguments>{"key": "value"}</arguments>
        arguments: dict[str, Any] = {}
        args_match = re.search(
            r"<arguments>(.*?)</arguments>", snippet, re.IGNORECASE | re.DOTALL
        )
        if args_match:
            args_content = args_match.group(1).strip()
            if args_content:
                try:
                    # Try to parse as JSON first
                    parsed = json.loads(args_content)
                    if isinstance(parsed, dict):
                        arguments = parsed
                    else:
                        arguments = {"content": parsed}
                except json.JSONDecodeError:
                    # Not valid JSON, use as raw content
                    arguments = {"content": args_content}
        else:
            # Fallback: extract individual tags, but skip wrapper tags
            # Tags to skip: use_mcp_tool (outer wrapper), server_name (metadata),
            # tool_name/name (already extracted above)
            skip_tags = {"use_mcp_tool", "server_name", "tool_name", "name"}
            for match in re.finditer(
                r"<([A-Za-z0-9_\-]+)>(.*?)</\1>", snippet, re.IGNORECASE | re.DOTALL
            ):
                tag, value = match.groups()
                if tag.lower() in skip_tags:
                    continue
                arguments[tag] = self._sanitize_extracted_text(value)

        return self._format_openai_tool_call(tool_name, arguments, snippet)

    def _parse_lenient_patch_file(self, snippet: str) -> ToolCallRepairResult | None:
        arguments: dict[str, Any] = {}

        path_match = re.search(
            r"<path>(.*?)</path>", snippet, re.DOTALL | re.IGNORECASE
        )
        if path_match:
            arguments["path"] = self._sanitize_extracted_text(path_match.group(1))

        for tag in ("diff", "patch", "patch_content", "content"):
            match = re.search(
                rf"<{tag}>(.*?)</{tag}>", snippet, re.DOTALL | re.IGNORECASE
            )
            if match:
                arguments[tag] = self._sanitize_extracted_text(match.group(1))

        if not arguments:
            return None

        return self._format_openai_tool_call("patch_file", arguments, snippet)

    def _sanitize_extracted_text(self, value: str) -> str:
        text = value.strip()
        if text.startswith("<![CDATA[") and text.endswith("]]>"):
            text = text[9:-3]
        return text.strip()

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
            return result["_text"]  # type: ignore

        return result

    def _normalize_tool_arguments(
        self,
        tool_name: str,  # - kept for API compatibility
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply generic normalization to extracted XML arguments.

        This method flattens nested XML structures generically, without
        hardcoding any specific tool names. The goal is to transform
        deeply nested structures into flat key-value pairs that clients expect.

        Args:
            tool_name: Name of the tool (unused, kept for API compatibility)
            arguments: Dictionary of arguments extracted from XML
            context_element: XML element context (unused, kept for API compatibility)

        Returns:
            Flattened dictionary of arguments
        """
        result: dict[str, Any] = {}
        self._extract_leaf_values(arguments, result)
        return result

    def _extract_leaf_values(self, obj: dict[str, Any], result: dict[str, Any]) -> None:
        """Recursively extract leaf values from nested dicts.

        For each leaf value (non-dict), use its key as the result key.
        This flattens arbitrarily nested structures while preserving
        meaningful key names.

        Transforms structures like:
        - {"args": {"file": {"path": "X"}}} -> {"path": "X"}
        - {"args": {"command": "ls"}} -> {"command": "ls"}
        - {"file": {"path": "X", "diff": {"content": "Y"}}} -> {"path": "X", "diff": "Y"}

        Special case: if a dict has exactly ONE child with a generic wrapper key
        like "content", "_text", or "text", use the parent key instead.
        """
        # Generic wrapper keys that should be replaced by their parent key
        wrapper_keys = {"content", "_text", "text", "value", "data"}

        for key, value in obj.items():
            # Skip wrapper keys that don't add semantic meaning
            if key in ("args", "arguments", "tool_arguments"):
                if isinstance(value, dict):
                    self._extract_leaf_values(value, result)
                continue

            if isinstance(value, dict):
                # Check if this dict has exactly one child with a wrapper key
                # e.g., {"diff": {"content": "..."}} -> use "diff" as key
                if len(value) == 1:
                    inner_key, inner_value = next(iter(value.items()))
                    if inner_key in wrapper_keys and not isinstance(inner_value, dict):
                        # Use parent key instead of wrapper key
                        if key not in result:
                            result[key] = inner_value
                        continue

                # Check if this dict has any non-dict values (leaves)
                has_leaves = any(not isinstance(v, dict) for v in value.values())
                has_nested = any(isinstance(v, dict) for v in value.values())

                if has_leaves:
                    # Extract leaf values from this dict
                    for inner_key, inner_value in value.items():
                        # Use the inner key (more specific) if not already present
                        if (
                            not isinstance(inner_value, dict)
                            and inner_key not in result
                        ):
                            result[inner_key] = inner_value

                if has_nested:
                    # Recursively process nested dicts
                    for inner_key, inner_value in value.items():
                        if isinstance(inner_value, dict):
                            self._extract_leaf_values({inner_key: inner_value}, result)
            else:
                # Leaf value - add directly
                if key not in result:
                    result[key] = value

    def _find_first_text(self, element: Any, tag_names: tuple[str, ...]) -> str | None:
        """Find the first non-empty text for any of the provided tag names."""
        if element is None:
            return None

        for tag in tag_names:
            found = element.find(f".//{tag}")
            if found is not None:
                text = self._collect_element_text(found)
                if text:
                    return text
        return None

    def _collect_element_text(self, element: Any) -> str:
        """Collect text content from an XML element, including nested nodes."""
        parts: list[str] = []
        if element.text:
            parts.append(element.text)
        for child in list(element):
            child_text = self._collect_element_text(child)
            if child_text:
                parts.append(child_text)
            if child.tail:
                parts.append(child.tail)
        return "".join(parts).strip()
