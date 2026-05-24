from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.responses_api import ResponsesRequest
from src.core.domain.translation_utils import (
    safe_string,
)


class NormalizedResponsesContentPart(BaseModel):
    """Normalized representation of a Responses API content part.

    Content parts represent structured content within a message, such as
    text blocks or images. The normalized format ensures compatibility
    with chat completion message structures.
    """

    model_config = {"extra": "allow"}

    type: str
    text: str | None = None
    image_url: dict[str, Any] | None = None


NormalizedResponsesMessage = dict[str, Any]
NormalizedResponsesMessageList = list[NormalizedResponsesMessage]
NormalizedResponsesContentPartList = list[dict[str, Any]]


def responses_to_domain_request(request: Any) -> CanonicalChatRequest:
    """
    Translate a Responses API request to a CanonicalChatRequest.

    The Responses API request includes structured output requirements via response_format.
    This method converts the request to the internal domain format while preserving
    the JSON schema information for later use by backends.
    """

    def _prepare_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = dict(payload)
        # Convert input to messages if messages is missing or empty
        messages = normalized_payload.get("messages")
        if (
            not messages or (isinstance(messages, list) and len(messages) == 0)
        ) and "input" in normalized_payload:
            normalized_payload["messages"] = normalize_responses_input_to_messages(
                normalized_payload["input"]
            )
        return normalized_payload

    if isinstance(request, dict):
        request_payload = _prepare_payload(request)
        # Let Pydantic validation handle missing required fields
        responses_request = ResponsesRequest.model_validate(request_payload)
    elif hasattr(request, "model_dump"):
        request_payload = _prepare_payload(request.model_dump())
        responses_request = (
            request
            if isinstance(request, ResponsesRequest)
            else ResponsesRequest(**request_payload)
        )
    else:
        request_payload = {
            "model": getattr(request, "model", None),
            "messages": getattr(request, "messages", None),
            "response_format": getattr(request, "response_format", None),
            "max_tokens": getattr(request, "max_tokens", None),
            "temperature": getattr(request, "temperature", None),
            "top_p": getattr(request, "top_p", None),
            "n": getattr(request, "n", None),
            "stream": getattr(request, "stream", None),
            "stop": getattr(request, "stop", None),
            "presence_penalty": getattr(request, "presence_penalty", None),
            "frequency_penalty": getattr(request, "frequency_penalty", None),
            "logit_bias": getattr(request, "logit_bias", None),
            "user": getattr(request, "user", None),
            "seed": getattr(request, "seed", None),
            "session_id": getattr(request, "session_id", None),
            "agent": getattr(request, "agent", None),
            "extra_body": getattr(request, "extra_body", None),
        }

        input_value = getattr(request, "input", None)
        if (not request_payload.get("messages")) and input_value is not None:
            request_payload["messages"] = normalize_responses_input_to_messages(
                input_value
            )

        other_params = {
            k: v for k, v in request_payload.items() if k not in ["model", "messages"]
        }
        responses_request = ResponsesRequest(
            model=request_payload.get("model") or "",
            messages=request_payload.get("messages") or [],
            **other_params,
        )

    extra_body = dict(responses_request.extra_body or {})
    if responses_request.response_format is not None:
        extra_body["response_format"] = responses_request.response_format.model_dump()

    # Preserve the raw Responses `input` array (including function_call history) for
    # backends that can forward it directly (e.g., ChatGPT Codex backend).
    if responses_request.input is not None:
        extra_body["input"] = responses_request.input
        # Enable Codex passthrough automatically when the caller used Responses `input`.
        # This allows Codex clients (and OpenCode-style clients) to preserve tool history
        # that cannot be faithfully reconstructed from chat messages alone.
        codex_caps = extra_body.get("codex_capabilities")
        if not isinstance(codex_caps, dict):
            codex_caps = {}
            extra_body["codex_capabilities"] = codex_caps
        codex_caps.setdefault("codex_passthrough", True)

    if responses_request.instructions is not None:
        extra_body["instructions"] = responses_request.instructions

    if responses_request.include is not None:
        extra_body["include"] = responses_request.include
    if responses_request.store is not None:
        extra_body["store"] = responses_request.store
    if responses_request.background is not None:
        extra_body["background"] = responses_request.background
    if responses_request.truncation is not None:
        extra_body["truncation"] = responses_request.truncation
    if responses_request.conversation is not None:
        extra_body["conversation"] = responses_request.conversation
    if responses_request.previous_response_id is not None:
        extra_body["previous_response_id"] = responses_request.previous_response_id
    if responses_request.prompt is not None:
        prompt_val = responses_request.prompt
        if hasattr(prompt_val, "model_dump") and not isinstance(prompt_val, dict):
            extra_body["prompt"] = prompt_val.model_dump()  # type: ignore[attr-defined]
        else:
            extra_body["prompt"] = prompt_val
    if responses_request.prompt_cache_key is not None:
        extra_body["prompt_cache_key"] = responses_request.prompt_cache_key
    if responses_request.prompt_cache_retention is not None:
        extra_body["prompt_cache_retention"] = responses_request.prompt_cache_retention
    if responses_request.safety_identifier is not None:
        extra_body["safety_identifier"] = responses_request.safety_identifier
    if responses_request.stream_options is not None:
        stream_opts = responses_request.stream_options
        if hasattr(stream_opts, "model_dump") and not isinstance(stream_opts, dict):
            extra_body["stream_options"] = stream_opts.model_dump()  # type: ignore[attr-defined]
        else:
            extra_body["stream_options"] = stream_opts
    if responses_request.text is not None:
        text_cfg = responses_request.text
        if hasattr(text_cfg, "model_dump") and not isinstance(text_cfg, dict):
            extra_body["text"] = text_cfg.model_dump()  # type: ignore[attr-defined]
        else:
            extra_body["text"] = text_cfg

    messages = responses_request.messages or []
    # Ensure we have at least one message - convert input if messages is empty
    if not messages and responses_request.input:
        from src.core.domain.chat import ChatMessage

        normalized_messages = normalize_responses_input_to_messages(
            responses_request.input
        )
        # Convert dict messages to ChatMessage objects
        # Handle content field conversion - ChatMessage expects content as str or MessageContentPart sequence
        converted_messages = []
        for msg_dict in normalized_messages:
            if isinstance(msg_dict, ChatMessage):
                converted_messages.append(msg_dict)
            else:
                # Extract content and convert to proper format
                content = msg_dict.get("content")
                if isinstance(content, list) and content:
                    # If content is a list of parts, extract text or use as-is
                    # ChatMessage can handle list of dicts as content
                    pass  # Keep content as-is, ChatMessage validator will handle it
                elif isinstance(content, str):
                    pass  # Already correct format
                # Create ChatMessage - it will handle validation and conversion
                converted_messages.append(ChatMessage(**msg_dict))
        messages = converted_messages

    # Validate that we have at least one message before creating CanonicalChatRequest
    # Note: Empty messages validation will be caught by CanonicalChatRequest's validator
    # which raises ValueError, so we let that handle it for consistency
    if not messages and not responses_request.input:
        # Only raise if both messages and input are empty/None
        # This allows Pydantic validation errors to surface first
        pass  # Let CanonicalChatRequest validator handle empty messages

    system_prompt = None
    if responses_request.instructions:
        system_prompt = responses_request.instructions

    effective_max_tokens = (
        responses_request.max_output_tokens or responses_request.max_tokens
    )

    reasoning_config = None
    reasoning_effort = None
    if responses_request.reasoning:
        reasoning_val = responses_request.reasoning
        if isinstance(reasoning_val, dict):
            reasoning_config = reasoning_val
            reasoning_effort = reasoning_val.get("effort")
        elif hasattr(reasoning_val, "model_dump"):
            reasoning_config = reasoning_val.model_dump()
            reasoning_effort = getattr(reasoning_val, "effort", None)
        else:
            reasoning_effort = getattr(reasoning_val, "effort", None)

    request_metadata = None
    if responses_request.metadata:
        request_metadata = responses_request.metadata

    return CanonicalChatRequest(
        model=responses_request.model,
        messages=messages,
        system_prompt=system_prompt,
        temperature=responses_request.temperature,
        top_p=responses_request.top_p,
        top_logprobs=responses_request.top_logprobs,
        max_tokens=effective_max_tokens,
        max_completion_tokens=responses_request.max_output_tokens,
        n=responses_request.n,
        stream=responses_request.stream,
        stop=responses_request.stop,
        presence_penalty=responses_request.presence_penalty,
        frequency_penalty=responses_request.frequency_penalty,
        logit_bias=responses_request.logit_bias,
        user=responses_request.user,
        seed=responses_request.seed,
        session_id=responses_request.session_id,
        agent=responses_request.agent,
        extra_body=extra_body,
        tools=responses_request.tools,
        tool_choice=responses_request.tool_choice,
        parallel_tool_calls=responses_request.parallel_tool_calls,
        reasoning=reasoning_config,
        reasoning_effort=reasoning_effort,
        service_tier=responses_request.service_tier,
        request_metadata=request_metadata,
    )


def from_domain_to_responses_request(request: CanonicalChatRequest) -> dict[str, Any]:
    """Translate a CanonicalChatRequest to an OpenAI Responses API request format."""
    from src.core.domain.translators.openai.request import from_domain_to_openai_request

    payload = from_domain_to_openai_request(request)

    if request.extra_body:
        extra_body_copy = dict(request.extra_body)

        # If the incoming request was a Responses request with `input`, prefer replaying it
        # verbatim so tool-call history survives translation.
        raw_input = extra_body_copy.pop("input", None)
        if raw_input is not None:
            payload["input"] = raw_input
            payload.pop("messages", None)

        raw_instructions = extra_body_copy.pop("instructions", None)
        if raw_instructions is not None:
            payload["instructions"] = raw_instructions

        response_format = extra_body_copy.pop("response_format", None)
        if response_format is not None:
            if isinstance(response_format, dict):
                payload["response_format"] = response_format
            elif hasattr(response_format, "model_dump"):
                payload["response_format"] = response_format.model_dump()
            else:
                payload["response_format"] = response_format

        safe_extra_body = filter_responses_extra_body(extra_body_copy)
        if safe_extra_body:
            payload.update(safe_extra_body)

    return payload


def filter_responses_extra_body(extra_body: dict[str, Any]) -> dict[str, Any]:
    if not extra_body:
        return {}

    allowed_keys: set[str] = {
        "input",
        "instructions",
        "metadata",
        "safety_identifier",
        "prompt_cache_key",
        "prompt_cache_retention",
        "conversation",
        "previous_response_id",
        "store",
        "background",
        "truncation",
        "include",
        "reasoning",
        "text",
        "service_tier",
        "stream_options",
    }

    return {key: value for key, value in extra_body.items() if key in allowed_keys}


def normalize_responses_input_to_messages(
    input_payload: Any,
) -> NormalizedResponsesMessageList:
    """Coerce OpenAI Responses API input payloads into chat messages.

    Returns a list of normalized message dictionaries. Each message follows
    the shape defined by Responses API messages with role, content and
    optional fields like name, tool_calls, tool_call_id.

    The message structure is documented in NormalizedResponsesMessage.
    """

    def _normalize_message_entry(entry: Any) -> dict[str, Any] | None:
        if entry is None:
            return None

        if isinstance(entry, str):
            return {"role": "user", "content": entry}

        if isinstance(entry, dict):
            raw_role = entry.get("role")
            if raw_role is None:
                raw_role = "user"
            role = str(raw_role)
            message: dict[str, Any] = {"role": role}

            content = normalize_responses_content(entry.get("content"))
            if content is not None:
                if isinstance(content, list):
                    message["content_parts"] = content
                    message["content"] = content
                else:
                    parts = [{"type": "text", "text": content}]
                    message["content_parts"] = parts
                    message["content"] = parts

            if "name" in entry and entry.get("name") is not None:
                message["name"] = entry["name"]

            if "tool_calls" in entry and entry.get("tool_calls") is not None:
                message["tool_calls"] = entry["tool_calls"]

            if "tool_call_id" in entry and entry.get("tool_call_id") is not None:
                message["tool_call_id"] = entry["tool_call_id"]

            # Codex / Responses clients may send role+name (e.g. name=bash) with no body after
            # tool-only content is stripped. Downstream Codex `ProcessedMessage` requires content.
            if "content" not in message or message.get("content") is None:
                message["content"] = ""

            return message

        return {"role": "user", "content": str(entry)}

    if input_payload is None:
        return []

    if isinstance(input_payload, str | bytes):
        text_value = (
            input_payload.decode("utf-8", "ignore")
            if isinstance(input_payload, bytes | bytearray)
            else input_payload
        )
        return [{"role": "user", "content": text_value}]

    if isinstance(input_payload, dict):
        normalized = _normalize_message_entry(input_payload)
        return [normalized] if normalized else []

    if isinstance(input_payload, list | tuple):
        messages: list[dict[str, Any]] = []
        for item in input_payload:
            normalized = _normalize_message_entry(item)
            if normalized:
                messages.append(normalized)
        return messages

    return [{"role": "user", "content": str(input_payload)}]


def normalize_responses_content(content: Any) -> Any:
    """Normalize Responses API content blocks into chat-compatible structures."""

    def _coerce_text_value(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, bytes | bytearray):
            return value.decode("utf-8", "ignore")
        if isinstance(value, list):
            segments: list[str] = []
            for segment in value:
                if isinstance(segment, dict):
                    segments.append(_coerce_text_value(segment.get("text")))
                else:
                    segments.append(str(segment))
            return "".join(segments)
        if isinstance(value, dict) and "text" in value:
            return _coerce_text_value(value.get("text"))
        return str(value) if value is not None else ""

    if content is None:
        return None

    if isinstance(content, str | bytes | bytearray):
        return _coerce_text_value(content)

    if isinstance(content, dict):
        normalized_parts = normalize_responses_content_part(content)
        if not normalized_parts:
            return None
        if len(normalized_parts) == 1 and normalized_parts[0].get("type") == "text":
            return normalized_parts[0]["text"]
        return normalized_parts

    if isinstance(content, list | tuple):
        collected_parts: list[dict[str, Any]] = []
        for part in content:
            if isinstance(part, dict):
                collected_parts.extend(normalize_responses_content_part(part))
            elif isinstance(part, str | bytes | bytearray):
                collected_parts.append(
                    {"type": "text", "text": _coerce_text_value(part)}
                )
        if not collected_parts:
            return None
        if len(collected_parts) == 1 and collected_parts[0].get("type") == "text":
            return collected_parts[0]["text"]
        return collected_parts

    return str(content)


def normalize_responses_content_part(
    part: dict[str, Any],
) -> NormalizedResponsesContentPartList:
    """Normalize a single Responses API content part.

    Returns a list of normalized content part dictionaries. Each part can be:
    - Text content: {"type": "text", "text": str}
    - Image content: {"type": "image_url", "image_url": dict}
    - Other content types: passed through as-is

    The normalized structure is documented in NormalizedResponsesContentPart.
    """

    part_type = str(part.get("type") or "").lower()
    normalized_parts: list[dict[str, Any]] = []

    if part_type in {"text", "input_text", "output_text"}:
        text_value = part.get("text")
        if text_value is None:
            text_value = part.get("value")
        normalized_parts.append({"type": "text", "text": safe_string(text_value)})
    elif "image" in part_type:
        image_payload = (
            part.get("image_url")
            or part.get("imageUrl")
            or part.get("image")
            or part.get("image_data")
        )
        if isinstance(image_payload, str):
            image_payload = {"url": image_payload}
        if isinstance(image_payload, dict) and image_payload.get("url"):
            normalized_parts.append({"type": "image_url", "image_url": image_payload})
    elif part_type == "tool_call":
        return []
    else:
        normalized_parts.append(part)

    return [p for p in normalized_parts if p]
