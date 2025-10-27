from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.core.commands.tool_call_text_parser import (
    TextToolResult,
    parse_textual_tool_invocation,
    parse_textual_tool_result,
)

if TYPE_CHECKING:
    from src.connectors.openai_codex import OpenAICodexConnector


logger = logging.getLogger(__name__)


class CodexRequestTranslator:
    """Translates a canonical chat request into Codex-specific input items."""

    def __init__(self, connector: OpenAICodexConnector) -> None:
        self._connector = connector

    def build_input_items(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        capabilities: CodexClientCapabilities,
    ) -> list[dict[str, Any]]:
        """Transform processed messages into Codex Responses `input` array."""
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Building Codex input items (protocol=%s, tool_text_format=%s)",
                capabilities.protocol,
                capabilities.tool_text_format,
            )
        input_items: list[dict[str, Any]] = []

        # System prompt handling is now centralized in `_resolve_system_prompt`,
        # so we no longer inject user instructions here.
        # The loop over processed_messages will skip any 'system' role messages.

        if capabilities.include_environment_context:
            env_block = self._connector._build_environment_context_block(
                request_data, effective_model
            )
            if env_block:
                input_items.append(
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": env_block,
                            }
                        ],
                    }
                )

        # --- Tool Call Handling Logic Split ---
        if capabilities.tool_text_format == "codex_xml":
            # Legacy path for Kilo/Cline agents relying on textual tool calls
            pending_tool_call_records: list[dict[str, str]] = []

            def _normalize_command_text(command_text: str | None) -> str:
                if not command_text:
                    return ""
                return " ".join(str(command_text).split())

            def _register_tool_call(
                call_id: str, name: str, command_text: str | None
            ) -> None:
                pending_tool_call_records.append(
                    {
                        "id": call_id,
                        "name": (name or "").lower(),
                        "command_text": _normalize_command_text(command_text),
                    }
                )

            def _match_textual_result(result: TextToolResult) -> dict[str, str] | None:
                normalized_name = (result.canonical_name or "").lower()
                normalized_command = _normalize_command_text(result.command_text)
                for idx, record in enumerate(pending_tool_call_records):
                    if record["name"] != normalized_name:
                        continue
                    if (
                        normalized_command
                        and record["command_text"]
                        and record["command_text"] != normalized_command
                    ):
                        continue
                    return pending_tool_call_records.pop(idx)
                if pending_tool_call_records:
                    return pending_tool_call_records.pop(0)
                return None

            def _extract_command_text_from_arguments(
                arguments: str | None,
            ) -> str | None:
                if not arguments:
                    return None
                try:
                    parsed = json.loads(arguments)
                except Exception:
                    return None
                command_value = parsed.get("command")
                if isinstance(command_value, list | tuple):
                    return " ".join(str(part) for part in command_value)
                if isinstance(command_value, str):
                    return command_value
                return None

            for message in processed_messages or []:
                role = getattr(message, "role", None)
                if role is None and isinstance(message, dict):
                    role = message.get("role")
                role = (role or "user").lower()

                if logger.isEnabledFor(logging.DEBUG):
                    try:
                        logger.debug(
                            "Codex message role=%s content_preview=%s",
                            role,
                            json.dumps(
                                getattr(message, "content", None)
                                if not isinstance(message, dict)
                                else message.get("content")
                            )[:200],
                        )
                    except Exception:
                        logger.debug(
                            "Codex message role=%s content=<unserializable>", role
                        )

                raw_content = getattr(message, "content", None)
                if raw_content is None and isinstance(message, dict):
                    raw_content = message.get("content")
                text = ""
                if raw_content is not None:
                    text = self._connector._message_to_text(message)

                if role == "system":
                    continue

                tool_calls = getattr(message, "tool_calls", None)
                if not tool_calls and isinstance(message, dict):
                    tool_calls = message.get("tool_calls")

                if role == "assistant" and tool_calls:
                    for tool_call in tool_calls or []:
                        call_id = getattr(tool_call, "id", None)
                        if call_id is None and isinstance(tool_call, dict):
                            call_id = tool_call.get("id")
                        function = getattr(tool_call, "function", None)
                        if function is None and isinstance(tool_call, dict):
                            function = tool_call.get("function")
                        name = None
                        arguments = None
                        if function is not None:
                            if isinstance(function, dict):
                                name = function.get("name")
                                arguments = function.get("arguments")
                            else:
                                name = getattr(function, "name", None)
                                arguments = getattr(function, "arguments", None)
                        if arguments is None:
                            arguments = "{}"
                        call_id = call_id or f"call_{uuid.uuid4().hex[:16]}"
                        _register_tool_call(
                            call_id,
                            name or "",
                            _extract_command_text_from_arguments(arguments),
                        )
                        input_items.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name or "",
                                "arguments": arguments,
                            }
                        )
                    if text.strip():
                        input_items.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": text}],
                            }
                        )
                    continue

                if role == "assistant":
                    invocation = parse_textual_tool_invocation(text) if text else None
                    if invocation:
                        call_id = f"call_{uuid.uuid4().hex[:16]}"
                        _register_tool_call(
                            call_id, invocation.canonical_name, invocation.command_text
                        )
                        input_items.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": invocation.canonical_name,
                                "arguments": json.dumps(invocation.arguments),
                            }
                        )
                        continue

                if role == "user":
                    textual_result = parse_textual_tool_result(text) if text else None
                    if textual_result:
                        matched_call = _match_textual_result(textual_result)
                        call_id = (
                            matched_call["id"]
                            if matched_call
                            else f"call_{uuid.uuid4().hex[:16]}"
                        )
                        output_payload: dict[str, Any] = {
                            "output": textual_result.output_text
                        }
                        if textual_result.exit_code is not None:
                            output_payload["exit_code"] = textual_result.exit_code
                        if textual_result.working_directory:
                            output_payload["workdir"] = textual_result.working_directory
                        input_items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": json.dumps(output_payload),
                            }
                        )
                        continue

                if not text.strip():
                    if role == "tool":
                        call_id = getattr(message, "tool_call_id", None)
                        if call_id is None and isinstance(message, dict):
                            call_id = message.get("tool_call_id")
                        output_payload = {"output": ""}
                        input_items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id or "",
                                "output": json.dumps(output_payload),
                            }
                        )
                    continue

                content_type = "input_text"
                if role == "assistant":
                    content_type = "output_text"
                elif role in {"tool", "function"}:
                    call_id = getattr(message, "tool_call_id", None)
                    if call_id is None and isinstance(message, dict):
                        call_id = message.get("tool_call_id")
                    output_payload = {"output": text}
                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id or "",
                            "output": json.dumps(output_payload),
                        }
                    )
                    continue

                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": [{"type": content_type, "text": text}],
                    }
                )
        else:
            # --- New Canonical Tool Call Handling Path ---
            for message in processed_messages or []:
                role = getattr(message, "role", None)
                if role is None and isinstance(message, dict):
                    role = message.get("role")
                role = (role or "user").lower()

                if logger.isEnabledFor(logging.DEBUG):
                    try:
                        logger.debug(
                            "Codex message role=%s content_preview=%s (Canonical Path)",
                            role,
                            json.dumps(
                                getattr(message, "content", None)
                                if not isinstance(message, dict)
                                else message.get("content")
                            )[:200],
                        )
                    except Exception:
                        logger.debug(
                            "Codex message role=%s content=<unserializable> (Canonical Path)",
                            role,
                        )

                raw_content = getattr(message, "content", None)
                if raw_content is None and isinstance(message, dict):
                    raw_content = message.get("content")
                text = ""
                if raw_content is not None:
                    text = self._connector._message_to_text(message)

                if role == "system":
                    continue

                tool_calls = getattr(message, "tool_calls", None)
                if not tool_calls and isinstance(message, dict):
                    tool_calls = message.get("tool_calls")

                if role == "assistant" and tool_calls:
                    for tool_call in tool_calls or []:
                        call_id = getattr(tool_call, "id", None)
                        if call_id is None and isinstance(tool_call, dict):
                            call_id = tool_call.get("id")
                        function = getattr(tool_call, "function", None)
                        if function is None and isinstance(tool_call, dict):
                            function = tool_call.get("function")
                        name = None
                        arguments = None
                        if function is not None:
                            if isinstance(function, dict):
                                name = function.get("name")
                                arguments = function.get("arguments")
                            else:
                                name = getattr(function, "name", None)
                                arguments = getattr(function, "arguments", None)
                        if arguments is None:
                            arguments = "{}"
                        call_id = call_id or f"call_{uuid.uuid4().hex[:16]}"
                        input_items.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name or "",
                                "arguments": arguments,
                            }
                        )
                    if text.strip():
                        input_items.append(
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [{"type": "output_text", "text": text}],
                            }
                        )
                    continue

                if role in {"tool", "function"}:
                    call_id = getattr(message, "tool_call_id", None)
                    if call_id is None and isinstance(message, dict):
                        call_id = message.get("tool_call_id")

                    # Tool messages must have content, even if empty string
                    output_payload = {"output": text or ""}

                    # Attempt to extract exit_code/workdir if content is JSON
                    try:
                        if text and text.strip().startswith("{"):
                            tool_result_json = json.loads(text)
                            if "exit_code" in tool_result_json:
                                output_payload["exit_code"] = tool_result_json[
                                    "exit_code"
                                ]
                            if "workdir" in tool_result_json:
                                output_payload["workdir"] = tool_result_json["workdir"]
                            # If it's a structured result, use the raw text as the output
                            output_payload["output"] = text
                    except json.JSONDecodeError:
                        # If not JSON, just use the raw text as output
                        pass

                    input_items.append(
                        {
                            "type": "function_call_output",
                            "call_id": call_id or "",
                            "output": json.dumps(output_payload),
                        }
                    )
                    continue

                # Handle regular user/assistant messages (text only)
                content_type = "input_text"
                if role == "assistant":
                    content_type = "output_text"

                if text.strip():
                    input_items.append(
                        {
                            "type": "message",
                            "role": role,
                            "content": [{"type": content_type, "text": text}],
                        }
                    )
        return input_items
