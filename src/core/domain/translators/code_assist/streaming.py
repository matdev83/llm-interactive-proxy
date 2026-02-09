from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translation_utils.content_utils import (
    _coerce_reasoning_text,  # pyright: ignore[reportPrivateUsage]
    _safe_string,  # pyright: ignore[reportPrivateUsage]
)
from src.core.domain.translation_utils.tool_utils import (
    _process_gemini_function_call,  # pyright: ignore[reportPrivateUsage]
)
from src.core.domain.translators.code_assist.textual_tool_call_parser import (
    parse_textual_tool_calls,
)
from src.core.domain.translators.openai.streaming import openai_to_domain_stream_chunk

logger = logging.getLogger(__name__)


def code_assist_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
    """
    Translate a Code Assist API streaming chunk to a canonical dictionary format.

    Code Assist API uses Server-Sent Events (SSE) format with "data: " prefix.
    The Antigravity sandbox returns chunks in OpenAI format directly, so we
    detect and pass through OpenAI-format chunks while still handling native
    Code Assist format for compatibility.
    """
    import time
    import uuid

    if chunk is None:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "code-assist-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        }

    if not isinstance(chunk, dict):
        return {"error": "Invalid chunk format: expected a dictionary"}

    if "choices" in chunk and "id" in chunk:
        result = openai_to_domain_stream_chunk(chunk)
        if isinstance(result, CanonicalStreamChunk):
            return result.model_dump(exclude_none=True)
        return result

    response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
    created = int(time.time())
    model = "code-assist-model"

    finish_reason = None
    tool_calls: list[dict[str, Any]] | None = None
    thought_signature: str | None = None
    reasoning_pieces: list[str] = []
    text_parts: list[str] = []

    response_wrapper = chunk.get("response", {})
    candidates = response_wrapper.get("candidates", [])

    if candidates and len(candidates) > 0:
        candidate = candidates[0]
        content_obj = candidate.get("content") or {}
        parts = content_obj.get("parts", [])

        if parts and len(parts) > 0:
            # Pre-scan for thought signature in any part of this chunk
            for part in parts:
                if isinstance(part, dict):
                    sig = part.get("thoughtSignature") or part.get("thought_signature")
                    if sig:
                        thought_signature = sig
                        break

            for part in parts:
                if not isinstance(part, dict):
                    continue

                # Prioritize explicit reasoning type
                if part.get("type") in {"reasoning", "thinking"}:
                    normalized_reasoning = _coerce_reasoning_text(
                        part.get("text") or part.get("value")
                    )
                    if normalized_reasoning:
                        reasoning_pieces.append(normalized_reasoning)
                    continue

                if "text" in part:
                    safe_text = _safe_string(
                        part.get("text")
                    )  # pyright: ignore[reportPrivateUsage]
                    if safe_text:
                        text_parts.append(safe_text)

                    # Check if metadata indicates this is also reasoning
                    metadata = part.get("metadata", {})
                    if isinstance(metadata, dict):
                        meta_type = str(metadata.get("type", "")).lower()
                        if meta_type in {"thinking", "thought"}:
                            # Try to get reasoning from specific metadata fields first
                            metadata_reasoning = _coerce_reasoning_text(
                                metadata.get("thought")
                                or metadata.get("thinking")
                                or metadata.get("reasoning")
                            )

                            # If not found in metadata fields, use the text content
                            if metadata_reasoning:
                                reasoning_pieces.append(metadata_reasoning)
                            elif safe_text:
                                reasoning_pieces.append(safe_text)
                elif "functionCall" in part:
                    try:
                        if tool_calls is None:
                            tool_calls = []
                        tool_call_dict = _process_gemini_function_call(
                            part["functionCall"],
                            part=part,
                            thought_signature=thought_signature,
                        ).model_dump()
                        tool_call_dict["index"] = len(tool_calls)
                        tool_calls.append(tool_call_dict)
                    except (KeyError, TypeError, AttributeError, ValueError) as e:
                        # Expected data transformation errors - log and skip this tool call
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Failed to process function call in Code Assist stream chunk, skipping: %s",
                                e,
                                exc_info=True,
                            )
                        continue
                    except Exception as e:
                        # Unexpected errors - log with full context but still skip to avoid breaking the stream
                        if logger.isEnabledFor(logging.ERROR):
                            logger.error(
                                "Unexpected error processing function call in Code Assist stream chunk, skipping: %s",
                                e,
                                exc_info=True,
                            )
                        continue

        if "finishReason" in candidate:
            finish_reason = candidate["finishReason"]

    delta: dict[str, Any] = {"role": "assistant"}
    if thought_signature:
        delta["thought_signature"] = thought_signature

    if text_parts:
        text_content = "".join(text_parts)
        cleaned_text, textual_tool_calls = parse_textual_tool_calls(text_content)
        if textual_tool_calls and tool_calls is None:
            for idx, tool_call in enumerate(textual_tool_calls):
                tool_call["index"] = idx
            tool_calls = textual_tool_calls

        if cleaned_text:
            delta["content"] = cleaned_text

    if reasoning_pieces:
        reasoning = "\n".join(
            segment for segment in reasoning_pieces if segment
        ).strip()
        delta["reasoning_content"] = reasoning
        # Add aliases for compatibility with various clients
        delta["reasoning"] = reasoning
        delta["thinking"] = reasoning
        delta["thought"] = reasoning

    # Map Gemini finish reason to OpenAI format
    from src.core.domain.translators.gemini.finish_reason import (
        map_gemini_finish_reason,
    )

    canonical_finish_reason = map_gemini_finish_reason(finish_reason)

    if tool_calls:
        delta["tool_calls"] = tool_calls
        # Fix: only set finish_reason if Gemini actually provided one.
        # Premature finish_reason causes clients like Roo-Code to stop reading the stream
        # before subsequent tool calls are received, breaking parallel tool calling.
        if canonical_finish_reason:
            finish_reason = "tool_calls"
        else:
            finish_reason = None
    else:
        finish_reason = canonical_finish_reason

    return {
        "id": response_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }
