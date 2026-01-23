from __future__ import annotations

import logging
from typing import Any

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translation_utils.tool_utils import _process_gemini_function_call
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

    content = ""
    finish_reason = None
    tool_calls: list[dict[str, Any]] | None = None
    thought_signature: str | None = None

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

            text_parts: list[str] = []
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part.get("text", ""))
                elif isinstance(part, dict) and "functionCall" in part:
                    try:
                        if tool_calls is None:
                            tool_calls = []
                        tool_calls.append(
                            _process_gemini_function_call(
                                part["functionCall"],
                                part=part,
                                thought_signature=thought_signature,
                            ).model_dump()
                        )
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
            content = "".join(text_parts)

        if "finishReason" in candidate:
            finish_reason = candidate["finishReason"]

    delta: dict[str, Any] = {"role": "assistant"}
    if thought_signature:
        delta["thought_signature"] = thought_signature

    if tool_calls:
        delta["tool_calls"] = tool_calls
        delta.pop("content", None)
        finish_reason = "tool_calls"
    elif content:
        delta["content"] = content

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
