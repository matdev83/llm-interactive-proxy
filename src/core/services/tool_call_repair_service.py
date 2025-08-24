from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from src.core.interfaces.response_processor_interface import ProcessedResponse

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
            logger.warning(f"Failed to decode JSON for tool call repair: {e}")
        except Exception as e:
            logger.warning(f"Error processing JSON tool call match: {e}")
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
        except Exception as e:
            logger.warning(f"Error processing text tool call match: {e}")
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

    async def process_chunk_for_streaming(
        self, chunk_content: str, session_id: str, is_final_chunk: bool = False
    ) -> AsyncGenerator[ProcessedResponse, None]:
        """
        Processes a single chunk of streaming text, attempting to extract and repair tool calls.
        Maintains an internal buffer per session.
        """
        current_buffer = self._tool_call_buffers.get(session_id, "")
        current_buffer += chunk_content
        # Apply buffer cap (keep last N bytes)
        if len(current_buffer) > self._max_buffer_bytes:
            current_buffer = current_buffer[-self._max_buffer_bytes :]

        while True:
            tool_call_match = None
            extracted_tool_call_str = None

            # Prioritize code block, then JSON, then text patterns with quick guards
            match = None
            if "```" in current_buffer:
                match = self.code_block_pattern.search(current_buffer)
            if not match and (
                '"function_call"' in current_buffer or '"tool"' in current_buffer
            ):
                # Try fast balanced-object extraction first
                extracted_obj = self._extract_json_object_near_key(current_buffer)
                if extracted_obj is not None:
                    # Synthesize a match-like behavior by locating this slice
                    start_idx = current_buffer.find(extracted_obj)
                    if start_idx != -1:

                        class _M:
                            def __init__(self, s: int, e: int, g: str) -> None:
                                self._s = s
                                self._e = e
                                self._g = g

                            def start(self) -> int:
                                return self._s

                            def end(self) -> int:
                                return self._e

                            def group(
                                self, _: int
                            ) -> str:  # pragma: no cover - simple shim
                                return self._g

                        match = _M(
                            start_idx, start_idx + len(extracted_obj), extracted_obj
                        )
                # Fallback to regex if needed
                if not match:
                    match = self.json_pattern.search(current_buffer)
            if not match and (
                "TOOL CALL" in current_buffer
                or "Function call" in current_buffer
                or "Call:" in current_buffer
            ):
                match = self.text_pattern.search(current_buffer)

            if match:
                tool_call_match = match
                extracted_tool_call_str = match.group(0)  # The full matched string

            if tool_call_match:
                # Found a potential tool call
                pre_match = current_buffer[: tool_call_match.start()]
                post_match = current_buffer[tool_call_match.end() :]

                # Yield any text before the tool call
                if pre_match:
                    yield ProcessedResponse(content=pre_match)

                # Try to repair the extracted tool call
                repaired = (
                    self.repair_tool_calls(extracted_tool_call_str)
                    if extracted_tool_call_str
                    else None
                )
                if repaired:
                    yield ProcessedResponse(content=json.dumps(repaired))
                else:
                    # If repair fails, yield the original extracted string
                    yield ProcessedResponse(
                        content=str(extracted_tool_call_str)
                    )  # Explicit cast to handle mypy

                current_buffer = post_match  # Update buffer to remaining text
                # Do not emit trailing text after a tool call; clear buffer
                current_buffer = ""
                break
            else:
                # No tool call found in current buffer
                if is_final_chunk:
                    # If it's the final chunk, yield everything remaining once
                    if current_buffer:
                        yield ProcessedResponse(content=current_buffer)
                    current_buffer = ""  # Clear buffer
                    # Important: break to avoid an infinite loop when buffer is empty
                    break
                else:
                    # If not final, keep the buffer for the next chunk
                    break  # Break from while loop, await next chunk

        # Final cap and persist per-session buffer
        if len(current_buffer) > self._max_buffer_bytes:
            current_buffer = current_buffer[-self._max_buffer_bytes :]
        self._tool_call_buffers[session_id] = current_buffer
