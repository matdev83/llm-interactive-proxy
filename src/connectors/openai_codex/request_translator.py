"""Request translator adapter for OpenAI Codex connector.

This module provides an adapter wrapper around CodexRequestTranslator
that implements the IRequestTranslator interface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.contracts import (
    CodexInputItem,
    CodexRequestContext,
    ProcessedMessage,
)
from src.connectors.openai_codex.interfaces import IRequestTranslator
from src.core.domain.chat import ToolCall

if TYPE_CHECKING:
    from src.connectors._openai_codex_request_translator import CodexRequestTranslator


class RequestTranslator(IRequestTranslator):
    """Adapter wrapper around CodexRequestTranslator implementing IRequestTranslator.

    This adapter bridges the existing CodexRequestTranslator implementation
    with the new interface-based architecture.
    """

    def __init__(self, codex_translator: CodexRequestTranslator) -> None:
        """Initialize RequestTranslator adapter.

        Args:
            codex_translator: The underlying CodexRequestTranslator instance
        """
        self._codex_translator = codex_translator

    def translate_messages(
        self,
        messages: list[ProcessedMessage],
        context: CodexRequestContext | None = None,
    ) -> list[CodexInputItem]:
        """Convert processed messages to Codex input items.

        Args:
            messages: List of processed messages
            context: Optional request context for environment context and capabilities

        Returns:
            List of Codex input items
        """
        # Convert ProcessedMessage to the format expected by build_input_items
        processed_messages: list[Any] = []
        for msg in messages:
            # Convert ProcessedMessage to dict-like format
            msg_dict: dict[str, Any] = {
                "role": msg.role,
                "content": msg.content,
            }
            if msg.tool_calls:
                tool_calls = []
                for tc in msg.tool_calls:
                    function = tc.function if hasattr(tc, "function") else {}
                    if isinstance(function, dict):
                        name = function.get("name", "")
                        arguments = function.get("arguments", "{}")
                    else:
                        name = getattr(function, "name", "")
                        arguments = getattr(function, "arguments", "{}")
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    )
                msg_dict["tool_calls"] = tool_calls
            if msg.name:
                msg_dict["name"] = msg.name
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.metadata:
                msg_dict["metadata"] = msg.metadata
            processed_messages.append(msg_dict)

        # Use context if provided, otherwise use defaults. The no-context branch
        # is a defensive fallback (production callers always pass a context);
        # ``auto`` is a routing sentinel, not a hardcoded model slug.
        request_data = context.request if context else {}
        capabilities = context.capabilities if context else CodexClientCapabilities()
        effective_model = context.effective_model if context else "auto"

        # Call build_input_items with full context to include environment context
        # Note: build_input_items does more than just message translation,
        # but for the interface we extract just the message-related items
        input_items = self._codex_translator.build_input_items(
            request_data=request_data,
            processed_messages=processed_messages,
            effective_model=effective_model,
            capabilities=capabilities,
            custom_instruction_sections=None,
        )

        # Convert dict items to CodexInputItem while preserving structure
        result: list[CodexInputItem] = []
        for item in input_items:
            if isinstance(item, dict):
                item_type = item.get("type")
                if item_type in ("message", "function_call", "function_call_output"):
                    result.append(CodexInputItem(**item))
                continue

            result.append(CodexInputItem(type="message", content=str(item)))

        return result

    def translate_tool_calls(self, tool_calls: list[ToolCall]) -> list[CodexInputItem]:
        """Convert tool calls to Codex function_call input items.

        Args:
            tool_calls: List of tool calls

        Returns:
            List of Codex input items representing function calls
        """
        result: list[CodexInputItem] = []
        for tool_call in tool_calls:
            # Extract function name and arguments from ToolCall
            function = tool_call.function if hasattr(tool_call, "function") else {}
            function_name = (
                function.get("name")
                if isinstance(function, dict)
                else getattr(function, "name", "")
            )
            arguments = (
                function.get("arguments")
                if isinstance(function, dict)
                else getattr(function, "arguments", "{}")
            )

            item_dict: dict[str, Any] = {
                "type": "function_call",
                "call_id": tool_call.id or "",
                "name": function_name or "",
                "arguments": arguments or "{}",
            }
            result.append(CodexInputItem(**item_dict))
        return result
