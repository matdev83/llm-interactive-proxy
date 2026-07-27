from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.commands.tool_call_text_parser import (
    TextToolResult,
    parse_textual_tool_invocation,
    parse_textual_tool_result,
)

if TYPE_CHECKING:
    from src.connectors.openai_codex import OpenAICodexConnector


logger = logging.getLogger(__name__)


def _format_content_preview_for_log(content: Any, *, max_len: int = 200) -> str:
    """Best-effort JSON snippet for TRACE logs (handles Pydantic models in content)."""

    def _json_default(obj: Any) -> Any:
        if isinstance(obj, BaseModel):
            try:
                return obj.model_dump(mode="json")
            except (TypeError, ValueError):
                return str(obj)
        return str(obj)

    try:
        out = json.dumps(content, default=_json_default)
    except (TypeError, ValueError):
        out = repr(content)
    return out[:max_len]


@dataclass(frozen=True, slots=True)
class _PendingToolCallRecord:
    id: str
    name: str
    command_text: str


@dataclass(frozen=True, slots=True)
class _ToolCallNameAndArguments:
    """Result of extracting tool call name and arguments.

    Attributes:
        name: The tool call name, or None if not found.
        arguments: The tool call arguments as a JSON string.
    """

    name: str | None
    arguments: str


def _normalize_command_text(command_text: str | None) -> str:
    if not command_text:
        return ""
    return " ".join(str(command_text).split())


def _extract_command_text_from_arguments(arguments: str | None) -> str | None:
    if not arguments:
        return None
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as e:
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Failed to parse command arguments JSON: %s",
                e,
                exc_info=True,
            )
        return None
    command_value = parsed.get("command")
    if isinstance(command_value, list | tuple):
        return " ".join(str(part) for part in command_value)
    if isinstance(command_value, str):
        return command_value
    return None


class _TextToolCallMatcher:
    def __init__(self, max_pending: int = 1000) -> None:
        self._pending: list[_PendingToolCallRecord] = []
        self._max_pending = max(max_pending, 1)

    def register(self, call_id: str, name: str, command_text: str | None) -> None:
        self._pending.append(
            _PendingToolCallRecord(
                id=call_id,
                name=(name or "").lower(),
                command_text=_normalize_command_text(command_text),
            )
        )
        if len(self._pending) > self._max_pending:
            self._pending.pop(0)

    def match_textual_result(
        self, result: TextToolResult
    ) -> _PendingToolCallRecord | None:
        normalized_name = (result.canonical_name or "").lower()
        normalized_command = _normalize_command_text(result.command_text)

        for idx, record in enumerate(self._pending):
            if record.name != normalized_name:
                continue
            if (
                normalized_command
                and record.command_text
                and record.command_text != normalized_command
            ):
                continue
            return self._pending.pop(idx)

        if self._pending:
            return self._pending.pop(0)
        return None


class CodexRequestTranslator:
    """Translates a canonical chat request into Codex-specific input items."""

    def __init__(self, connector: OpenAICodexConnector) -> None:  # type: ignore[invalid-type-form]
        self._connector = connector

    def build_input_items(
        self,
        request_data: Any,
        processed_messages: list[Any],
        effective_model: str,
        capabilities: CodexClientCapabilities,
        custom_instruction_sections: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Transform processed messages into Codex Responses `input` array."""
        input_items: list[dict[str, Any]] = []

        self._log_build_context(capabilities)
        self._append_prompt_mode_instructions(
            input_items=input_items,
            request_data=request_data,
            capabilities=capabilities,
            custom_instruction_sections=custom_instruction_sections,
        )

        # System prompt handling is now centralized in `_resolve_system_prompt`,
        # so we no longer inject user instructions here.
        # The loop over processed_messages will skip any 'system' role messages.

        self._append_environment_context(
            input_items=input_items,
            request_data=request_data,
            effective_model=effective_model,
            capabilities=capabilities,
        )

        # --- Tool Call Handling Logic Split ---
        if capabilities.tool_text_format == "codex_xml":
            # Legacy path for Kilo/Cline agents relying on textual tool calls
            matcher = _TextToolCallMatcher()

            for message in processed_messages or []:
                self._append_codex_xml_message_items(
                    input_items=input_items, matcher=matcher, message=message
                )
        else:
            # --- New Canonical Tool Call Handling Path ---
            for message in processed_messages or []:
                self._append_canonical_message_items(
                    input_items=input_items, message=message
                )
        return input_items

    @staticmethod
    def _log_build_context(capabilities: CodexClientCapabilities) -> None:
        if logger.isEnabledFor(TRACE_LEVEL):
            logger.log(
                TRACE_LEVEL,
                "Building Codex input items (protocol=%s, tool_text_format=%s)",
                capabilities.protocol,
                capabilities.tool_text_format,
            )

    def _append_prompt_mode_instructions(
        self,
        *,
        input_items: list[dict[str, Any]],
        request_data: Any,
        capabilities: CodexClientCapabilities,
        custom_instruction_sections: Sequence[str] | None,
    ) -> None:
        prompt_mode = (capabilities.prompt_mode or "codex_default").lower()
        if prompt_mode != "codex_default":
            return

        sections = (
            list(custom_instruction_sections)
            if custom_instruction_sections is not None
            else self._connector._extract_custom_instruction_sections(request_data)
        )
        user_instructions_block = self._connector._render_user_instruction_block(
            sections
        )
        if user_instructions_block:
            input_items.append(user_instructions_block)

    def _append_environment_context(
        self,
        *,
        input_items: list[dict[str, Any]],
        request_data: Any,
        effective_model: str,
        capabilities: CodexClientCapabilities,
    ) -> None:
        if not capabilities.include_environment_context:
            return

        env_block = self._connector._build_environment_context_block(
            request_data, effective_model
        )
        if not env_block:
            return

        input_items.append(
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": env_block}],
            }
        )

    @staticmethod
    def _extract_role(message: Any) -> str:
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        return (role or "user").lower()

    @staticmethod
    def _extract_tool_calls(message: Any) -> Any:
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls and isinstance(message, dict):
            tool_calls = message.get("tool_calls")
        return tool_calls

    def _message_to_text(self, message: Any) -> str:
        raw_content = getattr(message, "content", None)
        if raw_content is None and isinstance(message, dict):
            raw_content = message.get("content")
        if raw_content is None:
            return ""
        text = self._connector._message_to_text(message)
        return text if isinstance(text, str) else str(text)

    def _append_codex_xml_message_items(
        self,
        *,
        input_items: list[dict[str, Any]],
        matcher: _TextToolCallMatcher,
        message: Any,
    ) -> None:
        role = self._extract_role(message)
        self._log_message_preview(message, role, canonical=False)
        if role == "system":
            return

        text = self._message_to_text(message)
        tool_calls = self._extract_tool_calls(message)

        if role == "assistant" and tool_calls:
            self._append_codex_xml_assistant_tool_calls(
                input_items=input_items, matcher=matcher, tool_calls=tool_calls
            )
            self._append_text_message_if_present(
                input_items=input_items,
                role="assistant",
                content_type="output_text",
                text=text,
            )
            return

        if role == "assistant":
            invocation = parse_textual_tool_invocation(text) if text else None
            if invocation:
                call_id = f"call_{uuid.uuid4().hex[:16]}"
                matcher.register(
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
                return

        if role == "user":
            textual_result = parse_textual_tool_result(text) if text else None
            if textual_result:
                matched_call = matcher.match_textual_result(textual_result)
                call_id = (
                    matched_call.id if matched_call else f"call_{uuid.uuid4().hex[:16]}"
                )
                output_payload: dict[str, Any] = {"output": textual_result.output_text}
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
                return

        if not text.strip():
            self._append_empty_tool_output_if_needed(
                input_items=input_items, role=role, message=message
            )
            return

        if role in {"tool", "function"}:
            tool_call_id: str | None = getattr(message, "tool_call_id", None)
            if tool_call_id is None and isinstance(message, dict):
                tool_call_id = message.get("tool_call_id")
            if tool_call_id is not None and not isinstance(tool_call_id, str):
                tool_call_id = str(tool_call_id)
            output_payload = {"output": text}
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_call_id or "",
                    "output": json.dumps(output_payload),
                }
            )
            return

        content_type = "output_text" if role == "assistant" else "input_text"
        input_items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
            }
        )

    def _append_codex_xml_assistant_tool_calls(
        self,
        *,
        input_items: list[dict[str, Any]],
        matcher: _TextToolCallMatcher,
        tool_calls: Any,
    ) -> None:
        for tool_call in tool_calls or []:
            call_id = getattr(tool_call, "id", None)
            if call_id is None and isinstance(tool_call, dict):
                call_id = tool_call.get("id")
            function = getattr(tool_call, "function", None)
            if function is None and isinstance(tool_call, dict):
                function = tool_call.get("function")

            result = self._extract_tool_call_name_and_arguments(function)
            if not (isinstance(result.name, str) and result.name.strip()):
                continue
            call_id = call_id or f"call_{uuid.uuid4().hex[:16]}"
            matcher.register(
                call_id,
                result.name.strip(),
                _extract_command_text_from_arguments(result.arguments),
            )

            input_items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": result.name.strip(),
                    "arguments": result.arguments,
                }
            )

    @staticmethod
    def _extract_tool_call_name_and_arguments(
        function: Any,
    ) -> _ToolCallNameAndArguments:
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
        return _ToolCallNameAndArguments(name=name, arguments=str(arguments))

    def _append_empty_tool_output_if_needed(
        self,
        *,
        input_items: list[dict[str, Any]],
        role: str,
        message: Any,
    ) -> None:
        if role != "tool":
            return
        call_id = getattr(message, "tool_call_id", None)
        if call_id is None and isinstance(message, dict):
            call_id = message.get("tool_call_id")
        input_items.append(
            {
                "type": "function_call_output",
                "call_id": call_id or "",
                "output": json.dumps({"output": ""}),
            }
        )

    @staticmethod
    def _append_text_message_if_present(
        *,
        input_items: list[dict[str, Any]],
        role: str,
        content_type: str,
        text: str,
    ) -> None:
        if not text.strip():
            return
        input_items.append(
            {
                "type": "message",
                "role": role,
                "content": [{"type": content_type, "text": text}],
            }
        )

    def _append_canonical_message_items(
        self,
        *,
        input_items: list[dict[str, Any]],
        message: Any,
    ) -> None:
        role = self._extract_role(message)
        self._log_message_preview(message, role, canonical=True)
        if role == "system":
            return

        text = self._message_to_text(message)
        tool_calls = self._extract_tool_calls(message)

        if role == "assistant" and tool_calls:
            for tool_call in tool_calls or []:
                call_id = getattr(tool_call, "id", None)
                if call_id is None and isinstance(tool_call, dict):
                    call_id = tool_call.get("id")
                function = getattr(tool_call, "function", None)
                if function is None and isinstance(tool_call, dict):
                    function = tool_call.get("function")

                result = self._extract_tool_call_name_and_arguments(function)
                if not (isinstance(result.name, str) and result.name.strip()):
                    continue
                call_id = call_id or f"call_{uuid.uuid4().hex[:16]}"
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": result.name.strip(),
                        "arguments": result.arguments,
                    }
                )

            self._append_text_message_if_present(
                input_items=input_items,
                role="assistant",
                content_type="output_text",
                text=text,
            )
            return

        if role in {"tool", "function"}:
            self._append_tool_output_canonical(
                input_items=input_items, message=message, text=text
            )
            return

        content_type = "output_text" if role == "assistant" else "input_text"
        self._append_text_message_if_present(
            input_items=input_items, role=role, content_type=content_type, text=text
        )

    @staticmethod
    def _append_tool_output_canonical(
        *,
        input_items: list[dict[str, Any]],
        message: Any,
        text: str,
    ) -> None:
        call_id = getattr(message, "tool_call_id", None)
        if call_id is None and isinstance(message, dict):
            call_id = message.get("tool_call_id")

        output_payload: dict[str, Any] = {"output": text or ""}

        # Attempt to extract exit_code/workdir if content is JSON
        if text and text.strip().startswith("{"):
            try:
                tool_result_json = json.loads(text)
            except json.JSONDecodeError:
                tool_result_json = None
            if isinstance(tool_result_json, dict):
                if "exit_code" in tool_result_json:
                    output_payload["exit_code"] = tool_result_json["exit_code"]
                if "workdir" in tool_result_json:
                    output_payload["workdir"] = tool_result_json["workdir"]
                output_payload["output"] = text

        input_items.append(
            {
                "type": "function_call_output",
                "call_id": call_id or "",
                "output": json.dumps(output_payload),
            }
        )

    @staticmethod
    def _log_message_preview(message: Any, role: str, *, canonical: bool) -> None:
        if not logger.isEnabledFor(TRACE_LEVEL):
            return
        suffix = " (Canonical Path)" if canonical else ""
        preview_source = (
            getattr(message, "content", None)
            if not isinstance(message, dict)
            else message.get("content")
        )
        preview_text = _format_content_preview_for_log(preview_source)
        logger.log(
            TRACE_LEVEL,
            "Codex message role=%s content_preview=%s%s",
            role,
            preview_text,
            suffix,
        )
