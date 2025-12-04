"""
Gemini translation utilities.

This module provides utilities for translating between Gemini API format and other formats.
"""

import json
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    MessageContentPartImage,
    MessageContentPartText,
    ToolCall,
)


def gemini_content_to_chat_messages(
    contents: list[dict[str, Any]],
) -> list[ChatMessage]:
    """
    Convert Gemini content array to a list of ChatMessage objects.

    Args:
        contents: List of content items from Gemini request

    Returns:
        List of ChatMessage objects
    """
    chat_messages = []

    for content in contents:
        role = content.get("role", "user")
        if role == "model":
            role = "assistant"

        if "parts" not in content:
            continue

        parts = content["parts"]

        # Handle Gemini functionResponse parts (tool results)
        handled_tool_responses = False
        for part in parts:
            if not isinstance(part, dict):
                continue

            function_response = part.get("functionResponse") or part.get(
                "function_response"
            )
            if not function_response:
                continue

            if not isinstance(function_response, dict):
                continue

            response_payload = function_response.get("response")

            if isinstance(response_payload, dict | list):
                try:
                    content_text = json.dumps(response_payload)
                except (TypeError, ValueError):
                    content_text = str(response_payload)
            elif response_payload is None:
                content_text = ""
            else:
                content_text = str(response_payload)

            tool_call_id = (
                function_response.get("toolCallId")
                or function_response.get("tool_call_id")
                or function_response.get("id")
                or function_response.get("name")
            )
            tool_name = function_response.get("name")

            chat_messages.append(
                ChatMessage(
                    role="tool",
                    content=content_text,
                    name=tool_name,
                    tool_call_id=(
                        tool_call_id if isinstance(tool_call_id, str) else None
                    ),
                    metadata={
                        "is_proxy_tool_output": True,
                        "source": "gemini_translation",
                    },
                )
            )

            handled_tool_responses = True

        if handled_tool_responses:
            continue

        # Simple case: single text part
        if len(parts) == 1 and "text" in parts[0]:
            chat_messages.append(ChatMessage(role=role, content=parts[0]["text"]))
            continue

        # Complex case: multiple parts or non-text parts
        content_parts: list[MessageContentPartText | MessageContentPartImage] = []
        tool_calls: list[ToolCall] = []
        tool_responses: list[ChatMessage] = []

        for part in parts:
            function_response = part.get("functionResponse") or part.get(
                "function_response"
            )
            if function_response:
                response_payload = function_response.get("response")
                if isinstance(response_payload, str):
                    response_content = response_payload
                else:
                    try:
                        response_content = json.dumps(response_payload)
                    except (TypeError, ValueError):
                        response_content = str(response_payload)

                tool_message_kwargs: dict[str, Any] = {
                    "role": "tool",
                    "content": response_content,
                    "metadata": {
                        "is_proxy_tool_output": True,
                        "source": "gemini_translation",
                    },
                }

                name = function_response.get("name")
                if isinstance(name, str) and name:
                    tool_message_kwargs["name"] = name

                tool_call_id = function_response.get(
                    "toolCallId"
                ) or function_response.get("tool_call_id")
                if isinstance(tool_call_id, str) and tool_call_id:
                    tool_message_kwargs["tool_call_id"] = tool_call_id

                tool_responses.append(ChatMessage(**tool_message_kwargs))
                continue

            if "text" in part:
                content_parts.append(MessageContentPartText(text=part["text"]))
                continue

            if "functionCall" in part:
                from src.core.domain.translation import Translation

                tool_calls.append(
                    Translation._process_gemini_function_call(
                        part["functionCall"], part=part
                    )
                )
                continue

            inline_data = part.get("inlineData") or part.get("inline_data")
            file_data = part.get("fileData") or part.get("file_data")

            if inline_data:
                base64_data = inline_data.get("data", "")

                from src.core.domain.chat import ImageURL

                image_part = MessageContentPartImage(
                    image_url=ImageURL(url=base64_data, detail=None)
                )
                content_parts.append(image_part)  # type: ignore[arg-type]
            elif file_data:
                from src.core.domain.chat import ImageURL

                file_uri = file_data.get("fileUri") or file_data.get("file_uri") or ""
                if file_uri:
                    image_part = MessageContentPartImage(
                        image_url=ImageURL(url=file_uri, detail=None)
                    )
                    content_parts.append(image_part)  # type: ignore[arg-type]

        if not content_parts and not tool_calls and not tool_responses:
            continue

        if content_parts or tool_calls:
            message_content: (
                str | list[MessageContentPartText | MessageContentPartImage] | None
            )
            message_content = content_parts if content_parts else None

            chat_messages.append(
                ChatMessage(
                    role=role,
                    content=message_content,
                    tool_calls=tool_calls or None,
                )
            )

        if tool_responses:
            chat_messages.extend(tool_responses)

    return chat_messages


def gemini_request_to_canonical_request(
    request: dict[str, Any],
) -> CanonicalChatRequest:
    """
    Convert a Gemini API request to a CanonicalChatRequest.

    Args:
        request: Gemini API request

    Returns:
        CanonicalChatRequest
    """
    # Extract model
    model = request.get("model", "")

    # Extract contents and convert to messages
    contents = request.get("contents", [])
    messages = gemini_content_to_chat_messages(contents)

    # Extract generation config
    generation_config = request.get("generationConfig", {})
    temperature = generation_config.get("temperature")
    top_p = generation_config.get("topP")
    top_k = generation_config.get("topK")
    max_tokens = generation_config.get("maxOutputTokens")
    stop = generation_config.get("stopSequences")

    # Extract additional generationConfig parameters (Gemini API parity)
    candidate_count = generation_config.get("candidateCount")
    seed = generation_config.get("seed")
    presence_penalty = generation_config.get("presencePenalty")
    frequency_penalty = generation_config.get("frequencyPenalty")
    logprobs = generation_config.get("responseLogprobs")
    top_logprobs = generation_config.get("logprobs")

    # Handle responseMimeType and responseSchema for structured output
    response_format: dict[str, Any] | None = None
    response_mime_type = generation_config.get("responseMimeType")
    response_schema = generation_config.get("responseSchema")

    if response_mime_type == "application/json":
        if response_schema:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.get("title", "response"),
                    "schema": response_schema,
                    "strict": True,
                },
            }
        else:
            response_format = {"type": "json_object"}
    elif response_mime_type == "text/plain":
        response_format = {"type": "text"}

    # Extract tools
    tools = []
    tool_choice: str | dict[str, Any] | None = None
    if "tools" in request:
        for tool in request["tools"]:
            if "function_declarations" in tool:
                for func_decl in tool["function_declarations"]:
                    tools.append(
                        {
                            "type": "function",
                            "function": {
                                "name": func_decl.get("name", ""),
                                "description": func_decl.get("description", ""),
                                "parameters": func_decl.get("parameters", {}),
                            },
                        }
                    )

    # Extract streaming flag
    stream = request.get("stream", False)

    # Extract system instruction if present
    system_message = None
    if "systemInstruction" in request and "parts" in request["systemInstruction"]:
        parts = request["systemInstruction"]["parts"]
        if parts and "text" in parts[0]:
            system_message = ChatMessage(role="system", content=parts[0]["text"])
            messages.insert(0, system_message)

    # Handle thinking config (reasoning effort)
    reasoning_effort = None
    thinking_budget = None
    if "thinkingConfig" in generation_config:
        thinking_config = generation_config["thinkingConfig"]
        if isinstance(thinking_config, dict):
            if "reasoning_effort" in thinking_config:
                reasoning_effort = thinking_config["reasoning_effort"]
            if "thinkingBudget" in thinking_config:
                thinking_budget = thinking_config["thinkingBudget"]

    tool_config = request.get("toolConfig") or request.get("tool_config")
    if isinstance(tool_config, dict):
        fcc = tool_config.get("functionCallingConfig") or tool_config.get(
            "function_calling_config"
        )
        if isinstance(fcc, dict):
            mode = str(fcc.get("mode", "AUTO")).upper()
            allowed = fcc.get("allowedFunctionNames") or fcc.get(
                "allowed_function_names"
            )

            if mode == "NONE":
                tool_choice = "none"
            elif mode == "AUTO":
                tool_choice = "auto"
            elif mode == "ANY":
                if isinstance(allowed, list) and allowed:
                    tool_choice = {
                        "type": "function",
                        "function": {"name": allowed[0]},
                    }
                else:
                    tool_choice = "auto"

    # Store safetySettings in extra_body for passthrough
    extra_body: dict[str, Any] | None = None
    safety_settings = request.get("safetySettings")
    cached_content = request.get("cachedContent")
    if safety_settings or cached_content:
        extra_body = {}
        if safety_settings:
            extra_body["gemini_safety_settings"] = safety_settings
        if cached_content:
            extra_body["gemini_cached_content"] = cached_content

    # Create canonical request
    return CanonicalChatRequest(
        model=model,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        top_k=top_k,
        max_tokens=max_tokens,
        stop=stop,
        stream=stream,
        tools=tools if tools else None,  # type: ignore
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
        thinking_budget=thinking_budget,
        n=candidate_count,
        seed=seed,
        presence_penalty=presence_penalty,
        frequency_penalty=frequency_penalty,
        logprobs=logprobs,
        top_logprobs=top_logprobs,
        response_format=response_format,
        extra_body=extra_body,
    )


def _map_finish_reason_to_gemini(finish_reason: str | None) -> str:
    """Map canonical finish reason to Gemini finish reason format.

    Gemini API uses: STOP, MAX_TOKENS, SAFETY, RECITATION, OTHER, FINISH_REASON_UNSPECIFIED
    OpenAI uses: stop, length, content_filter, tool_calls, function_call
    """
    if not finish_reason:
        return "STOP"

    finish_reason_lower = finish_reason.lower()
    mapping = {
        "stop": "STOP",
        "length": "MAX_TOKENS",
        "max_tokens": "MAX_TOKENS",
        "content_filter": "SAFETY",
        "safety": "SAFETY",
        "tool_calls": "STOP",
        "function_call": "STOP",
        "recitation": "RECITATION",
        "other": "OTHER",
    }
    return mapping.get(finish_reason_lower, finish_reason.upper())


def canonical_response_to_gemini_response(
    response: dict[str, Any], is_streaming: bool = False
) -> dict[str, Any]:
    """
    Convert a canonical response to Gemini API format.

    Args:
        response: Canonical response in OpenAI format
        is_streaming: Whether this is a streaming response

    Returns:
        Response in Gemini API format
    """
    if not is_streaming:
        # Non-streaming response
        candidates = []

        if "choices" in response:
            for idx, choice in enumerate(response["choices"]):
                message = choice.get("message", {})
                content = message.get("content", "")
                parts: list[dict[str, Any]] = []

                # Add text content if present
                if content:
                    parts.append({"text": content})

                # Handle tool calls if present
                if "tool_calls" in message:
                    for tool_call in message["tool_calls"]:
                        if tool_call.get("type") == "function":
                            function_call = tool_call.get("function", {})
                            args = function_call.get("arguments", {})
                            # Parse JSON args if it's a string
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except (json.JSONDecodeError, TypeError):
                                    pass
                            parts.append(
                                {
                                    "functionCall": {
                                        "name": function_call.get("name", ""),
                                        "args": args,
                                    }
                                }
                            )

                # Ensure at least one part exists
                if not parts:
                    parts.append({"text": ""})

                candidate: dict[str, Any] = {
                    "content": {
                        "parts": parts,
                        "role": "model",
                    },
                    "finishReason": _map_finish_reason_to_gemini(
                        choice.get("finish_reason")
                    ),
                    "index": idx,
                }

                # Add safety ratings (empty by default for proxy responses)
                candidate["safetyRatings"] = []

                # Add logprobs if present
                if "logprobs" in choice and choice["logprobs"]:
                    candidate["avgLogprobs"] = choice["logprobs"].get(
                        "avg_logprob", None
                    )

                candidates.append(candidate)

        # Create usage metadata
        usage = response.get("usage", {})
        usage_metadata = {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        }

        # Add cached token count if present
        if "cached_tokens" in usage:
            usage_metadata["cachedContentTokenCount"] = usage["cached_tokens"]

        result: dict[str, Any] = {
            "candidates": candidates,
            "usageMetadata": usage_metadata,
        }

        # Add model version if available
        if "model" in response:
            result["modelVersion"] = response["model"]

        return result
    # Streaming responses
    stream_result: dict[str, Any] = {}

    # Handle usage metadata if present
    if "usage" in response:
        stream_usage = response["usage"]
        stream_result["usageMetadata"] = {
            "promptTokenCount": stream_usage.get("prompt_tokens", 0),
            "candidatesTokenCount": stream_usage.get("completion_tokens", 0),
            "totalTokenCount": stream_usage.get("total_tokens", 0),
        }

    # Handle content and finish reason if choices are present
    if response.get("choices"):
        choice = response["choices"][0]
        delta = choice.get("delta", {})
        content = delta.get("content", "")
        finish_reason = choice.get("finish_reason")
        stream_parts: list[dict[str, Any]] = []

        # Add text content
        if content:
            stream_parts.append({"text": content})

        # Handle streaming tool calls
        tool_calls = delta.get("tool_calls")
        if tool_calls:
            for tool_call in tool_calls:
                if tool_call.get("type") == "function" or "function" in tool_call:
                    function_call = tool_call.get("function", {})
                    args = function_call.get("arguments", "")
                    if isinstance(args, str) and args:
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if function_call.get("name"):
                        stream_parts.append(
                            {
                                "functionCall": {
                                    "name": function_call.get("name", ""),
                                    "args": args if args else {},
                                }
                            }
                        )

        # Ensure at least empty parts list
        if not stream_parts:
            stream_parts.append({"text": ""})

        stream_candidate: dict[str, Any] = {
            "content": {
                "parts": stream_parts,
                "role": "model",
            },
            "index": choice.get("index", 0),
        }

        if finish_reason:
            stream_candidate["finishReason"] = _map_finish_reason_to_gemini(
                finish_reason
            )

        stream_result["candidates"] = [stream_candidate]

    return stream_result
