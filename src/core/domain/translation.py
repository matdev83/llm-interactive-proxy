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
        if isinstance(request, dict):
            model = request.get("model")
            messages = request.get("messages", [])
            top_k = request.get("top_k")
            top_p = request.get("top_p")
            temperature = request.get("temperature")
            max_tokens = request.get("max_tokens")
            stop = request.get("stop")
            reasoning_effort = request.get("reasoning_effort")
        else:
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
        # This is a placeholder implementation.
        return CanonicalChatResponse(
            id="chatcmpl-123",
            object="chat.completion",
            created=1677652288,
            model="gemini-pro",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content="\n\nHello there, how may I assist you today?",
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
        )

    @staticmethod
    def gemini_to_domain_stream_chunk(chunk: Any) -> Any:
        """
        Translate a Gemini streaming chunk to a CanonicalChatResponse.
        This is a placeholder implementation.
        """
        # In a real scenario, this would parse the Gemini chunk and convert it
        # to a standardized internal format. For now, we return the chunk as is.
        return chunk

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

        result = {
            "contents": [
                {"role": message.role, "parts": [{"text": message.content}]}
                for message in request.messages
            ],
            "generationConfig": config,
        }
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
        messages = [
            message.model_dump(exclude_unset=True)
            for message in request.messages
            if message.role != "system"
        ]
        system_message = next(
            (m.content for m in request.messages if m.role == "system"), None
        )

        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
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
        if request.tools:
            payload["tools"] = request.tools
        if request.tool_choice:
            payload["tool_choice"] = request.tool_choice

        return payload
