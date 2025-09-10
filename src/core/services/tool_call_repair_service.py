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

    def __init__(self, max_buffer_bytes: int | None = None) -> None:
        self._tool_call_buffers: dict[str, str] = {}
        # Regex patterns for detecting tool calls in various formats
        # Pattern 1: JSON-like structure with "function_call" or "tool" keys
        # Changed `.*?` to `.*` to make it greedy for inner content.
        self.json_pattern = re.compile(
            r"(\{?\s*\"(function_call|tool)\":\s*\{.*\}\s*\})", re.DOTALL
        )
        # Pattern 2: Textual patterns like "TOOL CALL:" or "Function call:"
        self.text_pattern = re.compile(
            r"(?:TOOL CALL|Function call|Call)\s*:\s*(\w+)\s*(.*)", re.IGNORECASE
        )
        # Pattern 3: Code block with JSON inside (e.g., ```json { ... } ```)
        # Changed `.*?` to `.*` to make it greedy for inner content.
        self.code_block_pattern = re.compile(
            r"```(?:json)?\s*(\{.*\}\s*)\s*```",
            re.DOTALL,  # Added \s* before final } to match optional whitespace
        )

        # Cap per-session buffer to guard against pathological streams
        self._max_buffer_bytes: int = max_buffer_bytes or (64 * 1024)  # default 64 KB

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
            match = self.code_block_pattern.search(content)
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
            match = self.json_pattern.search(content)
            if match:
                return self._process_json_match(match.group(1))

        # Attempt to detect using textual patterns only if keywords present
        if (
            ("TOOL CALL" in content)
            or ("Function call" in content)
            or ("Call:" in content)
        ):
            match = self.text_pattern.search(content)
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
            # Attempt to parse arguments as JSON, fallback to string if not
            try:
                arguments = json.dumps(json.loads(args_string.strip()))
            except json.JSONDecodeError:
                arguments = json.dumps(
                    {"args": args_string.strip()}
                )  # Wrap as a simple JSON object

            return self._format_openai_tool_call(name, arguments)
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
