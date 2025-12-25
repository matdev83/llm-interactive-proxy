from __future__ import annotations

import json
import logging
from typing import Any

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)
from src.core.domain.translation_utils.content_utils import (
    _coerce_reasoning_text,
    _safe_string,
)
from src.core.domain.translation_utils.tool_utils import _process_gemini_function_call
from src.core.domain.translators.gemini.finish_reason import map_gemini_finish_reason

logger = logging.getLogger(__name__)


def gemini_to_domain_stream_chunk(chunk: Any) -> CanonicalStreamChunk | dict[str, Any]:
    """Translate a Gemini streaming chunk to a canonical CanonicalStreamChunk object."""
    import time
    import uuid

    if not isinstance(chunk, dict):
        logger.debug(
            "gemini_to_domain_stream_chunk: Invalid chunk format (not dict), type=%s",
            type(chunk).__name__,
        )
        return {"error": "Invalid chunk format: expected a dictionary"}

    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    model = "gemini-pro"

    content_pieces: list[str] = []
    reasoning_pieces: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    finish_reason = None

    logger.debug(
        "gemini_to_domain_stream_chunk: Processing chunk with keys=%s",
        list(chunk.keys()) if isinstance(chunk, dict) else "N/A",
    )

    if "candidates" in chunk:
        for candidate in chunk["candidates"]:
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") in {"reasoning", "thinking"}:
                        normalized_reasoning = _coerce_reasoning_text(
                            part.get("text") or part.get("value")
                        )
                        if normalized_reasoning:
                            reasoning_pieces.append(normalized_reasoning)
                    elif "text" in part and not part.get("functionCall"):
                        safe_text = _safe_string(part.get("text"))
                        if safe_text:
                            content_pieces.append(safe_text)
                        metadata = part.get("metadata", {})
                        if isinstance(metadata, dict):
                            metadata_reasoning = _coerce_reasoning_text(
                                metadata.get("thought")
                                or metadata.get("thinking")
                                or metadata.get("reasoning")
                            )
                            if metadata_reasoning:
                                reasoning_pieces.append(metadata_reasoning)
                            meta_type = str(metadata.get("type", "")).lower()
                            if meta_type in {"thinking", "thought"} and safe_text:
                                reasoning_pieces.append(safe_text)
                    elif "functionCall" in part:
                        try:
                            tool_call_dict = _process_gemini_function_call(
                                part["functionCall"], part=part
                            ).model_dump()
                            # Add index field required for streaming tool calls
                            tool_call_dict["index"] = len(tool_calls)
                            tool_calls.append(tool_call_dict)
                        except Exception:
                            continue
            if "finishReason" in candidate:
                finish_reason = map_gemini_finish_reason(candidate["finishReason"])

    delta_dict: dict[str, Any] = {"role": "assistant"}
    if content_pieces:
        delta_dict["content"] = "".join(content_pieces)
    if reasoning_pieces:
        delta_dict["reasoning_content"] = "\n".join(
            segment for segment in reasoning_pieces if segment
        ).strip()
    if tool_calls:
        delta_dict["tool_calls"] = tool_calls

    logger.debug(
        "gemini_to_domain_stream_chunk: Transformed chunk - "
        "content_len=%d, reasoning_len=%d, tool_calls=%d, finish_reason=%s",
        len(delta_dict.get("content", "")),
        len(delta_dict.get("reasoning_content", "")),
        len(tool_calls),
        finish_reason,
    )

    delta = StreamingChatCompletionChoiceDelta(**delta_dict)
    choice = StreamingChatCompletionChoice(
        index=0,
        delta=delta,
        finish_reason=finish_reason,
    )

    return CanonicalStreamChunk(
        id=response_id,
        object="chat.completion.chunk",
        created=created,
        model=model,
        choices=[choice],
    )


def from_domain_to_gemini_stream_chunk(chunk: Any) -> dict[str, Any]:
    """Translates a domain stream chunk to a Gemini stream format."""
    content = _extract_content_from_domain_chunk(chunk)
    parts: list[dict[str, Any]] = []
    if content:
        parts.append({"text": content})

    finish_reason = None
    choices = getattr(chunk, "choices", None)
    if choices and isinstance(choices, list) and len(choices) > 0:
        choice = choices[0]

        delta = getattr(choice, "delta", None)
        if delta:
            tool_calls = (
                delta.get("tool_calls")
                if isinstance(delta, dict)
                else getattr(delta, "tool_calls", None)
            )
            if tool_calls:
                for tool_call in tool_calls:
                    function_data = (
                        tool_call.get("function")
                        if isinstance(tool_call, dict)
                        else getattr(tool_call, "function", None)
                    )
                    if function_data:
                        name = (
                            function_data.get("name")
                            if isinstance(function_data, dict)
                            else getattr(function_data, "name", None)
                        )
                        args = (
                            function_data.get("arguments")
                            if isinstance(function_data, dict)
                            else getattr(function_data, "arguments", None)
                        )
                        if name and args:
                            try:
                                args_dict = json.loads(args)
                                parts.append(
                                    {"functionCall": {"name": name, "args": args_dict}}
                                )
                            except json.JSONDecodeError:
                                pass

        fr = (
            choice.get("finish_reason")
            if isinstance(choice, dict)
            else getattr(choice, "finish_reason", None)
        )
        if fr:
            finish_reason = "STOP" if fr == "stop" else str(fr).upper()

    return {
        "candidates": [
            {
                "content": {"parts": parts, "role": "model"},
                "finishReason": finish_reason,
            }
        ]
    }


def _extract_content_from_domain_chunk(chunk: Any) -> str:
    choices = getattr(chunk, "choices", None)
    if choices and isinstance(choices, list) and len(choices) > 0:
        choice = choices[0]
        if isinstance(choice, dict):
            delta = choice.get("delta", {})
            if isinstance(delta, dict) and "content" in delta:
                return delta.get("content", "") or ""
        elif hasattr(choice, "delta"):
            delta = getattr(choice, "delta", None)
            if delta:
                if isinstance(delta, dict):
                    return delta.get("content", "") or ""
                if hasattr(delta, "content"):
                    return getattr(delta, "content", "") or ""
    return getattr(chunk, "content", "") or ""
