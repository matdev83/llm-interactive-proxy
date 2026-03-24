"""Compatibility layer for OpenAI Codex connector.

This module handles KiloCode and Droid compatibility flows including detection,
tool translation, and streaming chunk translation.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any, Protocol, cast, runtime_checkable

from src.connectors.openai_codex.client_families import (
    ClientFamilyRegistry,
    DroidClientFamilyAdapter,
    KiloClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CodexToolSchema,
    CompatibilityResult,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
    ToolCall,
)
from src.connectors.openai_codex.interfaces import ICompatibilityLayer
from src.connectors.openai_codex.tools import ToolExecutionService

logger = logging.getLogger(__name__)


@runtime_checkable
class _XMLParserLike(Protocol):
    def parse(self, xml_text: str) -> Any: ...


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

        self._family_registry = self._build_family_registry()

    def _build_family_registry(self) -> ClientFamilyRegistry:
        return ClientFamilyRegistry(
            adapters=[
                KiloClientFamilyAdapter(
                    session_detector=self._session_detector,
                    kilo_translator=self._kilo_translator,
                    tool_execution_service=self._tool_execution_service,
                    translate_kilo_tools=self._translate_kilo_tools,
                    clean_xml_from_message=self._clean_xml_from_message,
                ),
                DroidClientFamilyAdapter(
                    droid_detector=self._droid_detector,
                    droid_translator=self._droid_translator,
                ),
            ]
        )

    def _sync_family_registry(self) -> None:
        """Rebuild adapter registry from current dependency fields.

        Tests and runtime wiring may override detector/translator fields after
        construction. Re-syncing preserves that behavior with the new modular
        adapter architecture.
        """
        self._family_registry = self._build_family_registry()

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
        self._sync_family_registry()
        state = self.create_state()
        await self._family_registry.detect_all(context, state)
        merged = await self._family_registry.apply_all(context, state)
        return CompatibilityResult(
            codex_tools=merged.codex_tools,
            proxy_tools=merged.proxy_tools,
            mcp_tools=merged.mcp_tools,
            tool_results=merged.tool_results,
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
        self._sync_family_registry()
        return await self._family_registry.translate_stream_chunk(chunk, state)

    async def cleanup_state(self, state: CompatibilityState) -> None:
        """Release per-request state after streaming completes or on error.

        Args:
            state: Compatibility state to clean up
        """
        self._sync_family_registry()
        await self._family_registry.cleanup_state(state)
        state.pending_tool_calls.clear()

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        self._sync_family_registry()
        return self._family_registry.detect_incompatible_tool_calls(tool_calls, context)

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        self._sync_family_registry()
        return self._family_registry.append_incompatible_tool_steering(
            payload_dict,
            incompatible_tool_names,
            context,
        )

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

        # Initialize XML parser via public translator seam.
        xml_parser = None
        ensure_parser = getattr(self._kilo_translator, "ensure_xml_parser", None)
        if callable(ensure_parser):
            try:
                xml_parser = ensure_parser()
            except Exception as exc:
                logger.debug(
                    "Failed to initialize XMLToolParser via ensure_xml_parser: %s",
                    exc,
                    exc_info=True,
                )
        if xml_parser is None:
            get_parser = getattr(self._kilo_translator, "get_xml_parser", None)
            if callable(get_parser):
                try:
                    xml_parser = get_parser()
                except (AttributeError, TypeError, RuntimeError) as e:
                    # Expected exceptions when XML parser is unavailable or misconfigured
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Could not get XML parser via get_xml_parser: %s",
                            e,
                            exc_info=True,
                        )
                    xml_parser = None
                except Exception as e:
                    # Unexpected errors - log with full context for visibility
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Unexpected error getting XML parser via get_xml_parser: %s",
                            e,
                            exc_info=True,
                        )
                    xml_parser = None
        if not isinstance(xml_parser, _XMLParserLike):
            logger.debug("XMLToolParser not available")
            return result

        # Process each message
        for message in processed_messages:
            # Extract message content and role
            if isinstance(message, ProcessedMessage):  # type: ignore
                content = message.content
                message_role = message.role.lower() if message.role else ""
            else:
                content = message.get("content", "")
                message_role = (
                    message.get("role", "").lower()
                    if isinstance(message.get("role"), str)  # type: ignore
                    else ""
                )

            if not isinstance(content, str) or "<" not in content or ">" not in content:
                continue

            try:
                parsed = xml_parser.parse(content)
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

                    if isinstance(message, ProcessedMessage):  # type: ignore
                        if message.tool_calls is None:
                            message.tool_calls = []
                        try:
                            tool_call_obj = ToolCall.model_validate(tool_call_entry)
                        except (ValueError, TypeError) as e:
                            # Expected validation errors - fallback to cast
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "ToolCall validation failed, using cast fallback: %s",
                                    e,
                                )
                            tool_call_obj = cast(ToolCall, tool_call_entry)
                        except Exception as e:
                            # Unexpected exception during validation (including pydantic ValidationError)
                            logger.warning(
                                "Unexpected error validating ToolCall, using cast fallback: %s",
                                e,
                                exc_info=True,
                            )
                            tool_call_obj = cast(ToolCall, tool_call_entry)
                        message.tool_calls.append(tool_call_obj)
                    elif isinstance(message, dict):  # type: ignore
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

    @staticmethod
    @functools.lru_cache(maxsize=4)
    def _get_xml_cleaning_pattern(tags: tuple[str, ...]) -> re.Pattern[str]:
        """Get cached compiled regex for cleaning XML tags.

        Args:
            tags: Tuple of tag names to remove

        Returns:
            Compiled regex pattern
        """
        tag_group = "|".join(re.escape(t) for t in tags)
        # Match <TAG...>...</TAG> OR <TAG.../>
        # We use a non-capturing group for the tag name alternatives inside the capturing group
        # Pattern 1: Paired tags <(TAG) [attrs]> ... </\1>
        p1 = rf"<({tag_group})(?:\s[^>]*)?>.*?</\1>"
        # Pattern 2: Self-closing tags <(TAG) [attrs]/>
        p2 = rf"<({tag_group})(?:\s[^>]*)?/>"

        return re.compile(f"{p1}|{p2}", flags=re.IGNORECASE | re.DOTALL)

    def _clean_xml_from_message(self, content: str) -> str:
        """Remove XML tool tags from message content.

        Args:
            content: Message content containing XML tags

        Returns:
            Content with XML tags removed
        """
        if not content:
            return content

        # Get supported tags from XML parser
        supported_tags_list = []
        if self._kilo_translator:
            xml_parser = None
            ensure_parser = getattr(self._kilo_translator, "ensure_xml_parser", None)
            if callable(ensure_parser):
                try:
                    xml_parser = ensure_parser()
                except (AttributeError, TypeError, RuntimeError) as e:
                    # Expected exceptions when XML parser is unavailable or misconfigured
                    if logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Could not get XML parser via ensure_xml_parser: %s",
                            e,
                            exc_info=True,
                        )
                    xml_parser = None
                except Exception as e:
                    # Unexpected errors - log with full context for visibility
                    if logger.isEnabledFor(logging.WARNING):
                        logger.warning(
                            "Unexpected error getting XML parser via ensure_xml_parser: %s",
                            e,
                            exc_info=True,
                        )
                    xml_parser = None
            if xml_parser is None:
                get_parser = getattr(self._kilo_translator, "get_xml_parser", None)
                if callable(get_parser):
                    try:
                        xml_parser = get_parser()
                    except (AttributeError, TypeError, RuntimeError) as e:
                        # Expected exceptions when XML parser is unavailable or misconfigured
                        if logger.isEnabledFor(logging.DEBUG):
                            logger.debug(
                                "Could not get XML parser via get_xml_parser: %s",
                                e,
                                exc_info=True,
                            )
                        xml_parser = None
                    except Exception as e:
                        # Unexpected errors - log with full context for visibility
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Unexpected error getting XML parser via get_xml_parser: %s",
                                e,
                                exc_info=True,
                            )
                        xml_parser = None
            supported_tags = getattr(xml_parser, "SUPPORTED_TAGS", None)
            if supported_tags:
                supported_tags_list = list(supported_tags)

        if not supported_tags_list:
            # Fallback to common tags
            supported_tags_list = [
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

        # Sort by length (descending) to ensure longer tags match first in regex alternation
        sorted_tags = tuple(sorted(supported_tags_list, key=len, reverse=True))

        pattern = self._get_xml_cleaning_pattern(sorted_tags)
        cleaned = pattern.sub("", content)

        # Clean up extra whitespace
        cleaned = re.sub(r"\n\s*\n\s*\n", "\n\n", cleaned)
        cleaned = cleaned.strip()

        return cleaned
