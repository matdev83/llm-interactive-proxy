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
                    Translation._process_gemini_function_call(part["functionCall"])
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
    if "thinkingConfig" in generation_config:
        thinking_config = generation_config["thinkingConfig"]
        if isinstance(thinking_config, dict) and "reasoning_effort" in thinking_config:
            reasoning_effort = thinking_config["reasoning_effort"]

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
        tools=tools,  # type: ignore
        tool_choice=tool_choice,
        reasoning_effort=reasoning_effort,
    )


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

                candidate = {
                    "content": {
                        "parts": [{"text": content}],
                        "role": "model",  # Always use 'model' role for Gemini responses
                    },
                    "finishReason": choice.get("finish_reason", "STOP").upper(),
                    "index": idx,
                }

                # Handle tool calls if present
                if "tool_calls" in message:
                    for tool_call in message["tool_calls"]:
                        if tool_call.get("type") == "function":
                            function_call = tool_call.get("function", {})
                            candidate["content"]["parts"].append(
                                {
                                    "functionCall": {
                                        "name": function_call.get("name", ""),
                                        "args": function_call.get("arguments", {}),
                                    }
                                }
                            )

                candidates.append(candidate)

        # Create usage metadata
        usage = response.get("usage", {})
        usage_metadata = {
            "promptTokenCount": usage.get("prompt_tokens", 0),
            "candidatesTokenCount": usage.get("completion_tokens", 0),
            "totalTokenCount": usage.get("total_tokens", 0),
        }

        return {
            "candidates": candidates,
            "usageMetadata": usage_metadata,
        }
    else:
        # For streaming, we'd typically return just the delta
        # This is a simplification - in a real implementation,
        # we'd need to handle the streaming format differences
        delta = response.get("choices", [{}])[0].get("delta", {})
        content = delta.get("content", "")

        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": content}],
                        "role": "model",
                    },
                    "index": 0,
                }
            ]
        }
