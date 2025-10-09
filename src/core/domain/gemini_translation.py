"""
Gemini translation utilities.

This module provides utilities for translating between Gemini API format and other formats.
"""

from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    MessageContentPartImage,
    MessageContentPartText,
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

        if "parts" not in content:
            continue

        parts = content["parts"]

        # Simple case: single text part
        if len(parts) == 1 and "text" in parts[0]:
            chat_messages.append(ChatMessage(role=role, content=parts[0]["text"]))
            continue

        # Complex case: multiple parts or non-text parts
        content_parts = []

        for part in parts:
            if "text" in part:
                content_parts.append(MessageContentPartText(text=part["text"]))
            elif "inline_data" in part:
                # Get image data from inline_data
                data = part["inline_data"].get("data", "")

                from src.core.domain.chat import ImageURL

                # Create image content part
                image_part = MessageContentPartImage(
                    image_url=ImageURL(url=data, detail=None)
                )
                content_parts.append(image_part)  # type: ignore

        if content_parts:
            chat_messages.append(ChatMessage(role=role, content=content_parts))

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

                finish_reason = choice.get("finish_reason")
                if isinstance(finish_reason, str) and finish_reason:
                    finish_reason_value = finish_reason.upper()
                else:
                    finish_reason_value = "STOP"

                candidate = {
                    "content": {
                        "parts": [{"text": content}],
                        "role": "model",  # Always use 'model' role for Gemini responses
                    },
                    "finishReason": finish_reason_value,
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
