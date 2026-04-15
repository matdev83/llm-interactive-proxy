"""OpenCode family payload adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CompatibilityState,
    ProviderStreamChunk,
)

_OPENCODE_BRIDGE_MARKER = "OpenCode compatibility mode"
_OPENCODE_INCOMPATIBLE_MARKER = "OpenCode incompatible tool retry"


class OpenCodeClientFamilyAdapter(IClientFamilyAdapter):
    """OpenCode-specific payload shaping.

    The Codex backend still owns its hidden tool semantics. This adapter only
    nudges the explicit request contract so OpenCode-style clients receive tool
    calls that match their stricter shell schema.
    """

    family = "opencode"

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
        if not self._is_opencode_request(context):
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
            marker=_OPENCODE_BRIDGE_MARKER,
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
        known_call_ids: set[str] = set()

        for item in input_items:
            normalized_item = self._normalize_input_item(item)
            if normalized_item is None:
                continue
            if self._is_opencode_system_prompt_item(normalized_item):
                continue
            item_type = str(normalized_item.get("type") or "").strip().lower()
            if item_type == "function_call":
                call_id = normalized_item.get("call_id")
                if isinstance(call_id, str) and call_id.strip():
                    known_call_ids.add(call_id.strip())
            normalized.append(normalized_item)

        bridged_items: list[dict[str, Any]] = []
        for item in normalized:
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "function_call_output":
                call_id = item.get("call_id")
                if (
                    isinstance(call_id, str)
                    and call_id.strip()
                    and call_id in known_call_ids
                ):
                    bridged_items.append(item)
                    continue
                bridged_items.append(
                    self._convert_orphaned_tool_output_to_message(item)
                )
                continue
            bridged_items.append(item)

        if has_tools and not any(
            self._is_bridge_message_item(item) for item in bridged_items
        ):
            bridged_items.insert(0, self._build_bridge_message_item())

        return bridged_items

    @staticmethod
    def _normalize_input_item(item: object) -> dict[str, Any] | None:
        if isinstance(item, Mapping):
            normalized = dict(item)
        elif hasattr(item, "model_dump"):
            item_with_dump = item
            dumped = item_with_dump.model_dump(exclude_none=True)  # type: ignore[attr-defined]
            if not isinstance(dumped, dict):
                return None
            normalized = dict(dumped)
        else:
            return None

        return normalized

    def _is_opencode_system_prompt_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            return False
        text = self._extract_item_text(item).lower()
        return "opencode" in text and "tool" in text

    def _is_bridge_message_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        return _OPENCODE_BRIDGE_MARKER in self._extract_item_text(item)

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
        if not isinstance(content, list):
            return ""
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _convert_orphaned_tool_output_to_message(
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        call_id = item.get("call_id")
        output = item.get("output")
        if isinstance(output, str):
            rendered_output = output
        else:
            rendered_output = json.dumps(output, ensure_ascii=True, default=str)

        header = "Prior tool output (original tool call reference unavailable)."
        if isinstance(call_id, str) and call_id.strip():
            header = f"{header} call_id={call_id.strip()}."

        return {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": f"{header}\n{rendered_output}",
                }
            ],
        }

    @staticmethod
    def _is_opencode_request(context: CodexRequestContext) -> bool:
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

        return any("opencode" in candidate.lower() for candidate in candidates)

    @staticmethod
    def _build_bridge_prompt() -> str:
        return (
            f"{_OPENCODE_BRIDGE_MARKER}:\n"
            "- Prefer the available client shell tool when command execution is needed.\n"
            "- For bash-style tools, arguments MUST be a JSON object with string "
            "`command` and string `description`.\n"
            "- Never emit array-valued `command` arguments for shell execution.\n"
            "- Do not use `apply_patch`; use the client's native file editing tools instead.\n"
            "- Do not use `update_plan` or `read_plan`; use the client's task tools instead.\n"
            "- If you need a working directory and the schema does not expose one, "
            "mention it in `description`."
        )

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._is_opencode_request(context):
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
        if not self._is_opencode_request(context) or not incompatible_tool_names:
            return payload_dict

        result = dict(payload_dict)
        steering = self._build_incompatible_tool_steering(
            incompatible_tool_names,
            context,
        )
        instructions = result.get("instructions")
        if (
            isinstance(instructions, str)
            and _OPENCODE_INCOMPATIBLE_MARKER in instructions
        ):
            return result
        result["instructions"] = self._append_instruction_block(
            instructions if isinstance(instructions, str) else "",
            marker=_OPENCODE_INCOMPATIBLE_MARKER,
            block=steering,
        )
        return result

    def _resolve_supported_tool_names(self, context: CodexRequestContext) -> set[str]:
        supported: set[str] = set()
        for tool in getattr(context.request, "tools", None) or []:
            tool_name = self._extract_request_tool_name(tool)
            if not tool_name:
                continue
            normalized = tool_name.lower()
            supported.add(normalized)
            if normalized in {"bash", "shell"}:
                supported.update({"bash", "shell", "local_shell_call"})
            if normalized == "apply_patch":
                supported.add("apply_patch")
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
        blocked = ", ".join(incompatible_tool_names)
        available = ", ".join(available_tools) if available_tools else "bash"
        return (
            f"{_OPENCODE_INCOMPATIBLE_MARKER}:\n"
            f"- Do not call these incompatible tools again: {blocked}.\n"
            "- This client cannot execute those Codex-native tools.\n"
            f"- Use only tools compatible with this client: {available}.\n"
            "- Prefer shell execution via `bash`/`shell` for unsupported Codex operations.\n"
            "- For shell execution, arguments MUST be a JSON object with string "
            "`command` and string `description`."
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
