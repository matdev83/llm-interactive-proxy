"""Payload builder for OpenAI Codex connector.

This module provides payload construction with passthrough detection.
"""

from __future__ import annotations

import json
import logging
import uuid
from copy import deepcopy
from typing import TYPE_CHECKING, Any, cast

from src.connectors.openai_codex.client_families import (
    ClientFamilyRegistry,
    DroidClientFamilyAdapter,
    KiloClientFamilyAdapter,
    OpenCodeClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexConnectorSettings,
    CodexInputItem,
    CodexPayload,
    CodexRequestContext,
    CodexToolSchema,
    ReasoningSpec,
)
from src.connectors.openai_codex.interfaces import (
    IPayloadBuilder,
    IPromptResolver,
    IRequestTranslator,
    IToolSchemaResolver,
)
from src.connectors.openai_codex.utils import message_to_text

if TYPE_CHECKING:
    from src.connectors.openai_codex import OpenAICodexConnector

logger = logging.getLogger(__name__)


class PayloadBuilder(IPayloadBuilder):
    """Service for building Codex payloads preserving passthrough rules.

    This service handles:
    - Native Responses payload passthrough detection
    - Payload construction from scratch
    - Tool schema resolution
    - Prompt resolution
    - Request translation
    """

    def __init__(
        self,
        connector: OpenAICodexConnector,  # type: ignore[invalid-type-form]
        request_translator: IRequestTranslator,
        prompt_resolver: IPromptResolver,
        tool_schema_resolver: IToolSchemaResolver,
        settings: CodexConnectorSettings,
        message_to_text_converter: Any,
    ) -> None:
        """Initialize the payload builder.

        Args:
            connector: Reference to connector for passthrough detection
            request_translator: Service for translating messages
            prompt_resolver: Service for resolving prompts
            tool_schema_resolver: Service for resolving tool schemas
            settings: Connector settings
            message_to_text_converter: Function to convert messages to text
        """
        self._connector = connector
        self._request_translator = request_translator
        self._prompt_resolver = prompt_resolver
        self._tool_schema_resolver = tool_schema_resolver
        self._settings = settings
        self._message_to_text = message_to_text_converter
        self._family_registry = ClientFamilyRegistry(
            adapters=[
                OpenCodeClientFamilyAdapter(),
                KiloClientFamilyAdapter(
                    session_detector=None,
                    kilo_translator=None,
                    tool_execution_service=None,
                    translate_kilo_tools=self._noop_translate_kilo_tools,
                    clean_xml_from_message=lambda content: content,
                ),
                DroidClientFamilyAdapter(),
            ]
        )

    def build_payload(self, context: CodexRequestContext) -> CodexPayload:
        """Build a Codex payload preserving passthrough rules.

        Args:
            context: Request context with processed messages and capabilities

        Returns:
            Codex API payload ready for submission
        """
        # Check for native passthrough first
        if (
            context.capabilities.codex_passthrough
            and self._is_native_responses_payload(context.request)
        ):
            logger.debug("Executing native Codex/Responses payload passthrough.")
            return self._build_passthrough_payload(context)

        # Build payload from scratch
        return self._build_translated_payload(context)

    def _is_native_responses_payload(self, request_data: Any) -> bool:
        """Detect if a request payload is in the native Codex/Responses format with strict validation."""
        # Use a dict-like view of the request_data
        if hasattr(request_data, "model_dump"):
            data = request_data.model_dump()
        elif isinstance(request_data, dict):
            data = request_data
        else:
            return False

        # If the proxy translated a Responses request into CanonicalChatRequest, it may have
        # stored the raw Responses `input` array in extra_body for passthrough.
        extra_body = data.get("extra_body")
        if isinstance(extra_body, dict) and "input" in extra_body:
            input_val = extra_body.get("input")
            if isinstance(input_val, list):
                return True

        # Early return for obvious OpenAI Chat format (has 'messages' list)
        if (
            "messages" in data
            and isinstance(data.get("messages"), list)
            and not ("prompt_cache_key" in data or "instructions" in data)
        ):
            return False

        # Structural check: does it have an 'input' array with proper structure?
        if "input" in data:
            input_val = data.get("input")
            if not isinstance(input_val, list):
                return False
            # Validate that input items have Responses-specific structure
            if input_val:  # Non-empty list
                first_item = input_val[0]
                if isinstance(first_item, dict):
                    # Responses items have 'type', 'role', 'content' structure
                    # or 'type' like 'function_call', 'function_call_output'
                    has_responses_structure = "type" in first_item or (
                        "role" in first_item and "content" in first_item
                    )
                    if has_responses_structure:
                        return True

        # Look for other distinctive Responses-specific fields
        # These fields are NOT typically in standard OpenAI Chat requests
        responses_specific_fields = {"prompt_cache_key", "include", "store"}
        return any(field in data for field in responses_specific_fields)

    def _build_passthrough_payload(self, context: CodexRequestContext) -> CodexPayload:
        """Build passthrough payload from native Responses format.

        Args:
            context: Request context

        Returns:
            Passthrough payload
        """
        request_data = context.request

        passthrough_dict: dict[str, Any] = {}
        raw_payload: dict[str, Any] | None = None

        if hasattr(request_data, "model_dump"):
            raw_payload = request_data.model_dump(exclude_none=True)
        elif isinstance(request_data, dict):
            raw_payload = deepcopy(dict(request_data))

        # Primary passthrough source: raw Responses payload stored under extra_body["input"] (and friends).
        # This is how /v1/responses requests survive translation into CanonicalChatRequest.
        extra_body = getattr(request_data, "extra_body", None)
        if isinstance(extra_body, dict) and isinstance(extra_body.get("input"), list):
            # Keep only Responses-relevant fields to avoid leaking connector-specific extras.
            for key in (
                "input",
                "instructions",
                "tools",
                "tool_choice",
                "parallel_tool_calls",
                "reasoning",
                "text",
                "include",
                "prompt_cache_key",
                "store",
                "stream",
            ):
                if key in extra_body:
                    passthrough_dict[key] = deepcopy(extra_body[key])
        elif raw_payload is not None:
            passthrough_dict = raw_payload

        # Ensure model is set
        passthrough_dict.setdefault("model", context.effective_model)

        # Codex backend expects streaming SSE; Codex CLI always sets stream=true.
        passthrough_dict["stream"] = True

        # Codex backend requires store=false (stateless). Keep the request stateless even if the client
        # asks otherwise; the ChatGPT backend differs from the Platform API here.
        passthrough_dict["store"] = False

        # Ensure prompt_cache_key exists
        passthrough_dict["prompt_cache_key"] = self._resolve_prompt_cache_key(
            request_data, passthrough_dict
        )

        # Ensure include is present when reasoning is used (Codex CLI behavior).
        if not passthrough_dict.get("include") and passthrough_dict.get("reasoning"):
            passthrough_dict["include"] = ["reasoning.encrypted_content"]

        resolved_instructions = self._resolve_instructions(context)
        passthrough_dict = self._family_registry.adapt_payload_dict(
            passthrough_dict,
            context,
            resolved_instructions=resolved_instructions,
        )

        # Convert to CodexPayload
        # Note: passthrough payload may have different structure, so we need to adapt
        return self.convert_dict_to_payload(passthrough_dict, context)

    def _build_translated_payload(self, context: CodexRequestContext) -> CodexPayload:
        """Build payload from translated messages and tools.

        Args:
            context: Request context

        Returns:
            Translated payload
        """
        # Translate messages to Codex input items (pass context for environment context)
        input_items = self._request_translator.translate_messages(
            context.processed_messages, context=context
        )

        # Resolve tool schemas
        tool_schemas = self._tool_schema_resolver.resolve_tool_schema(context)

        # Resolve reasoning effort
        reasoning_effort = self._resolve_reasoning_effort(context)
        reasoning: ReasoningSpec | None = None
        if reasoning_effort:
            reasoning = ReasoningSpec(effort=reasoning_effort, summary="auto")

        # Resolve system prompt/instructions
        instructions = self._resolve_instructions(context)

        # Build conversation ID
        conversation_id = self._resolve_prompt_cache_key(context.request, None)

        # Codex backend expects streaming SSE; Codex CLI always streams.
        stream_flag = True

        payload_dict: dict[str, Any] = {
            "model": context.effective_model,
            "input": input_items,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "reasoning": reasoning,
            "store": False,
            "stream": bool(stream_flag),
            "include": ["reasoning.encrypted_content"] if reasoning else [],
            "prompt_cache_key": conversation_id,
            "instructions": instructions,
            "extras": None,
        }
        payload_dict = self._family_registry.adapt_payload_dict(
            payload_dict,
            context,
            resolved_instructions=instructions,
        )
        model = cast(str, payload_dict["model"])
        payload_input = cast(list[CodexInputItem], payload_dict["input"])
        payload_tools = cast(list[CodexToolSchema], payload_dict["tools"])
        tool_choice = cast(str, payload_dict["tool_choice"])
        parallel_tool_calls = cast(bool, payload_dict["parallel_tool_calls"])
        payload_reasoning = cast(ReasoningSpec | None, payload_dict["reasoning"])
        store = cast(bool, payload_dict["store"])
        stream = cast(bool, payload_dict["stream"])
        include = cast(list[str], payload_dict["include"])
        prompt_cache_key = cast(str, payload_dict["prompt_cache_key"])
        payload_instructions = cast(str | None, payload_dict["instructions"])
        extras = cast(dict[str, object] | None, payload_dict["extras"])

        # Build payload
        payload = CodexPayload(
            model=model,
            input=payload_input,
            tools=payload_tools,
            tool_choice=tool_choice,
            parallel_tool_calls=parallel_tool_calls,
            reasoning=payload_reasoning,
            store=store,
            stream=stream,
            include=include,
            prompt_cache_key=prompt_cache_key,
            instructions=payload_instructions,
            extras=extras,
        )

        return payload

    @staticmethod
    async def _noop_translate_kilo_tools(
        processed_messages: list[Any], session_id: str
    ) -> dict[str, list[CodexToolSchema]]:
        return {"codex_tools": [], "proxy_tools": [], "mcp_tools": []}

    @staticmethod
    def _resolve_prompt_cache_key(
        request_data: Any, passthrough_dict: dict[str, Any] | None
    ) -> str:
        """Resolve a stable prompt_cache_key/conversation id.

        Priority order mirrors Codex/OpenCode usage:
        1) explicit prompt_cache_key (Responses)
        2) conversation_id/session_id (legacy)
        3) CanonicalChatRequest.session_id (proxy correlation)
        4) UUID fallback
        """
        candidates: list[Any] = []
        if passthrough_dict:
            candidates.extend(
                [
                    passthrough_dict.get("prompt_cache_key"),
                    passthrough_dict.get("conversation_id"),
                    passthrough_dict.get("session_id"),
                ]
            )

        extra_body = getattr(request_data, "extra_body", None)
        if isinstance(extra_body, dict):
            candidates.append(extra_body.get("prompt_cache_key"))
            candidates.append(extra_body.get("conversation_id"))
            candidates.append(extra_body.get("session_id"))

        candidates.append(getattr(request_data, "session_id", None))
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(uuid.uuid4())

    def _resolve_reasoning_effort(self, context: CodexRequestContext) -> str | None:
        """Resolve reasoning effort from request context.

        Args:
            context: Request context

        Returns:
            Reasoning effort level or None
        """
        request_data = context.request

        # Check for pre-resolved effort (from chat_completions)
        if hasattr(request_data, "_codex_resolved_reasoning_effort"):
            resolved = getattr(request_data, "_codex_resolved_reasoning_effort", None)  # type: ignore[attr-defined]
            if isinstance(resolved, str):
                return resolved

        # Check request data attribute
        if hasattr(request_data, "reasoning_effort"):
            effort = request_data.reasoning_effort
            if isinstance(effort, str):
                return effort.lower().strip()

        # Check metadata
        if context.metadata:
            metadata_effort = context.metadata.get("reasoning_effort")
            if isinstance(metadata_effort, str):
                return metadata_effort.lower().strip()

        # Default
        default_effort = getattr(self._connector, "DEFAULT_REASONING_EFFORT", None)
        return default_effort if isinstance(default_effort, str) else None

    def _resolve_instructions(self, context: CodexRequestContext) -> str | None:
        """Resolve system prompt/instructions for payload.

        Args:
            context: Request context

        Returns:
            Sanitized instructions or None
        """
        capabilities = context.capabilities

        # Extract custom instruction sections from request
        custom_sections = self._extract_custom_instruction_sections(context.request)
        custom_clean = [piece for piece in custom_sections if piece]

        # Get base prompt from PromptResolver
        base_prompt = self._prompt_resolver.resolve_system_prompt(
            self._settings, capabilities
        )

        # Merge custom sections based on prompt_mode (matching original logic)
        prompt_mode = (capabilities.prompt_mode or "codex_default").lower()
        prompt_cfg = self._settings.prompt
        prepend_sections = list(prompt_cfg.get("prepend", []))
        append_sections = list(prompt_cfg.get("append", []))
        deduplicate = bool(prompt_cfg.get("deduplicate", True))

        # Enforce robust prompt handling: codex_default always uses default instructions
        if prompt_mode == "codex_default":
            # No custom sections in default mode - always use Codex default
            # This ensures we never send invalid instructions that trigger backend errors
            combined = [*prepend_sections, base_prompt, *append_sections]
        elif prompt_mode == "merge_custom":
            # Merge custom sections with default
            combined = [
                *prepend_sections,
                base_prompt,
                *custom_clean,
                *append_sections,
            ]
        elif prompt_mode == "custom_only":
            # Only custom sections (with fallback)
            combined = prepend_sections + custom_clean + append_sections
            fallback_to_default = bool(prompt_cfg.get("fallback_to_default", True))
            if not combined and fallback_to_default:
                combined = [*prepend_sections, base_prompt, *append_sections]
        else:
            # Unknown prompt_mode: log warning and fallback to default for robustness
            logger.warning(
                "Unknown prompt_mode '%s' in request, falling back to codex_default. "
                "Set prompt_mode to 'codex_default', 'merge_custom', or 'custom_only'.",
                prompt_mode,
            )
            combined = [*prepend_sections, base_prompt, *append_sections]

        # Combine sections using PromptResolver static method
        from src.connectors.openai_codex.prompt import PromptResolver

        result = PromptResolver._combine_prompt_sections(combined, deduplicate)  # type: ignore[reportPrivateUsage]
        if not result:
            return None

        # Sanitize using PromptResolver static method
        sanitized = PromptResolver._sanitize_codex_instructions(result)  # type: ignore[reportPrivateUsage]
        return sanitized if sanitized else None

    def _extract_custom_instruction_sections(self, request_data: Any) -> list[str]:
        """Extract custom instruction sections from request.

        Args:
            request_data: Request data object

        Returns:
            List of instruction sections
        """
        sections: list[str] = []

        # Check system_prompt attribute
        request_prompt = getattr(request_data, "system_prompt", None)
        if isinstance(request_prompt, str) and request_prompt.strip():
            sections.append(request_prompt.strip())

        # Check messages for system role
        messages = getattr(request_data, "messages", [])
        for message in messages or []:
            role = getattr(message, "role", None)
            if role is None and isinstance(message, dict):
                role = message.get("role")
            if (role or "").lower() != "system":
                continue
            # Use converter if available, else util
            text = (
                self._message_to_text(message)
                if self._message_to_text
                else message_to_text(message)
            )
            if text.strip():
                sections.append(text.strip())

        # Check extra_body for codex_system_prompt
        extra_body = getattr(request_data, "extra_body", {}) or {}
        extra_prompt = extra_body.get("codex_system_prompt")
        if isinstance(extra_prompt, str) and extra_prompt.strip():
            sections.append(extra_prompt.strip())
        elif isinstance(extra_prompt, list | tuple):
            for part in extra_prompt:
                if isinstance(part, str) and part.strip():
                    sections.append(part.strip())

        # Deduplicate
        deduplicated: list[str] = []
        seen: set[str] = set()
        for section in sections:
            normalized = section.strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                deduplicated.append(normalized)

        return deduplicated

    def convert_dict_to_payload(
        self, payload_dict: dict[str, Any], context: CodexRequestContext
    ) -> CodexPayload:
        """Convert dictionary payload to CodexPayload model.

        This method handles passthrough format conversion, ensuring that
        dictionary payloads (e.g., from passthrough requests) are properly
        converted to CodexPayload instances with correct field types.

        Args:
            payload_dict: Dictionary containing Codex payload fields
            context: Request context for conversion metadata

        Returns:
            Validated CodexPayload instance
        """
        # Convert input items while preserving structure (and make them safe for Codex stateless mode).
        raw_input = payload_dict.get("input", [])
        safe_input = self._sanitize_responses_input(raw_input)

        input_items: list[CodexInputItem] = []
        for item in safe_input:
            if isinstance(item, dict):
                item_dict = dict(item)
                if "type" not in item_dict and (
                    "role" in item_dict or "content" in item_dict
                ):
                    item_dict["type"] = "message"
                input_items.append(CodexInputItem(**item_dict))
            else:
                input_items.append(
                    CodexInputItem(
                        type="message",
                        content=str(item),
                    )
                )

        # Convert tools
        tools: list[CodexToolSchema] = []
        for tool_candidate in payload_dict.get("tools", []) or []:
            if not isinstance(tool_candidate, dict):
                continue
            tool_dict = dict(tool_candidate)
            function_dict = (
                tool_dict.get("function")
                if isinstance(tool_dict.get("function"), dict)
                else None
            )

            name_value = tool_dict.get("name")
            if not name_value and function_dict:
                name_value = function_dict.get("name")

            if not isinstance(name_value, str) or not name_value.strip():
                continue

            description = tool_dict.get("description")
            parameters = tool_dict.get("parameters")
            fmt = tool_dict.get("format")
            if function_dict:
                if description is None:
                    description = function_dict.get("description")
                if parameters is None:
                    parameters = function_dict.get("parameters")

            tools.append(
                CodexToolSchema(
                    name=name_value.strip(),
                    description=description if isinstance(description, str) else None,
                    parameters=(
                        parameters
                        if isinstance(parameters, dict)
                        else (
                            None
                            if str(tool_dict.get("type", "function")) == "custom"
                            else {}
                        )
                    ),
                    type=tool_dict.get("type", "function"),
                    format=fmt if isinstance(fmt, dict) else None,
                )
            )

        # Extract reasoning
        reasoning: ReasoningSpec | None = None
        if payload_dict.get("reasoning"):
            reason_dict = payload_dict["reasoning"]
            if isinstance(reason_dict, dict):
                reasoning = ReasoningSpec(
                    effort=reason_dict.get("effort", "medium"),
                    summary=reason_dict.get("summary", "auto"),
                )

        return CodexPayload(
            model=payload_dict.get("model", context.effective_model),
            input=input_items,
            tools=tools,
            tool_choice=payload_dict.get("tool_choice", "auto"),
            parallel_tool_calls=payload_dict.get("parallel_tool_calls", False),
            reasoning=reasoning,
            store=payload_dict.get("store", False),
            stream=payload_dict.get("stream", True),
            include=payload_dict.get("include", []),
            prompt_cache_key=payload_dict.get("prompt_cache_key", str(uuid.uuid4())),
            instructions=payload_dict.get("instructions"),
            extras=payload_dict.get("extras"),
        )

    @staticmethod
    def _sanitize_responses_input(input_value: Any) -> list[dict[str, Any] | Any]:
        """Make a Responses `input` array safe for ChatGPT Codex backend.

        - Removes `item_reference` entries (AI SDK/OpenCode server-state references)
        - Strips per-item `id` fields for stateless mode (`store: false`)
        - Removes unsupported per-item `metadata` blocks
        - Converts orphaned `function_call_output` entries into assistant messages
          to preserve context while avoiding backend validation errors
        """
        if not isinstance(input_value, list):
            return []

        filtered: list[dict[str, Any]] = []
        for item in input_value:
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type == "item_reference":
                continue

            item_dict = dict(item)
            item_dict.pop("id", None)
            item_dict.pop("metadata", None)
            filtered.append(item_dict)

        function_call_ids: set[str] = set()
        for item in filtered:
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if isinstance(call_id, str) and call_id:
                    function_call_ids.add(call_id)

        safe: list[dict[str, Any]] = []
        for item in filtered:
            if item.get("type") == "function_call_output":
                call_id = item.get("call_id")
                if (
                    isinstance(call_id, str)
                    and call_id
                    and call_id not in function_call_ids
                ):
                    tool_name = item.get("name")
                    if not isinstance(tool_name, str) or not tool_name:
                        tool_name = "tool"
                    output_val = item.get("output")
                    if isinstance(output_val, str):
                        output_text = output_val
                    else:
                        try:
                            output_text = json.dumps(output_val)
                        except Exception:
                            output_text = str(output_val)

                    if len(output_text) > 16000:
                        output_text = output_text[:16000] + "\n...[truncated]"

                    safe.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": f"[Previous {tool_name} result; call_id={call_id}]: {output_text}",
                                }
                            ],
                        }
                    )
                    continue

            safe.append(item)

        return safe
