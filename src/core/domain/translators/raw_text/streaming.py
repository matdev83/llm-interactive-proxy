from __future__ import annotations

import time
import uuid
from typing import Any

from src.core.domain.chat import CanonicalStreamChunk
from src.core.domain.translators.openai.streaming import openai_to_domain_stream_chunk


def raw_text_to_domain_stream_chunk(
    chunk: Any,
) -> dict[str, Any] | CanonicalStreamChunk:
    """Translate a raw text stream chunk to canonical format."""
    if chunk is None:
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "text-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }

    if isinstance(chunk, str):
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "text-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": chunk},
                    "finish_reason": None,
                }
            ],
        }

    if isinstance(chunk, dict):
        if "text" in chunk and isinstance(chunk["text"], str):
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "text-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": chunk["text"]},
                        "finish_reason": None,
                    }
                ],
            }
        return openai_to_domain_stream_chunk(chunk)

    return {"error": "Invalid raw text chunk format"}
