from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def openai_to_domain_request(request: Any) -> CanonicalChatRequest:
    """Translate an OpenAI request to a CanonicalChatRequest."""
    if isinstance(request, dict):
        model = request.get("model")
        messages = request.get("messages", [])
        top_k = request.get("top_k")
        top_p = request.get("top_p")
        temperature = request.get("temperature")
        max_tokens = request.get("max_tokens")
        stop = request.get("stop")
        stream = request.get("stream", False)
        tools = request.get("tools")
        tool_choice = request.get("tool_choice")
        seed = request.get("seed")
        reasoning_effort = request.get("reasoning_effort")
        reasoning_payload = request.get("reasoning")
    else:
        model = getattr(request, "model", None)
        messages = getattr(request, "messages", [])
        top_k = getattr(request, "top_k", None)
        top_p = getattr(request, "top_p", None)
        temperature = getattr(request, "temperature", None)
        max_tokens = getattr(request, "max_tokens", None)
        stop = getattr(request, "stop", None)
        stream = getattr(request, "stream", False)
        tools = getattr(request, "tools", None)
        tool_choice = getattr(request, "tool_choice", None)
        seed = getattr(request, "seed", None)
        reasoning_effort = getattr(request, "reasoning_effort", None)
        reasoning_payload = getattr(request, "reasoning", None)

    if reasoning_effort in ("", None) and isinstance(reasoning_payload, dict):
        raw_effort = reasoning_payload.get("effort")
        if isinstance(raw_effort, str) and raw_effort.strip():
            reasoning_effort = raw_effort

    normalized_reasoning: dict[str, Any] | None = None
    if reasoning_payload:
        if isinstance(reasoning_payload, dict):
            normalized_reasoning = dict(reasoning_payload)
        elif hasattr(reasoning_payload, "model_dump"):
            normalized_reasoning = reasoning_payload.model_dump()  # type: ignore[attr-defined]

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
        stream=stream,
        tools=tools,
        tool_choice=tool_choice,
        seed=seed,
        reasoning_effort=reasoning_effort,
        reasoning=normalized_reasoning,
    )


def from_domain_to_openai_request(request: CanonicalChatRequest) -> dict[str, Any]:
    """Translate a CanonicalChatRequest to an OpenAI request."""
    messages_payload: list[dict[str, Any]] = []
    for message in request.messages:
        if hasattr(message, "to_dict"):
            message_dict = message.to_dict()
            if "content" not in message_dict:
                message_dict["content"] = None
        else:
            message_dict = {
                "role": getattr(message, "role", "assistant"),
                "content": getattr(message, "content", None),
            }
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls is not None:
                message_dict["tool_calls"] = tool_calls
            tool_call_id = getattr(message, "tool_call_id", None)
            if tool_call_id is not None:
                message_dict["tool_call_id"] = tool_call_id

        messages_payload.append(message_dict)

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages_payload,
    }

    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.top_k is not None:
        payload["top_k"] = request.top_k
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.stream is not None:
        payload["stream"] = request.stream
    if request.stop is not None:
        payload["stop"] = _normalize_stop_sequences(request.stop)
    if request.seed is not None:
        payload["seed"] = request.seed
    if request.presence_penalty is not None:
        payload["presence_penalty"] = request.presence_penalty
    if request.frequency_penalty is not None:
        payload["frequency_penalty"] = request.frequency_penalty
    if request.user is not None:
        payload["user"] = request.user
    if request.tools is not None:
        payload["tools"] = request.tools
    if request.tool_choice is not None:
        payload["tool_choice"] = request.tool_choice

    if request.max_completion_tokens is not None:
        payload["max_completion_tokens"] = request.max_completion_tokens
    if request.logprobs is not None:
        payload["logprobs"] = request.logprobs
    if request.top_logprobs is not None:
        payload["top_logprobs"] = request.top_logprobs
    if request.parallel_tool_calls is not None:
        payload["parallel_tool_calls"] = request.parallel_tool_calls
    if request.service_tier is not None:
        payload["service_tier"] = request.service_tier
    if request.response_format is not None:
        payload["response_format"] = request.response_format

    if request.store is not None:
        payload["store"] = request.store
    if request.request_metadata is not None:
        payload["metadata"] = request.request_metadata
    if request.prediction is not None:
        payload["prediction"] = request.prediction
    if request.modalities is not None:
        payload["modalities"] = request.modalities
    if request.audio is not None:
        payload["audio"] = request.audio

    reasoning_payload: dict[str, Any] | None = None
    if request.reasoning is not None:
        # request.reasoning is typed as dict[str, Any] | None, so after None check it's dict[str, Any]
        reasoning_payload = dict(request.reasoning)
        # Note: The hasattr check for model_dump is kept for runtime safety,
        # but pyright correctly identifies that isinstance check is unnecessary

    effort_value = request.reasoning_effort
    normalized_effort: str | None
    if isinstance(effort_value, str):
        normalized_effort = effort_value.strip()
    else:
        normalized_effort = str(effort_value) if effort_value is not None else None

    if normalized_effort:
        if reasoning_payload is None:
            reasoning_payload = {}
        if "effort" not in reasoning_payload:
            reasoning_payload["effort"] = effort_value

    if reasoning_payload:
        payload["reasoning"] = reasoning_payload

    if request.extra_body and "response_format" in request.extra_body:
        response_format = request.extra_body["response_format"]
        if (
            response_format
            and isinstance(response_format, dict)
            and response_format.get("type") == "json_schema"
        ):
            payload["response_format"] = response_format

    return payload


def _normalize_stop_sequences(stop: Any) -> list[str] | None:
    if stop is None:
        return None
    if isinstance(stop, str):
        return [stop]
    if isinstance(stop, list):
        return [str(s) for s in stop]
    return [str(stop)]
