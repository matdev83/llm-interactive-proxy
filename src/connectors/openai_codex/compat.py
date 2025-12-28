"""Compatibility layer for OpenAI Codex connector.

This module handles KiloCode and Droid compatibility flows including detection,
tool translation, and streaming chunk translation.
"""

from __future__ import annotations

import logging
import re
from typing import Any, cast

from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityResult,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolArguments,
    ToolCall,
    ToolExecutionResult,
)
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.connectors.openai_codex.tools import ToolExecutionService

logger = logging.getLogger(__name__)


class CompatibilityLayer(ICompatibilityLayer):
    """Service for handling KiloCode and Droid compatibility flows.

    This service handles:
    - Client detection (KiloCode and Droid)
    - Tool translation from XML to Codex format
    - Tool execution via ToolExecutionService
    - XML cleaning from messages
    - Streaming chunk translation for Droid
    - Per-request state management
    """

    def __init__(
        self,
        session_detector: Any | None = None,
        droid_detector: Any | None = None,
        kilo_translator: Any | None = None,
        droid_translator: Any | None = None,
        tool_execution_service: ToolExecutionService | None = None,
    ) -> None:
        """Initialize the compatibility layer.

        Args:
            session_detector: SessionDetector instance for KiloCode detection
            droid_detector: DroidSessionDetector instance for Droid detection
            kilo_translator: KiloToolTranslator instance for tool translation
            droid_translator: DroidToolTranslator instance for Droid translation
            tool_execution_service: ToolExecutionService instance for tool execution
        """
        self._session_detector = session_detector
        self._droid_detector = droid_detector
        self._kilo_translator = kilo_translator
        self._droid_translator = droid_translator
        self._tool_execution_service = tool_execution_service

    def create_state(self) -> CompatibilityState:
        """Create a new per-request compatibility state instance.

        Returns:
            New compatibility state instance
        """
        return CompatibilityState()

    async def apply(self, context: CodexRequestContext) -> CompatibilityResult:
        """Detect and translate compatibility tool calls.

        Args:
            context: Request context with processed messages and capabilities

        Returns:
            Compatibility result with tool lists and state
        """
        state = self.create_state()

        # Detect KiloCode client
        if self._session_detector:
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
                        "KiloCode client detected for session %s (method: %s, confidence: %.2f)",
                        context.session_id,
                        detection_result.detection_method,
                        detection_result.confidence,
                    )
            except Exception as e:
                logger.debug("KiloCode detection failed: %s", str(e))

        # Detect Droid client
        if self._droid_detector is None:
            try:
                from src.connectors._openai_codex_droid_session_detector import (
                    DroidSessionDetector,
                )

                self._droid_detector = DroidSessionDetector()
            except ImportError:
                logger.debug("Droid session detector not available")

        if self._droid_detector:
            try:
                # Extract tools and messages for detection
                request_tools = getattr(context.request, "tools", []) or []
                tools_for_detection = []
                for tool in request_tools:
                    if hasattr(tool, "model_dump"):
                        tools_for_detection.append(tool.model_dump())
                    elif isinstance(tool, dict):
                        tools_for_detection.append(tool)

                messages_for_detection = []
                for msg in context.processed_messages:
                    if isinstance(msg, ProcessedMessage):
                        msg_dict = (
                            msg.model_dump() if hasattr(msg, "model_dump") else {}
                        )
                        messages_for_detection.append(msg_dict)
                    elif isinstance(msg, dict):
                        messages_for_detection.append(msg)

                # Extract headers from metadata if available (headers are HTTP-level
                # and may not be available in domain request context)
                headers: dict[str, str] | None = None
                if context.metadata:
                    headers_candidate = context.metadata.get("headers")
                    if isinstance(headers_candidate, dict):
                        # Convert to dict[str, str] if possible
                        headers = {str(k): str(v) for k, v in headers_candidate.items()}

                droid_detection = self._droid_detector.detect(
                    headers=headers,  # Headers may not be available at domain layer
                    messages=messages_for_detection,
                    tools=tools_for_detection,
                )
                state.is_droid = droid_detection.is_droid

                if state.is_droid:
                    logger.info(
                        "Droid client detected for session %s (method: %s, confidence: %.2f)",
                        context.session_id,
                        droid_detection.detection_method,
                        droid_detection.confidence,
                    )

                    # Initialize Droid translator if not already set
                    if self._droid_translator is None:
                        try:
                            from src.connectors._openai_codex_droid_tool_translator import (
                                DroidToolTranslator,
                            )

                            self._droid_translator = DroidToolTranslator()
                        except ImportError:
                            logger.debug("Droid tool translator not available")
            except Exception as e:
                logger.debug("Droid detection failed: %s", str(e))

        # Translate KiloCode XML tools if detected
        codex_tools: list[CodexToolSchema] = []
        proxy_tools: list[CodexToolSchema] = []
        mcp_tools: list[CodexToolSchema] = []
        tool_results: list[ToolExecutionResult] = []

        if state.is_kilocode and self._kilo_translator:
            translated_tools = await self._translate_kilo_tools(
                context.processed_messages, context.session_id
            )

            codex_tools = translated_tools["codex_tools"]
            proxy_tools = translated_tools["proxy_tools"]
            mcp_tools = translated_tools["mcp_tools"]

            # Execute proxy tools
            if self._tool_execution_service:
                for tool in proxy_tools:
                    try:
                        result = await self._tool_execution_service.execute_proxy_tool(
                            tool.name,
                            ToolArguments(payload=tool.parameters),
                            context.session_id,
                        )
                        tool_results.append(result)
                        logger.debug(
                            "Executed proxy tool %s: success=%s",
                            tool.name,
                            result.success,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to execute proxy tool %s: %s",
                            tool.name,
                            str(e),
                            exc_info=True,
                        )
                        actual_tool_name = tool.name.replace("__proxy_", "")
                        tool_results.append(
                            ToolExecutionResult(
                                success=False,
                                result=f"[{actual_tool_name}] Error: {e!s}",
                                error=str(e),
                            )
                        )

                # Execute MCP tools
                for tool in mcp_tools:
                    try:
                        result = await self._tool_execution_service.execute_mcp_tool(
                            tool.name,
                            ToolArguments(payload=tool.parameters),
                            context.session_id,
                        )
                        tool_results.append(result)
                        logger.debug(
                            "Executed MCP tool %s: success=%s",
                            tool.name,
                            result.success,
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to execute MCP tool %s: %s",
                            tool.name,
                            str(e),
                            exc_info=True,
                        )
                        mcp_tool_name = tool.parameters.get("tool_name", "unknown")
                        tool_results.append(
                            ToolExecutionResult(
                                success=False,
                                result=f"[{mcp_tool_name}] Error: {e!s}",
                                error=str(e),
                            )
                        )

            # Clean XML from messages
            if codex_tools or proxy_tools or mcp_tools:
                for message in context.processed_messages:
                    if isinstance(message, ProcessedMessage):
                        content = message.content
                        if (
                            isinstance(content, str)
                            and "<" in content
                            and ">" in content
                        ):
                            cleaned_content = self._clean_xml_from_message(content)
                            if cleaned_content != content:
                                message.content = cleaned_content
                                logger.debug(
                                    "Cleaned XML from message (original: %d bytes, cleaned: %d bytes)",
                                    len(content),
                                    len(cleaned_content),
                                )
                    elif isinstance(message, dict):
                        content = message.get("content", "")
                        if (
                            isinstance(content, str)
                            and "<" in content
                            and ">" in content
                        ):
                            cleaned_content = self._clean_xml_from_message(content)
                            if cleaned_content != content:
                                message["content"] = cleaned_content

        return CompatibilityResult(
            codex_tools=codex_tools,
            proxy_tools=proxy_tools,
            mcp_tools=mcp_tools,
            tool_results=tool_results,
            state=state,
        )

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        """Apply streaming tool-call translations with owned state.

        Handles streaming where:
        - First chunk for a tool call has {"function": {"name": "shell", "arguments": ""}}
        - Subsequent chunks only have {"function": {"arguments": "..."}}

        Strategy:
        1. When we see a name, cache it and translate to Droid name
        2. Buffer all argument fragments per tool_call_id
        3. When finish_reason=tool_calls, parse complete args and translate them

        Args:
            chunk: Provider stream chunk
            state: Per-request compatibility state

        Returns:
            Translated stream chunk
        """
        if not state.is_droid or not self._droid_translator:
            return chunk
        droid_translator = self._droid_translator

        try:
            import json

            def _translate_tool_call(
                tc: dict[str, Any], finish_reason: str | None
            ) -> None:
                """Translate a single tool call dict in-place."""
                if not isinstance(tc, dict) or "function" not in tc:
                    return

                func = tc.get("function")
                if not isinstance(func, dict):
                    return

                tc_id = tc.get("id", "")
                original_name = func.get("name")
                args_fragment = func.get("arguments", "")

                # If we have a name, cache it and translate
                if original_name:
                    # Cache the original Codex name
                    if tc_id:
                        state.droid_tool_name_cache[tc_id] = original_name

                    # Translate to Droid name
                    try:
                        trans_res = droid_translator.translate_codex_to_droid(
                            original_name, {}
                        )
                        droid_name = trans_res.droid_tool_name
                        func["name"] = droid_name
                        logger.debug(
                            "Translated tool name: %s -> %s (id=%s)",
                            original_name,
                            droid_name,
                            tc_id,
                        )

                    except Exception as e:
                        logger.debug(
                            "Failed to translate tool %s: %s", original_name, e
                        )

                # Buffer argument fragments
                if tc_id and args_fragment:
                    if tc_id not in state.droid_tool_args_buffer:
                        state.droid_tool_args_buffer[tc_id] = ""
                    state.droid_tool_args_buffer[tc_id] += args_fragment

                # When tool call is complete, translate arguments
                if finish_reason == "tool_calls" and tc_id:
                    codex_name = state.droid_tool_name_cache.get(tc_id, "")
                    full_args_str = state.droid_tool_args_buffer.get(tc_id, "{}")

                    if codex_name and full_args_str:
                        try:
                            codex_args = json.loads(full_args_str)
                            trans_res = droid_translator.translate_codex_to_droid(
                                codex_name, codex_args
                            )
                            droid_args = trans_res.droid_arguments
                            # Replace arguments with translated version
                            func["arguments"] = json.dumps(droid_args)

                            logger.debug(
                                "Translated tool args for %s (id=%s): %s -> %s",
                                codex_name,
                                tc_id,
                                full_args_str[:100],
                                func["arguments"][:100],
                            )
                        except json.JSONDecodeError as e:
                            logger.debug(
                                "Failed to parse tool args for %s: %s", tc_id, e
                            )
                        except Exception as e:
                            logger.debug(
                                "Failed to translate tool args for %s: %s", tc_id, e
                            )

                    # Clean up buffers for this tool call
                    state.droid_tool_name_cache.pop(tc_id, None)
                    state.droid_tool_args_buffer.pop(tc_id, None)

            def _process_content(content: Any, finish_reason: str | None) -> None:
                """Process content that may contain tool calls."""
                # Handle CanonicalStreamChunk (Pydantic model with choices)
                if hasattr(content, "choices") and content.choices:
                    for choice in content.choices:
                        fr = getattr(choice, "finish_reason", None) or finish_reason
                        if hasattr(choice, "delta") and choice.delta:
                            delta = choice.delta
                            tool_calls = getattr(delta, "tool_calls", None)
                            if tool_calls:
                                for tc in tool_calls:
                                    if isinstance(tc, dict):
                                        _translate_tool_call(tc, fr)

                # Handle dict-based content with choices
                elif isinstance(content, dict) and "choices" in content:
                    for choice in content.get("choices", []):
                        fr = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta", {})
                        if delta and "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                _translate_tool_call(tc, fr)

            # Detect finish_reason from chunk
            finish_reason = None
            inner = chunk.raw

            if hasattr(inner, "choices"):
                choices_attr = getattr(inner, "choices", None)
                if choices_attr:
                    for choice in choices_attr:  # type: ignore[union-attr]
                        fr = getattr(choice, "finish_reason", None)
                        if fr:
                            finish_reason = fr
                            break
            elif isinstance(inner, dict) and "choices" in inner:
                for choice in inner.get("choices", []):
                    fr = choice.get("finish_reason")
                    if fr:
                        finish_reason = fr
                        break

            # Handle ProcessedResponse wrapper - unwrap to get actual content
            if hasattr(chunk.raw, "content"):
                content_attr = getattr(chunk.raw, "content", None)
                if content_attr is not None:
                    _process_content(content_attr, finish_reason)
                else:
                    _process_content(chunk.raw, finish_reason)
            else:
                _process_content(chunk.raw, finish_reason)

            return chunk

        except Exception as e:
            logger.debug("Droid stream chunk translation failed: %s", str(e))
            return chunk

    async def cleanup_state(self, state: CompatibilityState) -> None:
        """Release per-request state after streaming completes or on error.

        Args:
            state: Compatibility state to clean up
        """
        state.droid_tool_name_cache.clear()
        state.droid_tool_args_buffer.clear()
        state.pending_tool_calls.clear()
        state.is_kilocode = False
        state.is_droid = False

    async def _translate_kilo_tools(
        self, processed_messages: list[ProcessedMessage], session_id: str
    ) -> dict[str, list[CodexToolSchema]]:
        """Parse and translate KiloCode tool invocations.

        Args:
            processed_messages: List of processed messages (may be mutated)
            session_id: Session ID for telemetry

        Returns:
            Dictionary with 'codex_tools', 'proxy_tools', 'mcp_tools' lists
        """
        import json
        import uuid

        result: dict[str, list[CodexToolSchema]] = {
            "codex_tools": [],
            "proxy_tools": [],
            "mcp_tools": [],
        }

        if not self._kilo_translator:
            return result

        # Initialize XML parser if needed
        if self._kilo_translator._xml_parser is None:
            try:
                from src.connectors._openai_codex_xml_tool_parser import XMLToolParser

                self._kilo_translator._xml_parser = XMLToolParser()
            except ImportError:
                logger.debug("XMLToolParser not available")
                return result

        # Process each message
        for message in processed_messages:
            # Extract message content and role
            if isinstance(message, ProcessedMessage):
                content = message.content
                message_role = message.role.lower() if message.role else ""
            else:
                content = message.get("content", "")
                message_role = (
                    message.get("role", "").lower()
                    if isinstance(message.get("role"), str)
                    else ""
                )

            if not isinstance(content, str) or "<" not in content or ">" not in content:
                continue

            try:
                parsed = self._kilo_translator._xml_parser.parse(content)
                if not parsed:
                    continue

                translation_result = (
                    await self._kilo_translator.translate_tool_invocation(
                        parsed.raw_xml, session_id
                    )
                )

                if not translation_result:
                    continue

                tool_name, arguments = translation_result

                # Generate call_id and arguments_json for assistant role messages
                call_id: str | None = None
                arguments_json: str | None = None

                if message_role == "assistant":
                    call_id = f"call_{uuid.uuid4().hex[:16]}"
                    payload_arguments: dict[str, Any] = (
                        arguments if isinstance(arguments, dict) else {}
                    )
                    try:
                        arguments_json = json.dumps(payload_arguments)
                    except (TypeError, ValueError):
                        arguments_json = json.dumps({})

                    # Mutate message to add tool_calls
                    tool_call_entry = {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": arguments_json,
                        },
                    }

                    if isinstance(message, ProcessedMessage):
                        if message.tool_calls is None:
                            message.tool_calls = []
                        try:
                            tool_call_obj = ToolCall.model_validate(tool_call_entry)
                        except Exception:
                            tool_call_obj = cast(ToolCall, tool_call_entry)
                        message.tool_calls.append(tool_call_obj)
                    elif isinstance(message, dict):
                        message.setdefault("tool_calls", []).append(tool_call_entry)

                # Determine execution mode based on tool name prefix
                if tool_name.startswith(
                    ("__proxy_use_mcp_tool", "__proxy_access_mcp_resource")
                ):
                    tool_schema = CodexToolSchema(
                        name=tool_name,
                        description=None,
                        parameters=arguments if isinstance(arguments, dict) else {},
                    )
                    result["mcp_tools"].append(tool_schema)
                elif tool_name.startswith("__proxy_"):
                    tool_schema = CodexToolSchema(
                        name=tool_name,
                        description=None,
                        parameters=arguments if isinstance(arguments, dict) else {},
                    )
                    result["proxy_tools"].append(tool_schema)
                else:
                    tool_schema = CodexToolSchema(
                        name=tool_name,
                        description=None,
                        parameters=arguments if isinstance(arguments, dict) else {},
                    )
                    if call_id:
                        # Store call_id in metadata if needed (for codex_tools)
                        pass  # call_id is already in tool_calls
                    result["codex_tools"].append(tool_schema)

            except Exception as e:
                logger.warning(
                    "Failed to translate XML tools in message: %s",
                    str(e),
                    exc_info=True,
                )

        return result

    def _clean_xml_from_message(self, content: str) -> str:
        """Remove XML tool tags from message content.

        Args:
            content: Message content containing XML tags

        Returns:
            Content with XML tags removed
        """
        if not content or not isinstance(content, str):
            return content

        # Get supported tags from XML parser
        supported_tags = []
        if self._kilo_translator and self._kilo_translator._xml_parser:
            try:
                from src.connectors._openai_codex_xml_tool_parser import XMLToolParser

                supported_tags = list(XMLToolParser.SUPPORTED_TAGS)
            except (ImportError, AttributeError):
                pass

        if not supported_tags:
            # Fallback to common tags
            supported_tags = [
                "read_file",
                "list_files",
                "execute_command",
                "codebase_search",
                "search_files",
                "use_mcp_tool",
                "access_mcp_resource",
                "attempt_completion",
                "ask_followup_question",
                "search_and_replace",
                "write_to_file",
                "insert_content",
                "edit_file",
            ]

        cleaned = content
        for tag in supported_tags:
            # Remove opening and closing tags with content
            pattern = rf"<{tag}(?:\s[^>]*)?>.*?</{tag}>"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

            # Remove self-closing tags
            pattern = rf"<{tag}(?:\s[^>]*)?/>"
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

        # Clean up extra whitespace
        cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)
        cleaned = cleaned.strip()

        return cleaned
