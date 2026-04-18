"""Pi family payload adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CompatibilityState,
    ProviderStreamChunk,
)

_PI_BRIDGE_MARKER = "Pi compatibility mode"
_PI_INCOMPATIBLE_MARKER = "Pi incompatible tool retry"
_PI_PROMPT_MARKERS = (
    "operating inside pi",
    "coding agent harness",
    "available tools:",
    "in addition to the tools above",
    "guidelines:",
)
_PI_USER_AGENT_MARKERS = (
    "@mariozechner/pi-coding-agent",
    " pi/",
    "pi-coding-agent",
)
_PI_OPENAI_JS_MARKER = "openai/js"


class _SupportsModelDump(Protocol):
    def model_dump(self, *, exclude_none: bool = ...) -> dict[str, Any]: ...


class PiClientFamilyAdapter(IClientFamilyAdapter):
    """Pi-specific payload shaping for OpenAI Codex backends."""

    family = "pi"

    async def detect(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> None:
        return None

    async def apply(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> FamilyApplyResult:
        return FamilyApplyResult()

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        return chunk

    async def cleanup_state(self, state: CompatibilityState) -> None:
        return None

    def adapt_payload_dict(
        self,
        payload_dict: dict[str, object],
        context: CodexRequestContext,
        *,
        resolved_instructions: str | None = None,
    ) -> dict[str, object]:
        if not self._is_pi_request(context):
            return payload_dict

        result = dict(payload_dict)
        tools = result.get("tools")
        has_tools = isinstance(tools, list) and bool(tools)

        input_items = result.get("input")
        if isinstance(input_items, list):
            result["input"] = self._adapt_input_items(input_items, has_tools=has_tools)

        if not has_tools:
            return result

        instructions = result.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            instructions = resolved_instructions or ""

        result["instructions"] = self._append_instruction_block(
            instructions,
            marker=_PI_BRIDGE_MARKER,
            block=self._build_bridge_prompt(),
        )
        return result

    def _adapt_input_items(
        self,
        input_items: list[object],
        *,
        has_tools: bool,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in input_items:
            normalized_item = self._normalize_input_item(item)
            if normalized_item is None:
                continue
            if self._is_pi_system_prompt_item(normalized_item):
                continue
            normalized.append(normalized_item)

        if has_tools and not any(
            self._is_bridge_message_item(item) for item in normalized
        ):
            normalized.insert(0, self._build_bridge_message_item())

        return normalized

    @staticmethod
    def _normalize_input_item(item: object) -> dict[str, Any] | None:
        if isinstance(item, Mapping):
            return dict(item)
        if hasattr(item, "model_dump"):
            dumped = cast(_SupportsModelDump, item).model_dump(exclude_none=True)
            if isinstance(dumped, dict):
                return dict(dumped)
        return None

    def _is_pi_system_prompt_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            return False
        text = self._extract_item_text(item).lower()
        return any(marker in text for marker in _PI_PROMPT_MARKERS)

    def _is_bridge_message_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        return _PI_BRIDGE_MARKER in self._extract_item_text(item)

    def _build_bridge_message_item(self) -> dict[str, Any]:
        return {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": self._build_bridge_prompt(),
                }
            ],
        }

    @staticmethod
    def _extract_item_text(item: Mapping[str, Any]) -> str:
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, Sequence):
            return ""
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts)

    @classmethod
    def _is_pi_request(cls, context: CodexRequestContext) -> bool:
        candidates: list[str] = []

        if context.metadata:
            agent = context.metadata.get("agent")
            if isinstance(agent, str):
                candidates.append(agent)
            headers = context.metadata.get("headers")
            if isinstance(headers, Mapping):
                user_agent = headers.get("user-agent") or headers.get("User-Agent")
                if isinstance(user_agent, str):
                    candidates.append(user_agent)

        request_agent = getattr(context.request, "agent", None)
        if isinstance(request_agent, str):
            candidates.append(request_agent)

        extra_body = getattr(context.request, "extra_body", None)
        if isinstance(extra_body, Mapping):
            extra_agent = extra_body.get("agent")
            if isinstance(extra_agent, str):
                candidates.append(extra_agent)

        normalized_candidates = [candidate.lower() for candidate in candidates]
        if any(
            marker in candidate
            for candidate in normalized_candidates
            for marker in _PI_USER_AGENT_MARKERS
        ):
            return True

        prompt_text = cls._collect_prompt_text(context).lower()
        prompt_marker_hits = sum(
            1 for marker in _PI_PROMPT_MARKERS if marker in prompt_text
        )
        has_pi_prompt = prompt_marker_hits >= 2
        if has_pi_prompt and any(
            _PI_OPENAI_JS_MARKER in candidate for candidate in normalized_candidates
        ):
            return True

        return has_pi_prompt and "current working directory:" in prompt_text

    @classmethod
    def _collect_prompt_text(cls, context: CodexRequestContext) -> str:
        parts: list[str] = []
        for message in context.processed_messages:
            content = message.content
            if isinstance(content, str):
                parts.append(content)
                continue
            for part in content:
                text = part.text
                if isinstance(text, str) and text.strip():
                    parts.append(text)

        for message in getattr(context.request, "messages", None) or []:
            request_content: object | None
            if isinstance(message, Mapping):
                request_content = message.get("content")
            else:
                request_content = getattr(message, "content", None)
            if isinstance(request_content, str) and request_content.strip():
                parts.append(request_content)
        return "\n".join(parts)

    @staticmethod
    def _build_bridge_prompt() -> str:
        return (
            f"{_PI_BRIDGE_MARKER}:\n"
            "- Use only tools exposed by the pi client for this session.\n"
            "- Use `bash` for terminal execution with a JSON object containing string `command` and optional numeric `timeout` in seconds; pi has no default timeout.\n"
            "- Do not emit `shell`, `local_shell_call`, or array-valued shell commands; pi expects the `bash` tool name.\n"
            "- Do not use `apply_patch`; use pi's `edit` tool for exact text replacement in a single file.\n"
            "- For `edit`, pass `path` plus an `edits` array of replacements with `oldText` and `newText`, each matched against the original file.\n"
            "- For file reads use `read` with `path` and optional `offset`/`limit`; for full rewrites use `write` with `path` and `content`.\n"
            "- Keep responses concise and show file paths clearly."
        )

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._is_pi_request(context):
            return []

        supported_tools = self._resolve_supported_tool_names(context)
        incompatible: list[str] = []
        for tool_call in tool_calls:
            function = tool_call.get("function")
            if not isinstance(function, Mapping):
                continue
            tool_name = function.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                continue
            normalized = tool_name.strip().lower()
            if normalized not in supported_tools:
                incompatible.append(tool_name.strip())
        return incompatible

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        if not self._is_pi_request(context) or not incompatible_tool_names:
            return payload_dict

        result = dict(payload_dict)
        steering = self._build_incompatible_tool_steering(
            incompatible_tool_names,
            context,
        )
        instructions = result.get("instructions")
        if isinstance(instructions, str) and _PI_INCOMPATIBLE_MARKER in instructions:
            return result
        result["instructions"] = self._append_instruction_block(
            instructions if isinstance(instructions, str) else "",
            marker=_PI_INCOMPATIBLE_MARKER,
            block=steering,
        )
        return result

    def _resolve_supported_tool_names(self, context: CodexRequestContext) -> set[str]:
        supported: set[str] = set()
        for tool in getattr(context.request, "tools", None) or []:
            tool_name = self._extract_request_tool_name(tool)
            if tool_name:
                supported.add(tool_name.lower())
        return supported

    @staticmethod
    def _extract_request_tool_name(tool: object) -> str | None:
        if isinstance(tool, Mapping):
            name = tool.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
            function = tool.get("function")
            if isinstance(function, Mapping):
                function_name = function.get("name")
                if isinstance(function_name, str) and function_name.strip():
                    return function_name.strip()
            return None
        if hasattr(tool, "function"):
            function = getattr(tool, "function", None)
            name = getattr(function, "name", None)
            if isinstance(name, str) and name.strip():
                return name.strip()
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def _build_incompatible_tool_steering(
        self,
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> str:
        available_tools = sorted(self._resolve_supported_tool_names(context))
        blocked = ", ".join(dict.fromkeys(incompatible_tool_names))
        available = (
            ", ".join(available_tools) if available_tools else "bash, read, edit, write"
        )
        return (
            f"{_PI_INCOMPATIBLE_MARKER}:\n"
            f"- Do not call these incompatible tools again: {blocked}.\n"
            "- This pi session can execute only the tools provided by the client.\n"
            f"- Use only these compatible tools: {available}.\n"
            "- Prefer `bash` for terminal commands, `read` for file inspection, `edit` for precise patches, and `write` for full rewrites.\n"
            "- `apply_patch`, `shell`, and other Codex-native tools are not available in pi."
        )

    @staticmethod
    def _append_instruction_block(
        instructions: str,
        *,
        marker: str,
        block: str,
    ) -> str:
        if marker in instructions:
            return instructions
        if instructions.strip():
            return f"{instructions.rstrip()}\n\n{block}"
        return block
