"""Factory Droid family compatibility adapter."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
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
from src.core.app.constants.logging_constants import TRACE_LEVEL

logger = logging.getLogger(__name__)

_DROID_BRIDGE_MARKER = "Factory Droid compatibility mode"
_DROID_INCOMPATIBLE_MARKER = "Factory Droid incompatible tool retry"
_DROID_CRITICAL_INSTRUCTION = (
    "CRITICAL INSTRUCTION:\n"
    "(a) NEVER run cat inside a bash command to create a file or append to an "
    "existing file. Use respective tools provided by the Droid agent instead.\n"
    "(b) DO NOT use bash commands like ls for listing, cat for viewing, grep for "
    "string matching. Use respective tools provided by the Droid agent instead."
)
_DROID_NATIVE_TOOL_NAMES = {
    "Read",
    "LS",
    "Execute",
    "Edit",
    "Grep",
    "Glob",
    "Create",
    "TodoWrite",
    "WebSearch",
    "FetchUrl",
    "ExitSpecMode",
}
_DROID_TOOL_EQUIVALENTS = {
    "read": {"Read"},
    "read_file": {"Read"},
    "view_image": {"Read"},
    "ls": {"LS"},
    "list_dir": {"LS"},
    "execute": {"Execute"},
    "shell": {"Execute"},
    "bash": {"Execute"},
    "grep": {"Grep"},
    "grep_files": {"Grep"},
    "glob": {"Glob"},
    "create": {"Create"},
    "write": {"Create"},
    "edit": {"Edit"},
    "apply_patch": {"Edit", "Create"},
    "todowrite": {"TodoWrite"},
    "websearch": {"WebSearch"},
    "fetchurl": {"FetchUrl"},
    "exitspecmode": {"ExitSpecMode"},
}


class _SupportsModelDump(Protocol):
    def model_dump(self, *, exclude_none: bool = ...) -> dict[str, Any]: ...


class DroidClientFamilyAdapter(IClientFamilyAdapter):
    """Droid-specific detection, steering, and stream translation behavior."""

    family = "droid"

    def __init__(
        self,
        *,
        droid_detector: Any | None = None,
        droid_translator: Any | None = None,
    ) -> None:
        self._droid_detector = droid_detector
        self._droid_translator = droid_translator

    async def detect(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> None:
        detector = self._ensure_droid_detector()
        if detector is None:
            return

        try:
            request_tools = getattr(context.request, "tools", []) or []
            tools_for_detection: list[dict[str, Any]] = []
            for tool in request_tools:
                if isinstance(tool, Mapping):
                    tools_for_detection.append(dict(cast(Mapping[str, Any], tool)))
                elif hasattr(tool, "model_dump"):
                    tools_for_detection.append(
                        cast(_SupportsModelDump, tool).model_dump(exclude_none=True)
                    )

            messages_for_detection: list[dict[str, Any]] = []
            for msg in context.processed_messages:
                messages_for_detection.append(msg.model_dump())

            headers: dict[str, str] | None = None
            if context.metadata:
                headers_candidate = context.metadata.get("headers")
                if isinstance(headers_candidate, dict):
                    headers = {str(k): str(v) for k, v in headers_candidate.items()}

            droid_detection = detector.detect(
                headers=headers,
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
                self._ensure_droid_translator()
        except Exception as e:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "Droid detection failed: %s",
                    str(e),
                    exc_info=True,
                )

    async def apply(
        self, context: CodexRequestContext, state: CompatibilityState
    ) -> FamilyApplyResult:
        return FamilyApplyResult()

    async def translate_stream_chunk(
        self, chunk: ProviderStreamChunk, state: CompatibilityState
    ) -> ProviderStreamChunk:
        if not state.is_droid or not self._droid_translator:
            return chunk
        droid_translator = self._droid_translator

        try:

            def _translate_tool_call(
                tc: dict[str, Any], finish_reason: str | None
            ) -> None:
                if "function" not in tc:
                    return
                func = tc.get("function")
                if not isinstance(func, dict):
                    return
                func = cast(dict[str, Any], func)

                tc_id = tc.get("id", "")
                original_name = func.get("name")
                args_fragment = func.get("arguments", "")

                if original_name:
                    if tc_id:
                        state.droid_tool_name_cache[tc_id] = original_name

                    try:
                        trans_res = droid_translator.translate_codex_to_droid(
                            original_name, {}
                        )
                        func["name"] = trans_res.droid_tool_name
                    except Exception as e:
                        if logger.isEnabledFor(TRACE_LEVEL):
                            logger.log(
                                TRACE_LEVEL,
                                "Failed to translate tool %s: %s",
                                original_name,
                                e,
                                exc_info=True,
                            )

                if tc_id and args_fragment:
                    if tc_id not in state.droid_tool_args_buffer:
                        state.droid_tool_args_buffer[tc_id] = ""
                    state.droid_tool_args_buffer[tc_id] += args_fragment

                if finish_reason == "tool_calls" and tc_id:
                    codex_name = state.droid_tool_name_cache.get(tc_id, "")
                    full_args_str = state.droid_tool_args_buffer.get(tc_id, "{}")

                    if codex_name and full_args_str:
                        try:
                            codex_args = json.loads(full_args_str)
                            trans_res = droid_translator.translate_codex_to_droid(
                                codex_name, codex_args
                            )
                            func["arguments"] = json.dumps(trans_res.droid_arguments)
                        except Exception as e:
                            if logger.isEnabledFor(TRACE_LEVEL):
                                logger.log(
                                    TRACE_LEVEL,
                                    "Failed to translate tool args for %s: %s",
                                    tc_id,
                                    e,
                                    exc_info=True,
                                )

                    state.droid_tool_name_cache.pop(tc_id, None)
                    state.droid_tool_args_buffer.pop(tc_id, None)

            def _process_content(content: Any, finish_reason: str | None) -> None:
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
                elif isinstance(content, dict) and "choices" in content:
                    for choice in content.get("choices", []):
                        fr = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta", {})
                        if delta and "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                _translate_tool_call(tc, fr)

            finish_reason = None
            inner = chunk.raw
            if hasattr(inner, "choices"):
                choices_attr = getattr(inner, "choices", None)
                if choices_attr:
                    for choice in choices_attr:
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
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(
                    TRACE_LEVEL,
                    "Droid stream chunk translation failed: %s",
                    str(e),
                    exc_info=True,
                )
            return chunk

    async def cleanup_state(self, state: CompatibilityState) -> None:
        state.droid_tool_name_cache.clear()
        state.droid_tool_args_buffer.clear()
        state.is_droid = False

    def adapt_payload_dict(
        self,
        payload_dict: dict[str, object],
        context: CodexRequestContext,
        *,
        resolved_instructions: str | None = None,
    ) -> dict[str, object]:
        if not self._is_droid_request(context):
            return payload_dict

        result = dict(payload_dict)
        tools = result.get("tools")
        has_tools = isinstance(tools, list) and bool(tools)

        input_items = result.get("input")
        if isinstance(input_items, list) and has_tools:
            result["input"] = self._adapt_input_items(input_items)

        if not has_tools:
            return result

        instructions = result.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            instructions = resolved_instructions or ""

        available_tools = sorted(self._resolve_supported_tool_names(context))
        result["instructions"] = self._append_instruction_block(
            instructions,
            marker=_DROID_BRIDGE_MARKER,
            block=self._build_bridge_prompt(available_tools),
        )
        return result

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        if not self._is_droid_request(context):
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
            if not self._is_supported_tool_name(tool_name.strip(), supported_tools):
                incompatible.append(tool_name.strip())
        return incompatible

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        if not self._is_droid_request(context) or not incompatible_tool_names:
            return payload_dict

        result = dict(payload_dict)
        instructions = result.get("instructions")
        if isinstance(instructions, str) and _DROID_INCOMPATIBLE_MARKER in instructions:
            return result

        result["instructions"] = self._append_instruction_block(
            instructions if isinstance(instructions, str) else "",
            marker=_DROID_INCOMPATIBLE_MARKER,
            block=self._build_incompatible_tool_steering(
                incompatible_tool_names,
                context,
            ),
        )
        return result

    def _ensure_droid_detector(self) -> Any | None:
        detector = self._droid_detector
        if detector is not None:
            return detector
        try:
            from src.connectors._openai_codex_droid_session_detector import (
                DroidSessionDetector,
            )

            detector = DroidSessionDetector()
            self._droid_detector = detector
            return detector
        except ImportError:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "Droid session detector not available")
            return None

    def _ensure_droid_translator(self) -> Any | None:
        if self._droid_translator is not None:
            return self._droid_translator
        try:
            from src.connectors._openai_codex_droid_tool_translator import (
                DroidToolTranslator,
            )

            self._droid_translator = DroidToolTranslator()
            return self._droid_translator
        except ImportError:
            if logger.isEnabledFor(TRACE_LEVEL):
                logger.log(TRACE_LEVEL, "Droid tool translator not available")
            return None

    def _is_droid_request(self, context: CodexRequestContext) -> bool:
        detector = self._ensure_droid_detector()
        if detector is None:
            return False

        try:
            headers: dict[str, str] | None = None
            if context.metadata:
                headers_candidate = context.metadata.get("headers")
                if isinstance(headers_candidate, Mapping):
                    headers = {str(k): str(v) for k, v in headers_candidate.items()}

            messages = self._collect_message_dicts(context)
            tools = self._collect_request_tool_dicts(context)
            return bool(
                detector.detect(
                    headers=headers, messages=messages, tools=tools
                ).is_droid
            )
        except Exception:
            return False

    def _collect_message_dicts(
        self, context: CodexRequestContext
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for msg in context.processed_messages:
            collected.append(msg.model_dump())
        return collected

    def _collect_request_tool_dicts(
        self, context: CodexRequestContext
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for tool in getattr(context.request, "tools", None) or []:
            if isinstance(tool, Mapping):
                collected.append(dict(tool))
            elif hasattr(tool, "model_dump"):
                dumped = tool.model_dump(exclude_none=True)
                if isinstance(dumped, dict):
                    collected.append(dict(dumped))
        return collected

    def _adapt_input_items(self, input_items: list[object]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in input_items:
            normalized_item = self._normalize_input_item(item)
            if normalized_item is None:
                continue
            if self._is_droid_system_prompt_item(normalized_item):
                continue
            normalized.append(normalized_item)

        if not any(self._is_bridge_message_item(item) for item in normalized):
            normalized.insert(0, self._build_bridge_message_item())
        return normalized

    @staticmethod
    def _normalize_input_item(item: object) -> dict[str, Any] | None:
        if isinstance(item, Mapping):
            return dict(item)
        if hasattr(item, "model_dump"):
            dumped = cast(_SupportsModelDump, item).model_dump(exclude_none=True)
            return dict(dumped)
        return None

    def _is_droid_system_prompt_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        role = str(item.get("role") or "").strip().lower()
        if role not in {"system", "developer"}:
            return False
        text = self._extract_item_text(item).lower()
        return "factory droid" in text and "execute" in text and "todowrite" in text

    def _is_bridge_message_item(self, item: Mapping[str, Any]) -> bool:
        if str(item.get("type") or "").strip().lower() != "message":
            return False
        return _DROID_BRIDGE_MARKER in self._extract_item_text(item)

    def _build_bridge_message_item(self) -> dict[str, Any]:
        return {
            "type": "message",
            "role": "developer",
            "content": [
                {
                    "type": "input_text",
                    "text": self._build_bridge_prompt(sorted(_DROID_NATIVE_TOOL_NAMES)),
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
    def _build_bridge_prompt(available_tools: list[str]) -> str:
        if available_tools:
            available_tool_text = ", ".join(f"`{tool}`" for tool in available_tools)
        else:
            available_tool_text = ", ".join(
                f"`{tool}`" for tool in sorted(_DROID_NATIVE_TOOL_NAMES)
            )
        native_tool_text = ", ".join(
            f"`{tool}`" for tool in sorted(_DROID_NATIVE_TOOL_NAMES)
        )
        return (
            f"{_DROID_BRIDGE_MARKER}:\n"
            "- This session is using Factory Droid tools, not Codex-native tools.\n"
            f"- Use only tool names that are actually available in this session: {available_tool_text}.\n"
            f"- Prefer the native Factory Droid tool family when available: {native_tool_text}.\n"
            "- Preserve extra already-available tools such as `Skill`, `Task`, or `fff___*` search tools when they are present in the session tool list; do not rewrite or avoid them just because they are not part of the core Droid file/execute tool family.\n"
            "- Use Droid argument shapes exactly for the native file/execute tools: `Read(file_path, offset?, limit?)`, `LS(directory_path?)`, `Execute(command, timeout?, cwd?)`, `Edit(file_path, old_str, new_str)`, `Grep(pattern, path?, file_pattern?, max_results?)`, `Glob(pattern, max_results?)`, `Create(file_path, content)`.\n"
            "- Do not emit Codex-native tool names such as `read`, `read_file`, `bash`, `shell`, `apply_patch`, `grep_files`, or `list_dir`.\n"
            "- Use `TodoWrite` instead of Codex task-planner tools, `WebSearch` for web search, and `FetchUrl` for direct URL fetches when those tools are available.\n"
            "- Keep tool arguments as JSON objects; for `Execute`, the `command` value must be a single shell command string, not an array.\n"
            "\n"
            f"{_DROID_CRITICAL_INSTRUCTION}"
        )

    def _resolve_supported_tool_names(self, context: CodexRequestContext) -> set[str]:
        supported: set[str] = set()
        for tool in getattr(context.request, "tools", None) or []:
            tool_name = self._extract_request_tool_name(tool)
            if tool_name:
                supported.add(tool_name)
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

    def _is_supported_tool_name(
        self, tool_name: str, supported_tools: set[str]
    ) -> bool:
        if tool_name in supported_tools:
            return True
        equivalents = _DROID_TOOL_EQUIVALENTS.get(tool_name.lower(), set())
        return any(equivalent in supported_tools for equivalent in equivalents)

    def _build_incompatible_tool_steering(
        self,
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> str:
        available_tools = sorted(self._resolve_supported_tool_names(context))
        blocked = ", ".join(dict.fromkeys(incompatible_tool_names))
        available = (
            ", ".join(available_tools)
            if available_tools
            else ", ".join(sorted(_DROID_NATIVE_TOOL_NAMES))
        )
        return (
            f"{_DROID_INCOMPATIBLE_MARKER}:\n"
            f"- Do not call these incompatible tools again: {blocked}.\n"
            "- This Factory Droid session cannot execute Codex-native tool names.\n"
            f"- Use only Droid-compatible tools for this client: {available}.\n"
            "- Keep using any extra tools that are already available in this session, including `Skill`, `Task`, or `fff___*`, when they are the best fit.\n"
            "- Prefer `Execute` for terminal commands, `Read`/`LS` for filesystem inspection, `Edit`/`Create` for file changes, and `Grep`/`Glob` for search tasks.\n"
            "- Keep Droid tool names in PascalCase and keep `Execute.command` as a single command string.\n"
            "\n"
            f"{_DROID_CRITICAL_INSTRUCTION}"
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
