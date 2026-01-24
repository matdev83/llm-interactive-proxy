from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from typing import Any

import pydantic

from src.core.commands.models import Command, CommandResultWrapper
from src.core.commands.tool_call_text_parser import (
    TextToolResult,
    parse_textual_tool_result,
)
from src.core.common.exceptions import LLMProxyError
from src.core.domain.chat import (
    ChatMessage,
    FunctionCall,
    MessageContentPartText,
    ToolCall,
)
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.command_service_interface import ICommandService

logger = logging.getLogger(__name__)


class ToolCallCommandProcessor(ICommandProcessor):
    """Command processor handling structured tool calls and textual tool results."""

    def __init__(self, command_service: ICommandService):
        self._command_service = command_service

    async def process_messages(
        self,
        messages: list[Any],
        session_id: str,
        context: RequestContext | None = None,
    ) -> ProcessedResult:
        """Process structured tool calls and Cline-style textual tool results."""
        logger.debug("ToolCallCommandProcessor invoked")

        normalized_messages = self._clone_messages(messages)
        if not normalized_messages:
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        # Track tool calls emitted by preceding assistant messages
        pending_tool_calls: list[ToolCall] = []
        tool_calls_to_execute: list[ToolCall] = []
        textual_tool_messages: list[int] = []

        for index, message in enumerate(normalized_messages):
            role = (message.role or "").lower()
            if role == "assistant" and message.tool_calls:
                pending_tool_calls = list(message.tool_calls)
                tool_calls_to_execute.extend(pending_tool_calls)
                continue

            if role != "user":
                continue

            parsed = self._parse_textual_tool_result(message)
            if not parsed or not pending_tool_calls:
                continue

            matched_call = self._pop_matching_tool_call(
                pending_tool_calls, parsed.canonical_name
            )
            if matched_call is None:
                logger.debug(
                    "Detected textual tool result but no matching tool call was found "
                    "for canonical tool '%s'",
                    parsed.canonical_name,
                )
                continue

            with contextlib.suppress(ValueError):
                tool_calls_to_execute.remove(matched_call)

            replacement = ChatMessage(
                role="tool",
                content=parsed.output_text,
                name=parsed.canonical_name,
                tool_call_id=matched_call.id,
                metadata={
                    "is_proxy_tool_output": True,
                    "tool_call_id": matched_call.id,
                },
            )
            normalized_messages[index] = replacement
            textual_tool_messages.append(index)

        # Execute remaining structured tool calls (non textual) via command service
        command_results: list[CommandResultWrapper | Any] = []
        if tool_calls_to_execute:
            tasks = [
                self._execute_tool_call(tool_call, session_id)
                for tool_call in tool_calls_to_execute
            ]
            results = await asyncio.gather(*tasks)
            command_results = [res for res in results if isinstance(res, ChatMessage)]

        command_executed = bool(command_results or textual_tool_messages)
        if not command_executed:
            return ProcessedResult(
                modified_messages=messages, command_executed=False, command_results=[]
            )

        # When textual tool results were converted, return the normalized list
        modified = normalized_messages if textual_tool_messages else messages
        return ProcessedResult(
            modified_messages=modified,
            command_executed=True,
            command_results=command_results,
        )

    async def _execute_tool_call(
        self, tool_call: ToolCall, session_id: str
    ) -> ChatMessage | None:
        """Execute a single structured tool call via the command service."""
        if not isinstance(tool_call, ToolCall) or not isinstance(
            tool_call.function, FunctionCall
        ):
            return None

        command_name = tool_call.function.name
        if not command_name:
            logger.warning("Tool call has no function name, skipping")
            return None
        try:
            args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError:
            logger.warning(
                "Failed to decode tool call arguments: %s",
                tool_call.function.arguments,
                exc_info=True,
            )
            return None

        command = Command(name=command_name, args=args)

        try:
            result = await self._command_service.execute_command(command, session_id)
            if result and result.success:
                return ChatMessage(
                    role="tool",
                    content=result.message,
                    tool_call_id=tool_call.id,
                    name=command_name,
                    metadata={
                        "is_proxy_tool_output": True,
                        "tool_call_id": tool_call.id,
                    },
                )
            return ChatMessage(
                role="tool",
                content=f"Error executing tool {command_name}: {getattr(result, 'message', 'Unknown error')}",
                tool_call_id=tool_call.id,
                name=command_name,
                metadata={
                    "is_proxy_tool_output": True,
                    "tool_call_id": tool_call.id,
                },
            )

        except (LLMProxyError, Exception) as err:
            logger.error(
                "Error executing tool call '%s': %s",
                command_name,
                err,
                exc_info=True,
            )
            return ChatMessage(
                role="tool",
                content=f"Exception executing tool {command_name}",
                tool_call_id=tool_call.id,
                name=command_name,
                metadata={
                    "is_proxy_tool_output": True,
                    "tool_call_id": tool_call.id,
                },
            )

    @staticmethod
    def _clone_messages(messages: Sequence[Any]) -> list[ChatMessage]:
        cloned: list[ChatMessage] = []
        for message in messages:
            if isinstance(message, ChatMessage):
                cloned.append(message.model_copy(deep=True))
                continue
            try:
                cloned.append(ChatMessage(**message))
            except (pydantic.ValidationError, TypeError, ValueError):
                logger.debug("Failed to coerce message into ChatMessage", exc_info=True)
        return cloned

    @classmethod
    def _message_content_to_str(cls, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, MessageContentPartText):
            return content.text
        if hasattr(content, "text"):
            text_value = getattr(content, "text", None)
            if isinstance(text_value, str):
                return text_value
        if isinstance(content, dict):
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
        if isinstance(content, Sequence):
            parts: list[str] = []
            for part in content:
                try:
                    parts.append(cls._message_content_to_str(part))
                except (TypeError, ValueError, AttributeError):
                    logger.debug(
                        "Failed to convert message content part to string, using fallback",
                        exc_info=True,
                    )
                    parts.append(str(part))
            return "\n".join(part for part in parts if part)
        return str(content)

    def _parse_textual_tool_result(self, message: ChatMessage) -> TextToolResult | None:
        text = self._message_content_to_str(message.content).strip()
        result = parse_textual_tool_result(text)
        if result is None:
            return None
        return result

    @staticmethod
    def _pop_matching_tool_call(
        pending_calls: list[ToolCall], canonical_tool: str
    ) -> ToolCall | None:
        for idx, tool_call in enumerate(list(pending_calls)):
            function_name = getattr(tool_call.function, "name", "")
            if function_name == canonical_tool or not function_name:
                pending_calls.pop(idx)
                return tool_call
        if pending_calls:
            return pending_calls.pop(0)
        return None
