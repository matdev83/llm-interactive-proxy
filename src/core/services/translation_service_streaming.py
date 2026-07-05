from __future__ import annotations

from typing import Any

from src.core.domain.chat import (
    CanonicalStreamChunk,
    StreamingChatCompletionChoice,
    StreamingChatCompletionChoiceDelta,
)
from src.core.domain.translation_utils.content_utils import coerce_reasoning_text


def _normalize_reasoning_summary(delta_dict: dict[str, Any]) -> dict[str, Any]:
    """Surface ``reasoning_summary`` (Codex Responses reasoning stream) as reasoning.

    Codex streams reasoning as ``reasoning_summary`` deltas with ``content`` and
    ``reasoning_content`` null. Map a non-empty ``reasoning_summary`` into the
    existing ``reasoning_content`` / ``reasoning`` contract so downstream
    meaningful-output detection and client forwarding treat it as visible
    reasoning instead of an empty stream. The original ``reasoning_summary`` is
    preserved. Explicit ``reasoning_content`` wins.
    """
    if not isinstance(delta_dict, dict):
        return delta_dict
    summary = delta_dict.get("reasoning_summary")
    if not summary or delta_dict.get("reasoning_content"):
        return delta_dict
    normalized = coerce_reasoning_text(summary)
    if not normalized:
        return delta_dict
    delta_dict = dict(delta_dict)
    delta_dict["reasoning_content"] = normalized
    delta_dict.setdefault("reasoning", normalized)
    return delta_dict


def dict_to_canonical_stream_chunk(chunk_dict: dict[str, Any]) -> CanonicalStreamChunk:
    choices: list[StreamingChatCompletionChoice] = []
    for choice_dict in chunk_dict.get("choices", []):
        delta_dict = choice_dict.get("delta", {})
        if not isinstance(delta_dict, dict):
            delta_dict = {}
        delta_dict = _normalize_reasoning_summary(delta_dict)
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
