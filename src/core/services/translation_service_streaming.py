from __future__ import annotations

from typing import Any

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)


def dict_to_canonical_stream_chunk(chunk_dict: dict[str, Any]) -> CanonicalStreamChunk:
    choices: list[StreamingChatCompletionChoice] = []
    for choice_dict in chunk_dict.get("choices", []):
        delta_dict = choice_dict.get("delta", {})
        delta_data = {
            "role": delta_dict.get("role"),
            "content": delta_dict.get("content"),
            "tool_calls": delta_dict.get("tool_calls"),
            "refusal": delta_dict.get("refusal"),
        }
        for key, value in delta_dict.items():
            if key not in delta_data:
                delta_data[key] = value

        delta = StreamingChatCompletionChoiceDelta(**delta_data)
        choice = StreamingChatCompletionChoice(
            index=choice_dict.get("index", 0),
            delta=delta,
            finish_reason=choice_dict.get("finish_reason"),
            logprobs=choice_dict.get("logprobs"),
        )
        choices.append(choice)

    return CanonicalStreamChunk(
        id=chunk_dict.get("id"),
        object=chunk_dict.get("object", "chat.completion.chunk"),
        created=chunk_dict.get("created"),
        model=chunk_dict.get("model"),
        choices=choices,
        usage=chunk_dict.get("usage"),
        system_fingerprint=chunk_dict.get("system_fingerprint"),
    )
