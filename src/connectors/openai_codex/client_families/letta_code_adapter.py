"""Letta Code family payload adapter."""

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

_LETTA_BRIDGE_MARKER = "Letta Code compatibility mode"
_LETTA_INCOMPATIBLE_MARKER = "Letta Code incompatible tool retry"
_LETTA_CRITICAL_INSTRUCTION = (
    "CRITICAL INSTRUCTION:\n"
    "(a) NEVER run cat inside a bash command to create a file or append to an "
    "existing file. Use respective tools provided by the Letta Code agent instead.\n"
    "(b) DO NOT use bash commands like ls for listing, cat for viewing, grep for "
    "string matching. Use respective tools provided by the Letta Code agent instead."
)
_LETTA_AGENT_MARKERS = (
    "letta-code",
    "@letta-ai/letta-code",
    "letta code",
    "letta_code",
)
_LETTA_PROMPT_MARKERS = (
    "you are letta code",
    "you are codex, a coding agent based on gpt-5",
    "you have two channels for staying in conversation with the user",
    "`commentary` channel",
    "`final` channel",
    "letta agent",
    "experiential learning",
    "memory filesystem",
    "memfs",
)
_LETTA_DISTINCTIVE_TOOLS = {
    "askuserquestion",
    "enterplanmode",
    "exitplanmode",
    "shellcommand",
    "task",
    "taskoutput",
    "taskstop",
    "skill",
    "updateplan",
}


class _SupportsModelDump(Protocol):
    def model_dump(self, *, exclude_none: bool = ...) -> dict[str, Any]: ...


class LettaCodeClientFamilyAdapter(IClientFamilyAdapter):
    """Letta Code-specific payload shaping for OpenAI Codex backends."""

    family = "letta_code"

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
        if not self._is_letta_request(context):
            return payload_dict

        result = dict(payload_dict)
        tools = result.get("tools")
        has_tools = isinstance(tools, list) and bool(tools)

        input_items = result.get("input")
        if isinstance(input_items, list):
            result["input"] = self._adapt_input_items(
                input_items,
                has_tools=has_tools,
                available_tools=self._resolve_supported_tool_labels(context),
            )

        if not has_tools:
            return result

        instructions = result.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            instructions = resolved_instructions or ""

        result["instructions"] = self._append_instruction_block(
            instructions,
            marker=_LETTA_BRIDGE_MARKER,
            block=self._build_bridge_prompt(
                self._resolve_supported_tool_labels(context),
            ),
        )
        return result

    def _adapt_input_items(
        self,
        input_items: list[object],
        *,
        has_tools: bool,
        available_tools: list[str],
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in input_items:
            normalized_item = self._normalize_input_item(item)
            if normalized_item is None:
                continue
            if self._is_letta_system_prompt_item(normalized_item):
                continue
            normalized.append(normalized_item)

        if has_tools and not any(
            self._is_bridge_message_item(item) for item in normalized
        ):
            normalized.insert(0, self._build_bridge_message_item(available_tools))

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

    def _is_letta_system_prompt_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            return False
        text = self._extract_item_text(item).lower()
        marker_hits = sum(1 for marker in _LETTA_PROMPT_MARKERS if marker in text)
        if marker_hits < 2:
            return False
        return (
            "letta" in text
            or "commentary" in text
            or "final" in text
            or "memfs" in text
        )

    def _is_bridge_message_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        return _LETTA_BRIDGE_MARKER in self._extract_item_text(item)

    def _build_bridge_message_item(self, available_tools: list[str]) -> dict[str, Any]:
        return {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": self._build_bridge_prompt(available_tools),
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
    def _is_letta_request(cls, context: CodexRequestContext) -> bool:
        candidates: list[str] = []

        if context.metadata:
            agent = context.metadata.get("agent")
            if isinstance(agent, str):
                candidates.append(agent)
            headers = context.metadata.get("headers")
            if isinstance(headers, Mapping):
                for header_key in (
                    "user-agent",
                    "User-Agent",
                    "x-letta-source",
                    "X-Letta-Source",
                ):
                    header_value = headers.get(header_key)
                    if isinstance(header_value, str) and header_value.strip():
                        candidates.append(header_value)

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
            for marker in _LETTA_AGENT_MARKERS
        ):
            return True

        prompt_text = cls._collect_prompt_text(context).lower()
        prompt_marker_hits = sum(
            1 for marker in _LETTA_PROMPT_MARKERS if marker in prompt_text
        )
        has_prompt_evidence = prompt_marker_hits >= 2 and (
            "commentary" in prompt_text or "letta code" in prompt_text
        )
        if has_prompt_evidence:
            return True

        supported_tools = cls._resolve_supported_tool_names(context)
        return bool(supported_tools.intersection(_LETTA_DISTINCTIVE_TOOLS)) and any(
            "letta" in candidate for candidate in normalized_candidates
        )

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

    def _build_bridge_prompt(self, available_tools: list[str]) -> str:
        available = ", ".join(f"`{name}`" for name in available_tools)
        if not available:
            available = "`ShellCommand`, `ApplyPatch`, `UpdatePlan`"
        return (
            f"{_LETTA_BRIDGE_MARKER}:\n"
            "- This session uses Letta Code client tools, not the native Codex CLI harness tools.\n"
            f"- Use only tool names that are available in this session: {available}.\n"
            "- Prefer `ShellCommand` for terminal execution; keep arguments as a JSON object with string `command` (never an array).\n"
            "- Prefer `ApplyPatch` for patch edits and `UpdatePlan` for planning updates when available.\n"
            "- Use Letta planning/subagent tools such as `Task`, `TaskOutput`, `TaskStop`, `Skill`, `AskUserQuestion`, `EnterPlanMode`, and `ExitPlanMode` when present.\n"
            "- Do not emit Codex-native tool names like `shell`, `bash`, `local_shell_call`, `read_file`, `list_dir`, or `grep_files` unless they are explicitly provided in this session tool list.\n"
            "\n"
            f"{_LETTA_CRITICAL_INSTRUCTION}"
        )

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._is_letta_request(context):
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
        if not self._is_letta_request(context) or not incompatible_tool_names:
            return payload_dict

        result = dict(payload_dict)
        instructions = result.get("instructions")
        if isinstance(instructions, str) and _LETTA_INCOMPATIBLE_MARKER in instructions:
            return result

        result["instructions"] = self._append_instruction_block(
            instructions if isinstance(instructions, str) else "",
            marker=_LETTA_INCOMPATIBLE_MARKER,
            block=self._build_incompatible_tool_steering(
                incompatible_tool_names,
                context,
            ),
        )
        return result

    @classmethod
    def _resolve_supported_tool_names(cls, context: CodexRequestContext) -> set[str]:
        supported: set[str] = set()
        for tool in getattr(context.request, "tools", None) or []:
            tool_name = cls._extract_request_tool_name(tool)
            if tool_name:
                supported.add(tool_name.lower())
        return supported

    @classmethod
    def _resolve_supported_tool_labels(cls, context: CodexRequestContext) -> list[str]:
        labels: list[str] = []
        seen: set[str] = set()
        for tool in getattr(context.request, "tools", None) or []:
            tool_name = cls._extract_request_tool_name(tool)
            if not tool_name:
                continue
            normalized = tool_name.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            labels.append(tool_name)
        return labels

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
        available_tools = self._resolve_supported_tool_labels(context)
        blocked = ", ".join(dict.fromkeys(incompatible_tool_names))
        available = (
            ", ".join(f"`{tool}`" for tool in available_tools)
            if available_tools
            else "`ShellCommand`, `ApplyPatch`, `UpdatePlan`"
        )
        return (
            f"{_LETTA_INCOMPATIBLE_MARKER}:\n"
            f"- Do not call these incompatible tools again: {blocked}.\n"
            "- This Letta Code session can only execute tools exposed by the Letta client.\n"
            f"- Use only compatible tools from this session: {available}.\n"
            "- Prefer `ShellCommand` for terminal commands, `ApplyPatch` for patches, and `UpdatePlan` for plan updates when available.\n"
            "- Keep using Letta-native orchestration tools like `Task`, `TaskOutput`, `TaskStop`, and `Skill` when they are present.\n"
            "\n"
            f"{_LETTA_CRITICAL_INSTRUCTION}"
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
