from __future__ import annotations

from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
)


class Translation:
    """
    A class for translating requests and responses between different API formats.
    """

    @staticmethod
    def gemini_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate a Gemini request to a CanonicalChatRequest.
        """
        from src.core.domain.gemini_translation import (
            gemini_request_to_canonical_request,
        )

        if isinstance(request, dict):
            return gemini_request_to_canonical_request(request)

        # Legacy format handling (for backward compatibility)
        model = getattr(request, "model", None)
        messages = getattr(request, "messages", [])
        top_k = getattr(request, "top_k", None)
        top_p = getattr(request, "top_p", None)
        temperature = getattr(request, "temperature", None)
        max_tokens = getattr(request, "max_tokens", None)
        stop = getattr(request, "stop", None)
        reasoning_effort = getattr(request, "reasoning_effort", None)

        if not model:
            raise ValueError("Model not found in request")

        # Convert messages to ChatMessage objects if they are dicts
        chat_messages = []
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
            reasoning_effort=reasoning_effort,
        )

    @staticmethod
    def anthropic_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate an Anthropic request to a CanonicalChatRequest.
        """
        return CanonicalChatRequest(
            model=request.model,
            messages=request.messages,
            temperature=request.temperature,
            top_p=request.top_p,
            top_k=request.top_k,
            n=request.n,
            stream=request.stream,
            stop=request.stop,
            max_tokens=request.max_tokens,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            logit_bias=request.logit_bias,
            user=request.user,
            reasoning_effort=request.reasoning_effort,
            seed=request.seed,
            tools=request.tools,
            tool_choice=request.tool_choice,
            extra_body=request.extra_body,
        )

    @staticmethod
    def anthropic_to_domain_response(response: Any) -> CanonicalChatResponse:
        """
        Translate an Anthropic response to a CanonicalChatResponse.
        """
        # This is a placeholder implementation.
        return CanonicalChatResponse(
            id="chatcmpl-anthropic-123",
            object="chat.completion",
            created=1677652288,
            model="claude-v1",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="Hello from Anthropic, how may I assist you?",
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
        )

    @staticmethod
    def gemini_to_domain_response(response: Any) -> CanonicalChatResponse:
        """
        Translate a Gemini response to a CanonicalChatResponse.
        """
        import time
        import uuid

        # Generate a unique ID for the response
        response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        model = "gemini-pro"  # Default model if not specified

        # Extract choices from candidates
        choices = []
        if isinstance(response, dict) and "candidates" in response:
            for idx, candidate in enumerate(response["candidates"]):
                content = ""
                tool_calls = None

                # Extract content from parts
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]

                    # Extract text content
                    text_parts = []
                    for part in parts:
                        if "text" in part:
                            text_parts.append(part["text"])
                        elif "functionCall" in part:
                            # Handle function calls (tool calls)
                            if tool_calls is None:
                                tool_calls = []

                            function_call = part["functionCall"]
                            tool_calls.append(
                                {
                                    "id": f"call_{uuid.uuid4().hex[:12]}",
                                    "type": "function",
                                    "function": {
                                        "name": function_call.get("name", ""),
                                        "arguments": function_call.get("args", "{}"),
                                    },
                                }
                            )

                    content = "".join(text_parts)

                # Map finish reason
                finish_reason = candidate.get("finishReason", "STOP").lower()
                if finish_reason == "stop":
                    finish_reason = "stop"
                elif finish_reason == "max_tokens":
                    finish_reason = "length"
                elif finish_reason == "safety":
                    finish_reason = "content_filter"
                elif finish_reason == "tool_calls":
                    finish_reason = "tool_calls"
                else:
                    finish_reason = "stop"  # Default

                # Create choice
                choice = ChatCompletionChoice(
                    index=idx,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content=content, tool_calls=tool_calls  # type: ignore
                    ),
                    finish_reason=finish_reason,
                )
                choices.append(choice)

        # Extract usage metadata
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if isinstance(response, dict) and "usageMetadata" in response:
            usage_metadata = response["usageMetadata"]
            usage = {
                "prompt_tokens": usage_metadata.get("promptTokenCount", 0),
                "completion_tokens": usage_metadata.get("candidatesTokenCount", 0),
                "total_tokens": usage_metadata.get("totalTokenCount", 0),
            }

        # If no choices were extracted, create a default one
        if not choices:
            choices = [
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="",
                    ),
                    finish_reason="stop",
                )
            ]

        return CanonicalChatResponse(
            id=response_id,
            object="chat.completion",
            created=created,
            model=model,
            choices=choices,
            usage=usage,
        )

    @staticmethod
    def gemini_to_domain_stream_chunk(chunk: Any) -> Any:
        """
        Translate a Gemini streaming chunk to a CanonicalChatResponse.
        """
        import time
        import uuid

        # Generate a unique ID for the response
        response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        model = "gemini-pro"  # Default model if not specified

        # Extract content from the chunk
        content = ""
        if isinstance(chunk, dict) and "candidates" in chunk:
            for candidate in chunk["candidates"]:
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            content += part["text"]

        # Create a canonical response
        return {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        }

    @staticmethod
    def openai_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate an OpenAI request to a CanonicalChatRequest.
        """
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

        if not model:
            raise ValueError("Model not found in request")

        # Convert messages to ChatMessage objects if they are dicts
        chat_messages = []
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
        )

    @staticmethod
    def openai_to_domain_response(response: Any) -> CanonicalChatResponse:
        """
        Translate an OpenAI response to a CanonicalChatResponse.
        """
        # Parse a typical OpenAI-style response dict into the canonical model.
        if not isinstance(response, dict):
            # Fallback placeholder for non-dict responses
            return CanonicalChatResponse(
                id="chatcmpl-openai-unknown",
                object="chat.completion",
                created=int(__import__("time").time()),
                model=getattr(response, "model", "unknown"),
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=str(response)
                        ),
                        finish_reason="stop",
                    )
                ],
                usage={},
            )

        choices: list[ChatCompletionChoice] = []
        for idx, ch in enumerate(response.get("choices", [])):
            msg = ch.get("message", {})
            role = msg.get("role", "assistant")
            content = msg.get("content")

            # Preserve tool_calls if present
            tool_calls = None
            if isinstance(msg.get("tool_calls"), list):
                tool_calls = list(msg.get("tool_calls"))

            message_obj = ChatCompletionChoiceMessage(
                role=role, content=content, tool_calls=tool_calls
            )

            choices.append(
                ChatCompletionChoice(
                    index=idx,
                    message=message_obj,
                    finish_reason=ch.get("finish_reason"),
                )
            )

        usage = response.get("usage") or {}

        return CanonicalChatResponse(
            id=response.get("id", "chatcmpl-openai-unk"),
            object=response.get("object", "chat.completion"),
            created=response.get("created", int(__import__("time").time())),
            model=response.get("model", "unknown"),
            choices=choices,
            usage=usage,
        )

    @staticmethod
    def openai_to_domain_stream_chunk(chunk: Any) -> Any:
        """
        Translate an OpenAI streaming chunk to a CanonicalChatResponse.
        This is a placeholder implementation.
        """
        # In a real scenario, this would parse the OpenAI chunk and convert it
        # to a standardized internal format. For now, we return the chunk as is.
        return chunk

    @staticmethod
    def openrouter_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate an OpenRouter request to a CanonicalChatRequest.
        """
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

        # Convert messages to ChatMessage objects if they are dicts
        chat_messages = []
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

    @staticmethod
    def from_domain_to_gemini_request(request: CanonicalChatRequest) -> dict[str, Any]:
        """
        Translate a CanonicalChatRequest to a Gemini request.
        """

        config: dict[str, Any] = {}
        if request.top_k is not None:
            config["topK"] = request.top_k
        if request.top_p is not None:
            config["topP"] = request.top_p
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_tokens is not None:
            config["maxOutputTokens"] = request.max_tokens
        if request.stop:
            config["stopSequences"] = request.stop
        if request.reasoning_effort is not None:
            config["thinkingConfig"] = {"reasoning_effort": request.reasoning_effort}

        # Process messages with proper handling of multimodal content and tool calls
        contents = []
        for message in request.messages:
            msg_dict = {"role": message.role}
            parts = []

            # Handle content which could be string, list of parts, or None
            if message.content is None:
                # Skip empty content
                continue
            elif isinstance(message.content, str):
                # Simple text content
                parts.append({"text": message.content})
            elif isinstance(message.content, list):
                # Multimodal content (list of parts)
                for part in message.content:
                    if hasattr(part, "type") and part.type == "image":
                        # Handle image part
                        if hasattr(part, "image_url") and part.image_url:
                            parts.append(
                                {
                                    "inline_data": {
                                        "mime_type": "image/jpeg",  # Assume JPEG by default
                                        "data": str(part.image_url.url),
                                    }  # type: ignore
                                }
                            )
                    elif hasattr(part, "type") and part.type == "text":
                        # Handle text part
                        if hasattr(part, "text"):
                            parts.append({"text": part.text})
                    else:
                        # Try best effort conversion
                        if hasattr(part, "model_dump"):
                            part_dict = part.model_dump()
                            if "text" in part_dict:
                                parts.append({"text": part_dict["text"]})

            # Add parts to message
            msg_dict["parts"] = parts  # type: ignore

            # Only add non-empty messages
            if parts:
                contents.append(msg_dict)

        result = {
            "contents": contents,
            "generationConfig": config,
        }

        # Add tools if present
        if request.tools:
            # Convert OpenAI-style tools to Gemini format
            gemini_tools = []
            for tool in request.tools:
                if isinstance(tool, dict) and "function" in tool:
                    function = tool["function"]
                    gemini_tool = {
                        "function_declarations": [
                            {
                                "name": function.get("name", ""),
                                "description": function.get("description", ""),
                                "parameters": function.get("parameters", {}),
                            }
                        ]
                    }
                    gemini_tools.append(gemini_tool)
                elif hasattr(tool, "model_dump"):
                    tool_dict = tool.model_dump()
                    if "function" in tool_dict:
                        function = tool_dict["function"]
                        gemini_tool = {
                            "function_declarations": [
                                {
                                    "name": function.get("name", ""),
                                    "description": function.get("description", ""),
                                    "parameters": function.get("parameters", {}),
                                }
                            ]
                        }
                        gemini_tools.append(gemini_tool)

            if gemini_tools:
                result["tools"] = gemini_tools

        return result

    @staticmethod
    def from_domain_to_openai_request(request: CanonicalChatRequest) -> dict[str, Any]:
        """
        Translate a CanonicalChatRequest to an OpenAI request.
        """
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }

        # Add all supported parameters
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stream is not None:
            payload["stream"] = request.stream
        if request.stop is not None:
            payload["stop"] = request.stop
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

        return payload

    @staticmethod
    def from_domain_to_anthropic_request(
        request: CanonicalChatRequest,
    ) -> dict[str, Any]:
        """
        Translate a CanonicalChatRequest to an Anthropic request.
        """
        # Process messages with proper handling of system messages and multimodal content
        processed_messages = []
        system_message = None

        for message in request.messages:
            if message.role == "system":
                # Extract system message
                system_message = message.content
                continue

            # Process regular messages
            msg_dict = {"role": message.role}

            # Handle content which could be string, list of parts, or None
            if message.content is None:
                # Skip empty content
                continue
            elif isinstance(message.content, str):
                # Simple text content
                msg_dict["content"] = message.content
            elif isinstance(message.content, list):
                # Multimodal content (list of parts)
                content_parts = []
                for part in message.content:
                    if hasattr(part, "type") and part.type == "image":
                        # Handle image part
                        if hasattr(part, "image_url") and part.image_url:
                            content_parts.append(
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "url",
                                        "url": str(part.image_url.url),
                                    },
                                }
                            )
                    elif hasattr(part, "type") and part.type == "text":
                        # Handle text part
                        if hasattr(part, "text"):
                            content_parts.append({"type": "text", "text": part.text})
                    else:
                        # Try best effort conversion
                        if hasattr(part, "model_dump"):
                            part_dict = part.model_dump()
                            if "text" in part_dict:
                                content_parts.append(
                                    {"type": "text", "text": part_dict["text"]}
                                )

                if content_parts:
                    # Use type annotation to help mypy
                    msg_dict["content"] = content_parts  # type: ignore

            # Handle tool calls if present
            if message.tool_calls:
                tool_calls = []
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "model_dump"):
                        tool_call_dict = tool_call.model_dump()
                        tool_calls.append(tool_call_dict)
                    elif isinstance(tool_call, dict):
                        tool_calls.append(tool_call)
                    else:
                        # Convert to dict if possible
                        try:
                            tool_call_dict = dict(tool_call)
                            tool_calls.append(tool_call_dict)
                        except (TypeError, ValueError):
                            # Skip if can't convert
                            continue

                if tool_calls:
                    # Use type annotation to help mypy
                    msg_dict["tool_calls"] = tool_calls  # type: ignore

            # Handle tool call ID if present
            if message.tool_call_id:
                msg_dict["tool_call_id"] = message.tool_call_id

            # Handle name if present
            if message.name:
                msg_dict["name"] = message.name

            processed_messages.append(msg_dict)

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": processed_messages,
            "max_tokens": request.max_tokens or 1024,
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

        # Handle tools if present
        if request.tools:
            # Convert tools to Anthropic format
            anthropic_tools = []
            for tool in request.tools:
                if isinstance(tool, dict) and "function" in tool:
                    anthropic_tool = {"type": "function", "function": tool["function"]}
                    anthropic_tools.append(anthropic_tool)
                elif hasattr(tool, "model_dump"):
                    tool_dict = tool.model_dump()
                    if "function" in tool_dict:
                        anthropic_tool = {
                            "type": "function",
                            "function": tool_dict["function"],
                        }
                        anthropic_tools.append(anthropic_tool)

            if anthropic_tools:
                payload["tools"] = anthropic_tools

        # Handle tool_choice if present
        if request.tool_choice:
            if isinstance(request.tool_choice, dict):
                if request.tool_choice.get("type") == "function":
                    # Already in Anthropic format
                    payload["tool_choice"] = request.tool_choice
                elif "function" in request.tool_choice:
                    # Convert from OpenAI format to Anthropic format
                    payload["tool_choice"] = {
                        "type": "function",
                        "function": request.tool_choice["function"],
                    }
            elif request.tool_choice == "auto" or request.tool_choice == "none":
                payload["tool_choice"] = request.tool_choice

        # Add stop sequences if present
        if request.stop:
            payload["stop_sequences"] = request.stop

        # Add metadata if present in extra_body
        if request.extra_body and isinstance(request.extra_body, dict):
            metadata = request.extra_body.get("metadata")
            if metadata:
                payload["metadata"] = metadata

        return payload
