from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def openrouter_to_domain_request(request: Any) -> CanonicalChatRequest:
    """Translate an OpenRouter request to a CanonicalChatRequest."""
    if isinstance(request, dict):
        model = request.get("model")
        messages = request.get("messages", [])
        top_k = request.get("top_k")
        top_p = request.get("top_p")
        temperature = request.get("temperature")
        max_tokens = request.get("max_tokens")
        stop = request.get("stop")
        seed = request.get("seed")
        reasoning_effort = request.get("reasoning_effort")
        extra_params = request.get("extra_params")
    else:
        model = getattr(request, "model", None)
        messages = getattr(request, "messages", [])
        top_k = getattr(request, "top_k", None)
        top_p = getattr(request, "top_p", None)
        temperature = getattr(request, "temperature", None)
        max_tokens = getattr(request, "max_tokens", None)
        stop = getattr(request, "stop", None)
        seed = getattr(request, "seed", None)
        reasoning_effort = getattr(request, "reasoning_effort", None)
        extra_params = getattr(request, "extra_params", None)

    if not model:
        raise ValueError("Model not found in request")

    chat_messages: list[Any] = []
    for msg in messages:
        if isinstance(msg, dict):
            chat_messages.append(ChatMessage(**msg))
        else:
            chat_messages.append(msg)

    return CanonicalChatRequest(
        model=model,
        messages=chat_messages,
        top_k=top_k,
        top_p=top_p,
        temperature=temperature,
        max_tokens=max_tokens,
        stop=stop,
        seed=seed,
        reasoning_effort=reasoning_effort,
        stream=(
            request.get("stream")
            if isinstance(request, dict)
            else getattr(request, "stream", None)
        ),
        extra_body=(
            request.get("extra_body")
            if isinstance(request, dict)
            else getattr(request, "extra_body", None)
        )
        or (extra_params if extra_params is not None else None),
        tools=(
            request.get("tools")
            if isinstance(request, dict)
            else getattr(request, "tools", None)
        ),
        tool_choice=(
            request.get("tool_choice")
            if isinstance(request, dict)
            else getattr(request, "tool_choice", None)
        ),
    )
