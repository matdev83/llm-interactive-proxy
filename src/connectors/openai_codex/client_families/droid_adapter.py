"""Factory Droid family compatibility adapter."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.connectors.openai_codex.client_families.base import (
    FamilyApplyResult,
    IClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    CompatibilityState,
    ProcessedMessage,
    ProviderStreamChunk,
)

logger = logging.getLogger(__name__)


class DroidClientFamilyAdapter(IClientFamilyAdapter):
    """Droid-specific detection and stream translation behavior."""

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
        detector = self._droid_detector
        if detector is None:
            try:
                from src.connectors._openai_codex_droid_session_detector import (
                    DroidSessionDetector,
                )

                detector = DroidSessionDetector()
                self._droid_detector = detector
            except ImportError:
                logger.debug("Droid session detector not available")
                return

        try:
            request_tools = getattr(context.request, "tools", []) or []
            tools_for_detection: list[dict[str, Any]] = []
            for tool in request_tools:
                if hasattr(tool, "model_dump"):
                    tools_for_detection.append(tool.model_dump())
                elif isinstance(tool, dict):
                    tools_for_detection.append(tool)

            messages_for_detection: list[dict[str, Any]] = []
            for msg in context.processed_messages:
                if isinstance(msg, ProcessedMessage):
                    messages_for_detection.append(msg.model_dump())
                elif isinstance(msg, dict):
                    messages_for_detection.append(msg)

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
                if self._droid_translator is None:
                    try:
                        from src.connectors._openai_codex_droid_tool_translator import (
                            DroidToolTranslator,
                        )

                        self._droid_translator = DroidToolTranslator()
                    except ImportError:
                        logger.debug("Droid tool translator not available")
        except Exception as e:
            logger.debug("Droid detection failed: %s", str(e), exc_info=True)

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
                if not isinstance(tc, dict) or "function" not in tc:
                    return
                func = tc.get("function")
                if not isinstance(func, dict):
                    return

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
                        logger.debug(
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
                            logger.debug(
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
            logger.debug(
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
        return payload_dict

    def detect_incompatible_tool_calls(
        self,
        tool_calls: list[dict[str, object]],
        context: CodexRequestContext,
    ) -> list[str]:
        return []

    def append_incompatible_tool_steering(
        self,
        payload_dict: dict[str, object],
        incompatible_tool_names: list[str],
        context: CodexRequestContext,
    ) -> dict[str, object]:
        return payload_dict
