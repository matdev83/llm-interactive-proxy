from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest


def _convert_tools_to_anthropic(tools: list[Any]) -> list[dict[str, Any]]:
    anthropic_tools: list[dict[str, Any]] = []
    for tool in tools:
        if isinstance(tool, dict) and "function" in tool:
            anthropic_tools.append({"type": "function", "function": tool["function"]})
        elif not isinstance(tool, dict):
            tool_dict = tool.model_dump()
            if "function" in tool_dict:
                anthropic_tools.append(
                    {"type": "function", "function": tool_dict["function"]}
                )
    return anthropic_tools


def _convert_tool_choice_to_anthropic(tool_choice: Any) -> Any | None:
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            return tool_choice
        if "function" in tool_choice:
            return {"type": "function", "function": tool_choice["function"]}
        return None
    if tool_choice in {"auto", "none"}:
        return tool_choice
    return None


def _apply_anthropic_extra_body(
    payload: dict[str, Any], extra_body: dict[str, Any]
) -> None:
    metadata = extra_body.get("metadata")
    if metadata:
        payload["metadata"] = metadata

    thinking_config = extra_body.get("thinking")
    if thinking_config is not None:
        if isinstance(thinking_config, dict):
            payload["thinking"] = thinking_config
        elif hasattr(thinking_config, "model_dump"):
            payload["thinking"] = thinking_config.model_dump()
        else:
            payload["thinking"] = {"type": str(thinking_config)}

    service_tier = extra_body.get("service_tier")
    if service_tier is not None:
        payload["service_tier"] = service_tier

    response_format = extra_body.get("response_format")
    if response_format and response_format.get("type") == "json_schema":
        json_schema = response_format.get("json_schema", {})
        schema = json_schema.get("schema", {})
        schema_name = json_schema.get("name")
        schema_description = json_schema.get("description")
        strict = json_schema.get("strict", True)

        import json

        schema_instruction = (
            "\n\nYou must respond with valid JSON that conforms to this schema"
        )
        if schema_name:
            schema_instruction += f" for '{schema_name}'"
        if schema_description:
            schema_instruction += f" ({schema_description})"
        schema_instruction += f":\n\n{json.dumps(schema, indent=2)}"

        if strict:
            schema_instruction += "\n\nIMPORTANT: The response must strictly adhere to this schema. Do not include any additional fields or deviate from the specified structure."
        else:
            schema_instruction += "\n\nNote: The response should generally follow this schema, but minor variations may be acceptable."

        schema_instruction += (
            "\n\nRespond only with the JSON object, no additional text or formatting."
        )

        if payload.get("system"):
            if isinstance(payload["system"], str):
                payload["system"] += schema_instruction
            else:
                payload["system"] = schema_instruction
        else:
            payload["system"] = f"You are a helpful assistant.{schema_instruction}"


def anthropic_to_domain_request(request: Any) -> CanonicalChatRequest:
    """Translate an Anthropic request to a CanonicalChatRequest."""
    from src.core.domain.translation import Translation

    system_prompt = Translation._get_request_param(request, "system")
    raw_messages = Translation._get_request_param(request, "messages", [])
    normalized_messages: list[Any] = []

    if system_prompt:
        normalized_messages.append({"role": "system", "content": system_prompt})

    if raw_messages:
        for message in raw_messages:
            normalized_messages.append(message)

    stop_param = Translation._get_request_param(request, "stop")
    stop_sequences = Translation._get_request_param(request, "stop_sequences")
    normalized_stop = stop_param
    if (normalized_stop is None or normalized_stop == [] or normalized_stop == "") and (
        stop_sequences not in (None, [], "")
    ):
        normalized_stop = stop_sequences

    return CanonicalChatRequest(
        model=Translation._get_request_param(request, "model"),
        messages=normalized_messages,
        temperature=Translation._get_request_param(request, "temperature"),
        top_p=Translation._get_request_param(request, "top_p"),
        top_k=Translation._get_request_param(request, "top_k"),
        n=Translation._get_request_param(request, "n"),
        stream=Translation._get_request_param(request, "stream"),
        stop=normalized_stop,
        max_tokens=Translation._get_request_param(request, "max_tokens"),
        presence_penalty=Translation._get_request_param(request, "presence_penalty"),
        frequency_penalty=Translation._get_request_param(request, "frequency_penalty"),
        logit_bias=Translation._get_request_param(request, "logit_bias"),
        user=Translation._get_request_param(request, "user"),
        reasoning_effort=Translation._get_request_param(request, "reasoning_effort"),
        seed=Translation._get_request_param(request, "seed"),
        tools=Translation._get_request_param(request, "tools"),
        tool_choice=Translation._get_request_param(request, "tool_choice"),
        extra_body=Translation._get_request_param(request, "extra_body"),
    )


def from_domain_to_anthropic_request(request: CanonicalChatRequest) -> dict[str, Any]:
    """Translate a CanonicalChatRequest to an Anthropic request."""
    from src.core.domain.chat import MessageContentPartImage, MessageContentPartText
    from src.core.domain.translation import Translation

    processed_messages: list[dict[str, Any]] = []
    system_message = None

    for message in request.messages:
        if message.role == "system":
            system_message = message.content
            continue

        msg_dict: dict[str, Any] = {"role": message.role}

        if message.content is None:
            continue
        if isinstance(message.content, str):
            msg_dict["content"] = message.content
        elif isinstance(message.content, list):
            content_parts: list[dict[str, Any]] = []
            for part in message.content:
                if isinstance(part, MessageContentPartImage):
                    if part.image_url:
                        url_str = str(part.image_url.url)
                        if url_str.startswith("data:"):
                            try:
                                header, data = url_str.split(",", 1)
                                media_type = header.split(";")[0].replace("data:", "")
                                content_parts.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type or "image/jpeg",
                                            "data": data,
                                        },
                                    }
                                )
                            except ValueError:
                                content_parts.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/jpeg",
                                            "data": url_str.split(",", 1)[-1],
                                        },
                                    }
                                )
                        elif url_str.startswith(("http://", "https://")):
                            content_parts.append(
                                {
                                    "type": "image",
                                    "source": {"type": "url", "url": url_str},
                                }
                            )
                elif isinstance(part, MessageContentPartText):
                    content_parts.append({"type": "text", "text": part.text})
                else:
                    if hasattr(part, "model_dump"):
                        part_dict = part.model_dump()
                        if "text" in part_dict:
                            content_parts.append(
                                {"type": "text", "text": part_dict["text"]}
                            )

            if content_parts:
                msg_dict["content"] = content_parts  # type: ignore[assignment]

        if message.tool_calls:
            # PERFORMANCE: Use explicit loop to avoid multiple model_dump() calls
            tool_calls = []
            for tool_call in message.tool_calls:
                if hasattr(tool_call, "model_dump"):
                    tool_calls.append(tool_call.model_dump())
                elif isinstance(tool_call, dict):
                    tool_calls.append(tool_call)
                else:
                    try:
                        tool_calls.append(dict(tool_call))
                    except (TypeError, ValueError):
                        continue

            if tool_calls:
                msg_dict["tool_calls"] = tool_calls  # type: ignore[assignment]

        if message.tool_call_id:
            msg_dict["tool_call_id"] = message.tool_call_id

        if message.name:
            msg_dict["name"] = message.name

        processed_messages.append(msg_dict)

    max_tokens = request.max_completion_tokens or request.max_tokens or 1024
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": processed_messages,
        "max_tokens": max_tokens,
        "stream": request.stream,
    }

    if system_message:
        payload["system"] = system_message
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.top_p is not None:
        payload["top_p"] = request.top_p
    if request.top_k is not None:
        payload["top_k"] = request.top_k

    if request.tools:
        anthropic_tools = _convert_tools_to_anthropic(request.tools)
        if anthropic_tools:
            payload["tools"] = anthropic_tools

    if request.tool_choice:
        tool_choice = _convert_tool_choice_to_anthropic(request.tool_choice)
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    if request.stop:
        payload["stop_sequences"] = Translation._normalize_stop_sequences(request.stop)

    if request.extra_body and isinstance(request.extra_body, dict):
        _apply_anthropic_extra_body(payload, request.extra_body)

    return payload
