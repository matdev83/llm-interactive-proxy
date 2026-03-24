"""Cline-like XML family compatibility adapter."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolArguments,
    ToolExecutionResult,
)
from src.connectors.openai_codex.tools import ToolExecutionService

logger = logging.getLogger(__name__)


class KiloClientFamilyAdapter(IClientFamilyAdapter):
    """Compatibility adapter for KiloCode, RooCode, and Cline XML clients."""

    family = "cline_like"

    _CLINE_LIKE_ALIASES = {
        "kilocode",
        "kilo-code",
        "kilo_code",
        "kilocode.ai",
        "kilo",
        "kiloc",
        "roocode",
        "roo-code",
        "roo_code",
        "roo",
        "roo cline",
        "roo-cline",
        "roo_cline",
        "cline",
        "cline.ai",
    }
    _SUPPORTED_XML_TOOL_NAMES = {
        "shell",
        "read_file",
        "list_dir",
        "grep_files",
        "__proxy_attempt_completion",
        "__proxy_ask_followup_question",
        "__proxy_search_and_replace",
        "__proxy_write_to_file",
        "__proxy_insert_content",
        "__proxy_edit_file",
        "__proxy_use_mcp_tool",
        "__proxy_access_mcp_resource",
    }
    _XML_BRIDGE_INSTRUCTIONS = (
        "Cline-family XML compatibility mode is active for this session. "
        "Do not emit native OpenAI/Codex function or custom tool calls in the response. "
        "When you need a tool, write a single XML tool invocation directly in assistant text using the client XML format. "
        "Prefer these XML tools: <execute_command>, <read_file>, <list_files>, <search_files>, "
        "<attempt_completion>, <ask_followup_question>, <use_mcp_tool>, <access_mcp_resource>, "
        "<search_and_replace>, <write_to_file>, <insert_content>, <edit_file>. "
        "For command execution, use <execute_command>...</execute_command> rather than bash/shell JSON tool calls."
    )

    def __init__(
        self,
        *,
        session_detector: Any | None = None,
        kilo_translator: Any | None = None,
        tool_execution_service: ToolExecutionService | None = None,
        translate_kilo_tools: Callable[
            [list[ProcessedMessage], str],
            Awaitable[dict[str, list[CodexToolSchema]]],
        ],
        clean_xml_from_message: Callable[[str], str],
    ) -> None:
        self._session_detector = session_detector
        self._kilo_translator = kilo_translator
        self._tool_execution_service = tool_execution_service
        self._translate_kilo_tools = translate_kilo_tools
        self._clean_xml_from_message = clean_xml_from_message

    async def detect(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> None:
        if self._is_cline_like_context(context):
            state.is_kilocode = True

        if not self._session_detector:
            return

        try:
            detection_result = await self._session_detector.detect(
                request_data=context.request,
                metadata=context.metadata,
                session_id=context.session_id,
                backend="openai-codex",
            )
            state.is_kilocode = detection_result.is_kilocode
            if state.is_kilocode:
                logger.info(
                    "Cline-like XML client detected for session %s (method: %s, confidence: %.2f)",
                    context.session_id,
                    detection_result.detection_method,
                    detection_result.confidence,
                )
        except Exception as e:
            logger.debug("KiloCode detection failed: %s", str(e), exc_info=True)

    async def apply(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> FamilyApplyResult:
        result = FamilyApplyResult()
        if not state.is_kilocode or not self._kilo_translator:
            return result

        translated_tools = await self._translate_kilo_tools(
            context.processed_messages, context.session_id
        )
        result.codex_tools.extend(translated_tools.get("codex_tools", []))
        result.proxy_tools.extend(translated_tools.get("proxy_tools", []))
        result.mcp_tools.extend(translated_tools.get("mcp_tools", []))

        if self._tool_execution_service:
            for tool in result.proxy_tools:
                try:
                    exec_result = await self._tool_execution_service.execute_proxy_tool(
                        tool.name,
                        ToolArguments(payload=tool.parameters or {}),
                        context.session_id,
                    )
                    result.tool_results.append(exec_result)
                except Exception as e:
                    logger.error(
                        "Failed to execute proxy tool %s: %s",
                        tool.name,
                        str(e),
                        exc_info=True,
                    )
                    actual_tool_name = tool.name.replace("__proxy_", "")
                    result.tool_results.append(
                        ToolExecutionResult(
                            success=False,
                            result=f"[{actual_tool_name}] Error: {e!s}",
                            error=str(e),
                        )
                    )

            for tool in result.mcp_tools:
                try:
                    exec_result = await self._tool_execution_service.execute_mcp_tool(
                        tool.name,
                        ToolArguments(payload=tool.parameters or {}),
                        context.session_id,
                    )
                    result.tool_results.append(exec_result)
                except Exception as e:
                    logger.error(
                        "Failed to execute MCP tool %s: %s",
                        tool.name,
                        str(e),
                        exc_info=True,
                    )
                    mcp_tool_name = (tool.parameters or {}).get("tool_name", "unknown")
                    result.tool_results.append(
                        ToolExecutionResult(
                            success=False,
                            result=f"[{mcp_tool_name}] Error: {e!s}",
                            error=str(e),
                        )
                    )

        if result.codex_tools or result.proxy_tools or result.mcp_tools:
            for message in context.processed_messages:
                content = (
                    message.content if isinstance(message, ProcessedMessage) else ""
                )
                if (
                    not isinstance(content, str)
                    or "<" not in content
                    or ">" not in content
                ):
                    continue
                cleaned_content = self._clean_xml_from_message(content)
                if cleaned_content == content:
                    continue
                message.content = cleaned_content

        return result

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        return chunk

    async def cleanup_state(self, state: CompatibilityState) -> None:
        state.is_kilocode = False

    def adapt_payload_dict(
        self,
        payload_dict: dict[str, object],
        context: CodexRequestContext,
        *,
        resolved_instructions: str | None = None,
    ) -> dict[str, object]:
        if not self._is_cline_like_context(context):
            return payload_dict

        adapted = dict(payload_dict)
        existing_instructions = adapted.get("instructions")
        bridge_instructions = self._XML_BRIDGE_INSTRUCTIONS
        if isinstance(existing_instructions, str) and existing_instructions.strip():
            if bridge_instructions not in existing_instructions:
                adapted["instructions"] = (
                    f"{existing_instructions.rstrip()}\n\n{bridge_instructions}"
                )
        else:
            adapted["instructions"] = bridge_instructions

        input_items = adapted.get("input")
        if isinstance(input_items, list):
            bridge_message = {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": bridge_instructions,
                    }
                ],
            }
            if not self._has_bridge_message(input_items):
                adapted["input"] = [bridge_message, *input_items]

        return adapted

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._is_cline_like_context(context):
            return []

        incompatible: list[str] = []
        for tool_call in tool_calls:
            function_data = tool_call.get("function")
            if not isinstance(function_data, dict):
                incompatible.append("unknown_tool")
                continue
            name = function_data.get("name")
            if not isinstance(name, str) or not name.strip():
                incompatible.append("unknown_tool")
                continue
            if name not in self._SUPPORTED_XML_TOOL_NAMES:
                incompatible.append(name)
        return incompatible

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        if not self._is_cline_like_context(context) or not incompatible_tool_names:
            return payload_dict

        adapted = dict(payload_dict)
        blocked = ", ".join(dict.fromkeys(incompatible_tool_names))
        steering = (
            f"Do not call these native Codex/OpenAI tools in this session: {blocked}. "
            "Those tool calls are incompatible with the connected client and were rejected by the proxy. "
            "Instead, continue by emitting only Cline-family XML tool invocations in assistant text. "
            "Prefer <execute_command> for terminal commands and other supported XML tags for file/search actions."
        )
        instructions = adapted.get("instructions")
        if isinstance(instructions, str) and instructions.strip():
            adapted["instructions"] = f"{instructions.rstrip()}\n\n{steering}"
        else:
            adapted["instructions"] = steering
        return adapted

    def _is_cline_like_context(self, context: CodexRequestContext) -> bool:
        metadata = context.metadata or {}
        agent_candidates: list[str] = []

        agent_value = metadata.get("agent")
        if isinstance(agent_value, str):
            agent_candidates.append(agent_value)

        headers = metadata.get("headers")
        if isinstance(headers, dict):
            for header_name in ("user-agent", "User-Agent"):
                header_value = headers.get(header_name)
                if isinstance(header_value, str):
                    agent_candidates.append(header_value)

        request_agent = getattr(context.request, "agent", None)
        if isinstance(request_agent, str):
            agent_candidates.append(request_agent)

        extra_body = getattr(context.request, "extra_body", None)
        if isinstance(extra_body, dict):
            extra_agent = extra_body.get("agent")
            if isinstance(extra_agent, str):
                agent_candidates.append(extra_agent)

        for candidate in agent_candidates:
            normalized = (
                candidate.lower()
                .split("/", 1)[0]
                .replace("-", "")
                .replace("_", "")
                .replace(".", "")
                .replace(" ", "")
            )
            if candidate.lower().strip() in self._CLINE_LIKE_ALIASES or normalized in {
                "kilocode",
                "kiloc",
                "kilo",
                "cline",
                "roo",
                "roocode",
                "roocline",
            }:
                return True
        return False

    def _has_bridge_message(self, input_items: list[object]) -> bool:
        for item in input_items:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "message" or item.get("role") != "developer":
                continue
            content = item.get("content")
            if isinstance(content, list) and any(
                isinstance(part, dict)
                and self._XML_BRIDGE_INSTRUCTIONS in str(part.get("text", ""))
                for part in content
            ):
                return True
        return False
