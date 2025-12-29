from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ElementTree
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

# Maximum JSON parse size to prevent DoS attacks (10MB)
MAX_JSON_PARSE_SIZE = 10 * 1024 * 1024  # 10MB in bytes


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
    # Include colon in tag names to support namespaced tags like
    # <ClientControls:run_terminal_command> used by Factory Droid
    _XML_SNIPPET_PATTERN = re.compile(
        r"<([A-Za-z0-9_\-:]+)(?:\s[^>]*)?>.*?</\1>", re.DOTALL
    )

    def __init__(self, max_buffer_bytes: int | None = None) -> None:
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

        # If tools are explicitly disallowed, skip detection entirely
        if allowed_tools is not None and len(allowed_tools) == 0:
            return None

        # Fast-path checks to avoid expensive regex when not needed
        content = response_content

        # Attempt to detect using code block patterns only if backticks present
        if "```" in content:
            match = self._CODE_BLOCK_PATTERN.search(content)
            if match:
                result = self._process_json_match(match.group(1), match.group(0))
                if result:
                    return result

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
                processed = self._process_json_match(match.group(1), match.group(0))
                if processed:
                    return processed

        # Attempt to detect using XML patterns (Kilo MCP tool format)
        # Only if the content contains obvious XML markers
        if "<" in content and "</" in content:
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
            # DoS protection: Check JSON size before parsing
            if len(json_string) > MAX_JSON_PARSE_SIZE:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Tool call JSON too large for repair (%d characters, limit: %d bytes)",
                        len(json_string),
                        MAX_JSON_PARSE_SIZE,
                    )
                return None

            json_size = len(json_string.encode("utf-8"))
            if json_size > MAX_JSON_PARSE_SIZE:
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "Tool call JSON too large for repair (%d bytes, limit: %d bytes)",
                        json_size,
                        MAX_JSON_PARSE_SIZE,
                    )
                return None

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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to decode JSON for tool call repair: {e}", exc_info=True
                )
        except KeyError as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Missing expected key in JSON for tool call repair: {e}",
                    exc_info=True,
                )
        except TypeError as e:
            if logger.isEnabledFor(logging.WARNING):
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
                # DoS protection: Check JSON size before parsing
                if len(stripped_args) > MAX_JSON_PARSE_SIZE:
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Tool call arguments too large for repair (%d characters, limit: %d bytes)",
                            len(stripped_args),
                            MAX_JSON_PARSE_SIZE,
                        )
                    arguments = json.dumps({"args": stripped_args})
                else:
                    args_size = len(stripped_args.encode("utf-8"))
                    if args_size > MAX_JSON_PARSE_SIZE:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Tool call arguments too large for repair (%d bytes, limit: %d bytes)",
                                args_size,
                                MAX_JSON_PARSE_SIZE,
                            )
                        arguments = json.dumps({"args": stripped_args})
                    else:
                        # Parse JSON to validate it, then use original string to avoid round-trip
                        json.loads(stripped_args)
                    # Parse JSON to validate it, then use original string to avoid round-trip
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
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Failed to encode arguments to JSON: {e}", exc_info=True
                )
        except (KeyError, TypeError) as e:
            if logger.isEnabledFor(logging.WARNING):
                logger.warning(
                    f"Error processing text tool call match: {e}", exc_info=True
                )
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
        """Detect and convert XML-formatted tool calls using structural heuristics.

        DESIGN PRINCIPLE: This method uses ONLY structural patterns and heuristics
        to identify tool calls. It does NOT rely on:
        - Hardcoded tool name lists
        - Client/agent identifiers
        - Any specific tool name enumeration

        This design ensures compatibility with ANY tool from ANY agent/client,
        including future tools that don't exist yet.

        Detection heuristics:
        1. XML elements with child elements (nested structure) = likely tool calls
        2. XML elements with attributes = likely tool calls
        3. XML elements containing JSON = likely tool calls
        4. Simple text-only elements = likely parameters, NOT tool calls
        5. Thinking/reasoning patterns = filtered out

        When allowed_tools is provided, ONLY those tools are detected - this enables
        transparent pass-through of client-specific formatting (like <brain_dump>).
        When allowed_tools is NOT provided, structural heuristics are used.
        """
        if "<" not in content or "</" not in content:
            return None

        candidate_snippets: list[str] = []

        # Build allowed set for whitelist matching (if provided)
        allowed_set: set[str] | None = None
        if allowed_tools:
            allowed_set = {t.lower() for t in allowed_tools}
            # Also add base names for namespaced tools (e.g., "run_cmd" for "Prefix:run_cmd")
            for t in allowed_tools:
                if ":" in t:
                    allowed_set.add(t.split(":")[-1].lower())

        if allowed_set and allowed_tools:
            # WHITELIST MODE: search ONLY for allowed tools
            for tool_name in allowed_tools:
                # Search for this specific tool (case-insensitive)
                pattern = (
                    rf"<{re.escape(tool_name)}(?:\s[^>]*)?>.*?</{re.escape(tool_name)}>"
                )
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match:
                    candidate_snippets.append(match.group(0))
            # Also search for namespaced versions (e.g., "Prefix:tool_name")
            for tool_name in allowed_tools:
                pattern = rf"<[A-Za-z0-9_\-]+:{re.escape(tool_name)}(?:\s[^>]*)?>.*?</[A-Za-z0-9_\-]+:{re.escape(tool_name)}>"
                match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
                if match and match.group(0) not in candidate_snippets:
                    candidate_snippets.append(match.group(0))
        else:
            # HEURISTIC MODE: search for any XML elements using structural heuristics
            generic_matches = list(self._XML_SNIPPET_PATTERN.finditer(content))
            # Sort by length (longest first) so outer wrappers like <apply_diff> are
            # evaluated before nested tags such as <content>.
            for match in sorted(
                generic_matches, key=lambda m: len(m.group(0)), reverse=True
            ):
                candidate_snippets.append(match.group(0))

        if not candidate_snippets:
            return None

        for xml_snippet in candidate_snippets:
            try:
                # Try parsing as-is first
                try:
                    root = ElementTree.fromstring(xml_snippet)
                except Exception as parse_err:
                    # If that fails, try escaping common invalid XML characters
                    # (e.g., unescaped & in text content like "Testing & Documentation")
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Initial XML parse failed, attempting sanitization: %s",
                            parse_err,
                            exc_info=True,
                        )
                    sanitized = self._sanitize_xml_for_parsing(xml_snippet)
                    root = ElementTree.fromstring(sanitized)
            except Exception:
                # Fallback to lenient parsing if XML parsing fails completely
                # Log this as it might indicate malformed XML that we're patching up
                if logger.isEnabledFor(logging.WARNING):
                    logger.warning(
                        "XML parsing failed, attempting lenient fallback", exc_info=True
                    )
                fallback = self._parse_lenient_tool_call(xml_snippet)
                if fallback:
                    return fallback
                continue

            # Use heuristics to determine if this is a tool call or not


            if not self._is_likely_tool_call(root, xml_snippet):
                continue

            # Skip plain <content> wrappers to avoid misclassifying diff bodies
            # as independent tool calls (e.g., inside <apply_diff>).
            if root.tag.lower() == "content":
                continue

            # Special handling for use_mcp_tool wrapper
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

                # Try to parse as JSON if arguments_raw is a string
                if not isinstance(arguments_raw, dict):
                    if arguments_raw.strip():
                        parsed: Any = None

                        try:

                            # DoS protection: Check JSON size before parsing
                            arg_str = arguments_raw.strip()
                            arg_size = len(arg_str.encode("utf-8"))
                            if arg_size > MAX_JSON_PARSE_SIZE:
                                if logger.isEnabledFor(logging.WARNING):
                                    logger.warning(
                                        "Tool call arguments too large for repair (%d bytes, limit: %d bytes)",
                                        arg_size,
                                        MAX_JSON_PARSE_SIZE,
                                    )
                                arguments_raw = {"content": arguments_raw}
                            else:
                                parsed = json.loads(arg_str)
                            if parsed is not None:
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

                # Unwrap double-nested content structures
                if isinstance(arguments_raw, dict):
                    arguments_raw = self._unwrap_nested_content(arguments_raw)
                # If not a dict, keep as is (will be handled by normalize_tool_arguments)

                # Ensure arguments_raw is a dict for normalize_tool_arguments
                # If it's a string, convert to dict format
                if isinstance(arguments_raw, str):
                    arguments_raw = {"content": arguments_raw}
                
                if not isinstance(arguments_raw, dict):
                    arguments_raw = {}

                arguments = self._normalize_tool_arguments(


                    tool_name_candidate,
                    arguments_raw,
                )
                return self._format_openai_tool_call(
                    tool_name_candidate, arguments, xml_snippet
                )

            # Direct tool call (not wrapped in use_mcp_tool)
            arguments_raw = self._element_children_to_dict(root)
            if not isinstance(arguments_raw, dict):
                arguments_raw = {"content": arguments_raw} if arguments_raw else {}

            # Restore namespace separator in tag name if it was sanitized
            # e.g., "ClientControls__NS__run_terminal_command" -> "ClientControls:run_terminal_command"
            tool_name = root.tag.replace("__NS__", ":")
            arguments = self._normalize_tool_arguments(tool_name, arguments_raw)
            return self._format_openai_tool_call(tool_name, arguments, xml_snippet)

        return None

    def _is_likely_tool_call(self, element: Any, xml_snippet: str) -> bool:
        """Determine if an XML element is likely a tool call using structural heuristics.

        DESIGN PRINCIPLE: This method uses PURELY STRUCTURAL heuristics.
        It does NOT rely on any hardcoded tool name lists.

        Tool calls have structure (children, attributes, JSON content, complex text).
        Parameters have simple values (paths, numbers, identifiers, short strings).

        Heuristic priority:
        1. Thinking/reasoning patterns -> NOT a tool call
        2. Has children -> IS a tool call (nested structure)
        3. Has attributes -> IS a tool call (structured data)
        4. Contains JSON -> IS a tool call (structured arguments)
        5. Contains multi-line/long text -> IS a tool call (complex content)
        6. Contains only simple value (path, number, short string) -> NOT a tool call

        Args:
            element: Parsed XML element
            xml_snippet: Original XML string

        Returns:
            True if the element appears to be a tool call, False otherwise
        """
        tag = element.tag.lower()

        # REJECT 1: Common thinking/reasoning tags (universal pattern)
        # These are well-known internal model monologue patterns
        # Other internal tags are handled by structural detection downstream
        thinking_patterns = {
            "think",
            "thought",
            "thinking",
            "reasoning",
            "reflection",
        }
        if tag in thinking_patterns:
            return False

        # ACCEPT: Elements with child elements (nested structure = tool call)
        children = list(element)
        if children:
            return True

        # ACCEPT: Elements with attributes (attributes = structured data = tool call)
        if element.attrib:
            return True

        # Check text content for elements without children
        text_content = (element.text or "").strip()

        # No content at all - ambiguous, but lean towards tool call for empty wrappers
        if not text_content:
            return True

        # ACCEPT: Elements containing JSON (arguments in JSON format)
        if text_content.startswith(("{", "[")):
            return True

        # ACCEPT: Elements with multi-line content (complex = tool call)
        if "\n" in text_content:
            return True

        # ACCEPT: Elements with substantial content (long = likely tool call)
        if len(text_content) > 500:
            return True

        # REJECT 2: Elements with ONLY simple value content
        # This is purely structural - if content is just a path, number, identifier,
        # or short string, it's almost certainly a parameter value, not a tool call.
        # This catches <command>ls</command>, <file>main.py</file>, <line>42</line>
        # regardless of the tag name.
        # DEFAULT: Accept as tool call if NOT a simple value
        return not self._looks_like_simple_value(text_content)

    def _looks_like_simple_value(self, text: str) -> bool:
        """Check if text looks like a simple parameter value using structural patterns.

        DESIGN PRINCIPLE: This method identifies parameter VALUES (not names)
        based on their structural characteristics. It does NOT rely on any
        hardcoded lists - only on patterns that distinguish simple values
        from complex tool call structures.

        Simple values include:
        - Empty or very short strings
        - Boolean-like values (true, false, yes, no)
        - Numbers (integers, floats)
        - File paths (Unix, Windows)
        - URLs
        - Single-word identifiers
        - Short command-like strings without special structure
        - Simple quoted strings

        Args:
            text: Text content to check

        Returns:
            True if the text appears to be a simple value (not a tool call body)
        """
        text = text.strip()

        # Empty or very short values are likely parameters
        if not text or len(text) < 3:
            return True

        # Boolean-like values
        if text.lower() in {"true", "false", "yes", "no", "on", "off", "null", "none"}:
            return True

        # Number-like values
        try:
            float(text)
            return True
        except ValueError:
            pass

        # Path-like values (Unix paths)
        if text.startswith(("/", "./", "../", "~/")):
            return True

        # Path-like values (Windows paths)
        if len(text) > 2 and text[1:3] in (":\\", ":/"):
            return True

        # File extensions (common file types)
        common_extensions = (
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".json",
            ".yaml",
            ".yml",
            ".toml",
            ".md",
            ".txt",
            ".html",
            ".css",
            ".xml",
            ".sh",
            ".bash",
            ".go",
            ".rs",
            ".java",
            ".c",
            ".cpp",
            ".h",
            ".rb",
            ".php",
        )
        if any(text.endswith(ext) for ext in common_extensions):
            return True

        # URL-like values (including custom schemes like resource://, file://, etc.)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", text):
            return True

        # Single-word identifiers (variable names, modes, etc.)
        if re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", text):
            return True

        # Hyphenated identifiers (like "my-project", "some-tool")
        if re.match(r"^[a-zA-Z][a-zA-Z0-9\-]*$", text):
            return True

        # Short words with common punctuation (like "Success!", "Yes?", "Done.")
        if len(text) < 50 and re.match(r"^[a-zA-Z][a-zA-Z0-9]*[!?.]*$", text):
            return True

        # Regex-like patterns (contain regex metacharacters)
        # These are clearly values, not tool call bodies
        if len(text) < 100 and re.match(r"^[\w.*+?^$\\|\[\]{}()-]+$", text):
            return True

        # Short single-line strings without XML/JSON markers
        # These are likely simple parameter values
        # Check for command-like patterns (e.g., "python -m pytest")
        return bool(
            len(text) < 200
            and "<" not in text
            and "{" not in text
            and "[" not in text
            and re.match(r"^[a-zA-Z0-9_./-]+(\s+[^\n<>{}\[\]]+)?$", text)
        )

    # Property last_tool_snippet removed as it is no longer needed

    def _sanitize_xml_for_parsing(self, xml_snippet: str) -> str:
        """Escape common invalid XML characters and handle namespace prefixes.

        XML requires certain characters to be escaped:
        - & must be &amp; (unless part of an entity reference)
        - < must be &lt; (unless starting a tag)
        - > should be &gt; (for symmetry, though only required in some contexts)

        Additionally, tags with namespace prefixes like <ClientControls:run_terminal_command>
        cause "unbound prefix" errors in ElementTree. We temporarily replace the colon
        with a placeholder to allow parsing.
        """
        # Only escape & that is NOT already part of an entity reference
        # Entity references look like: &name; or &#123; or &#x1F;
        # We use negative lookahead to avoid double-escaping
        result = re.sub(
            r"&(?!(?:amp|lt|gt|quot|apos|#[0-9]+|#x[0-9a-fA-F]+);)",
            "&amp;",
            xml_snippet,
        )

        # Handle namespace prefixes in tag names by replacing : with __NS__
        # This allows parsing without requiring namespace declarations
        # Pattern: <Prefix:TagName or </Prefix:TagName
        result = re.sub(
            r"<(/?)([A-Za-z0-9_]+):([A-Za-z0-9_]+)",
            r"<\1\2__NS__\3",
            result,
        )
        return result

    def _parse_lenient_tool_call(self, xml_snippet: str) -> ToolCallRepairResult | None:
        """Best-effort parser for malformed XML that still resembles tool calls."""
        snippet = xml_snippet.strip()
        if not snippet.startswith("<"):
            return None

        tag_match = re.match(r"<([A-Za-z0-9_\-:]+)", snippet)
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
                parsed: Any = None
                try:
                    # DoS protection: Check JSON size before parsing
                    args_size = len(args_content.encode("utf-8"))
                    if args_size > MAX_JSON_PARSE_SIZE:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Tool call arguments too large for repair (%d bytes, limit: %d bytes)",
                                args_size,
                                MAX_JSON_PARSE_SIZE,
                            )
                        arguments = {"content": args_content}
                    else:
                        # Try to parse as JSON first
                        parsed = json.loads(args_content)
                    if parsed is not None:
                        if isinstance(parsed, dict):
                            arguments = parsed
                        else:
                            arguments = {"content": parsed}
                except json.JSONDecodeError:
                    # Not valid JSON, use as raw content
                    arguments = {"content": args_content}
                # Unwrap double-nested content structures
                arguments = self._unwrap_nested_content(arguments)
        else:
            # Fallback: extract individual tags, but skip wrapper tags
            # Tags to skip: use_mcp_tool (outer wrapper), server_name (metadata),
            # tool_name/name (already extracted above)
            skip_tags = {"use_mcp_tool", "server_name", "tool_name", "name"}
            for match in re.finditer(
                r"<([A-Za-z0-9_\-:]+)>(.*?)</\1>", snippet, re.IGNORECASE | re.DOTALL
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
                # Special case: if key is "content" and value is a JSON string, try to parse it
                if key == "content" and isinstance(value, str):
                    stripped = value.strip()
                    if stripped.startswith("{") and stripped.endswith("}"):
                        parsed: Any = None
                        try:
                            # DoS protection: Check JSON size before parsing
                            stripped_size = len(stripped.encode("utf-8"))
                            if stripped_size > MAX_JSON_PARSE_SIZE:
                                if logger.isEnabledFor(logging.WARNING):
                                    logger.warning(
                                        "Content string too large for JSON parsing (%d bytes, limit: %d bytes)",
                                        stripped_size,
                                        MAX_JSON_PARSE_SIZE,
                                    )
                            else:
                                parsed = json.loads(stripped)
                            if (
                                parsed is not None
                                and isinstance(parsed, dict)
                                and parsed
                            ):
                                # Unwrap the nested JSON and add its keys directly
                                for inner_key, inner_value in parsed.items():
                                    if inner_key not in result:
                                        result[inner_key] = inner_value
                                continue
                        except json.JSONDecodeError:
                            pass  # Fall through to add as-is
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

    def _unwrap_nested_content(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Unwrap double-nested content structures from tool call arguments.

        Some models output malformed arguments like:
            {"content": "{\"file_path\": \"...\", \"patch_content\": \"...\"}"}

        This should be unwrapped to:
            {"file_path": "...", "patch_content": "..."}

        The issue occurs when models double-serialize their JSON arguments,
        resulting in a "content" wrapper containing a JSON string.

        Args:
            arguments: Dictionary of tool call arguments to potentially unwrap

        Returns:
            Unwrapped arguments dict, or original if no unwrapping needed
        """
        # Check for the specific pattern: {"content": "<json_string>"}
        # where <json_string> is a valid JSON object when parsed
        if (
            len(arguments) == 1


            and "content" in arguments
            and isinstance(arguments["content"], str)
        ):
            content_str = arguments["content"].strip()
            # Only try to parse if it looks like a JSON object
            if content_str.startswith("{") and content_str.endswith("}"):
                # DoS protection: Check input size before parsing
                content_size = len(content_str.encode("utf-8"))
                if content_size > MAX_JSON_PARSE_SIZE:
                    logger.warning(
                        "Content string too large for JSON parsing (%d bytes, limit: %d bytes). "
                        "Skipping unwrap to prevent DoS attack.",
                        content_size,
                        MAX_JSON_PARSE_SIZE,
                    )
                    return arguments

                try:
                    # DoS protection: Check JSON size before parsing
                    content_size = len(content_str.encode("utf-8"))
                    if content_size > MAX_JSON_PARSE_SIZE:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Content string too large for JSON parsing (%d bytes, limit: %d bytes)",
                                content_size,
                                MAX_JSON_PARSE_SIZE,
                            )
                        return arguments

                    parsed = json.loads(content_str)
                    if isinstance(parsed, dict) and parsed:
                        # Successfully unwrapped - log for debugging
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Unwrapped nested content structure: "
                                "{'content': '<json>'} -> %s keys",
                                len(parsed),
                            )
                        return parsed
                except json.JSONDecodeError:
                    pass  # Not valid JSON, keep original

        return arguments
