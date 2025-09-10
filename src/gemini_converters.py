"""
Converter functions between Gemini API format and OpenAI format.
These functions enable the proxy to accept Gemini API requests and convert them
to the internal OpenAI format used by existing backends.
"""

import json
from typing import Any, cast

from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    MessageContentPartImage,
    MessageContentPartText,
)
from src.gemini_models import (
    Blob,
    Candidate,
    Content,
    FileData,
    FinishReason,
    GenerateContentRequest,
    GenerateContentResponse,
    ListModelsResponse,
    Model,
    Part,
    UsageMetadata,
)


def gemini_to_openai_messages(contents: list[Content]) -> list[ChatMessage]:
    """Convert Gemini contents to OpenAI messages format."""
    messages = []

    for content in contents:
        # Determine role mapping
        role = "user"  # Default role
        if content.role == "model":
            role = "assistant"
        elif content.role == "function":
            role = "function"
        elif content.role == "user" or content.role is None:
            role = "user"

        # If the client sends a functionResponse part (tool result), translate to OpenAI 'tool' message
        has_tool_response = False
        for part in content.parts:
            if getattr(part, "function_response", None):
                has_tool_response = True
                try:
                    payload = json.dumps(part.function_response)
                except (TypeError, ValueError):
                    payload = str(part.function_response)
                messages.append(ChatMessage(role="tool", content=payload))
        if has_tool_response:
            continue

        message_content = _parts_to_text(content.parts)
        if message_content:
            messages.append(ChatMessage(role=role, content=message_content))

    return messages


def openai_to_gemini_contents(messages: list[ChatMessage]) -> list[Content]:
    """Convert OpenAI messages to Gemini contents format."""
    contents = []
    system_messages = []

    for message in messages:
        # Collect system messages separately (we'll handle them later)
        if message.role == "system":
            system_messages.append(message)
            continue

        # Determine role mapping
        role = "user"  # Default role
        if message.role == "assistant":
            role = "model"
        elif message.role == "function":
            role = "function"
        elif message.role == "user":
            role = "user"

        # Create content with text or parts
        if isinstance(message.content, str):
            part = Part(text=message.content)  # type: ignore[call-arg]
            content = Content(parts=[part], role=role)
            contents.append(content)
        elif isinstance(message.content, list):
            parts_maybe = [_openai_part_to_gemini_part(p) for p in message.content]
            parts: list[Part] = [p for p in parts_maybe if p is not None]
            if parts:
                content = Content(parts=parts, role=role)
                contents.append(content)

    # Note: We don't use system messages directly in Gemini API
    # but we could add them as a user message if needed in the future

    return contents


def gemini_to_openai_request(
    gemini_request: GenerateContentRequest, model: str
) -> ChatRequest:
    """Convert Gemini GenerateContentRequest to OpenAI ChatCompletionRequest."""
    messages = gemini_to_openai_messages(gemini_request.contents)

    # Handle system instruction
    if gemini_request.system_instruction:
        system_messages = gemini_to_openai_messages([gemini_request.system_instruction])
        for msg in system_messages:
            msg.role = "system"
        messages = system_messages + messages

    # Convert generation config to OpenAI parameters
    max_tokens = None
    temperature = None
    top_p = None
    stop = None

    if gemini_request.generation_config:
        config = gemini_request.generation_config
        max_tokens = config.max_output_tokens
        temperature = config.temperature
        top_p = config.top_p
        stop = config.stop_sequences

    return ChatRequest(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        top_p=top_p,
        stop=stop,
        tool_choice=None,
        stream=False,  # Will be set separately for streaming requests
        n=None,
        presence_penalty=None,
        frequency_penalty=None,
        logit_bias=None,
        user=None,
        reasoning_effort=None,
        reasoning=None,
        thinking_budget=None,
        generation_config=None,
    )


def openai_to_gemini_response(openai_response: ChatResponse) -> GenerateContentResponse:
    """Convert OpenAI ChatCompletionResponse to Gemini GenerateContentResponse."""
    candidates = []

    for choice in cast(list[ChatCompletionChoice], openai_response.choices):
        # Convert choice to candidate
        content = None

        if choice.message:
            # Properly map OpenAI tool_calls to Gemini functionCall part
            if choice.message.tool_calls:
                part = _tool_call_to_function_call(choice.message.tool_calls[0])
                content = Content(parts=[part], role="model")
            elif choice.message.content:
                part = Part(text=choice.message.content)  # type: ignore[call-arg]
                content = Content(parts=[part], role="model")

        # Map finish reason
        finish_reason = None
        if choice.finish_reason == "stop":
            finish_reason = FinishReason.STOP
        elif choice.finish_reason == "length":
            finish_reason = FinishReason.MAX_TOKENS
        elif choice.finish_reason == "content_filter":
            finish_reason = FinishReason.SAFETY
        elif choice.finish_reason == "tool_calls":
            finish_reason = FinishReason.TOOL_CALLS
        elif choice.finish_reason == "function_call":
            finish_reason = FinishReason.FUNCTION_CALL

        candidate = Candidate(
            content=content, finishReason=finish_reason, index=choice.index
        )
        candidates.append(candidate)

    # Convert usage information
    usage_metadata = None
    if openai_response.usage:
        usage_metadata = UsageMetadata(
            promptTokenCount=openai_response.usage.get("prompt_tokens", 0),
            candidatesTokenCount=openai_response.usage.get("completion_tokens", 0),
            totalTokenCount=openai_response.usage.get("total_tokens", 0),
            cachedContentTokenCount=None,
        )

    return GenerateContentResponse(
        candidates=candidates, promptFeedback=None, usageMetadata=usage_metadata
    )


def openai_to_gemini_stream_chunk(chunk_data: str) -> str:
    """Convert OpenAI streaming chunk to Gemini streaming format."""
    try:
        # Parse the OpenAI chunk
        if chunk_data.startswith("data: "):
            chunk_data = chunk_data[6:]

        if chunk_data.strip() == "[DONE]":
            return "data: [DONE]\n\n"

        openai_chunk = json.loads(chunk_data)

        # Convert to Gemini format
        candidates = []
        if "choices" in openai_chunk:
            for choice in openai_chunk["choices"]:
                content = None
                part = _openai_delta_to_part(choice)
                if part is not None:
                    content = Content(parts=[part], role="model")

                finish_reason = None
                if choice.get("finish_reason") == "stop":
                    finish_reason = FinishReason.STOP
                elif choice.get("finish_reason") == "length":
                    finish_reason = FinishReason.MAX_TOKENS

                candidate = Candidate(
                    content=content,
                    finishReason=finish_reason,
                    index=choice.get("index", 0),
                )
                candidates.append(candidate)

        gemini_chunk = {
            "candidates": [
                candidate.model_dump(exclude_none=True, by_alias=True)
                for candidate in candidates
            ]
        }

        return f"data: {json.dumps(gemini_chunk)}\n\n"

    except json.JSONDecodeError:
        # If parsing fails, return empty chunk
        return "data: {}\n\n"


def gemini_to_openai_stream_chunk(chunk_data: str) -> str:
    """Convert Gemini streaming chunk to OpenAI streaming format."""
    try:
        # Parse the Gemini chunk
        if chunk_data.startswith("data: "):
            chunk_data = chunk_data[6:]

        if chunk_data.strip() == "[DONE]":
            return "data: [DONE]\n\n"

        gemini_chunk = json.loads(chunk_data)

        # Handle Gemini array format (multiple candidates in one chunk)
        if isinstance(gemini_chunk, list):
            openai_chunks = []
            for item in gemini_chunk:
                if item.get("candidates"):
                    candidate = item["candidates"][0]
                    openai_chunk = _gemini_candidate_to_openai_chunk(candidate)
                    if openai_chunk:
                        openai_chunks.append(openai_chunk)
            return "".join(openai_chunks)

        # Handle single Gemini object format
        elif isinstance(gemini_chunk, dict) and "candidates" in gemini_chunk:
            if gemini_chunk["candidates"]:
                candidate = gemini_chunk["candidates"][0]
                openai_chunk = _gemini_candidate_to_openai_chunk(candidate)
                if openai_chunk:
                    return openai_chunk

        # If parsing fails, return empty chunk
        return "data: {}\n\n"

    except json.JSONDecodeError:
        # If parsing fails, return empty chunk
        return "data: {}\n\n"


def _gemini_candidate_to_openai_chunk(candidate: dict[str, Any]) -> str | None:
    """Convert a single Gemini candidate to OpenAI chunk format."""
    try:
        openai_chunk: dict[str, Any] = {
            "id": "chatcmpl-gemini",
            "object": "chat.completion.chunk",
            "created": 1677652288,
            "model": "gemini",
            "choices": [],
        }

        choice: dict[str, Any] = {"index": 0, "delta": {}, "finish_reason": None}

        # Extract content from Gemini candidate
        if "content" in candidate:
            content = candidate["content"]
            if "parts" in content:
                for part in content["parts"]:
                    if "text" in part:
                        choice["delta"]["content"] = part["text"]
                    elif "functionCall" in part:
                        # Handle function calls
                        function_call = part["functionCall"]
                        choice["delta"]["tool_calls"] = [
                            {
                                "index": 0,
                                "id": f"call_{function_call.get('name', 'unknown')}",
                                "function": {
                                    "name": function_call.get("name", ""),
                                    "arguments": json.dumps(
                                        function_call.get("args", {})
                                    ),
                                },
                                "type": "function",
                            }
                        ]

        # Extract finish reason
        if "finishReason" in candidate:
            finish_reason = candidate["finishReason"].lower()
            if finish_reason == "stop":
                choice["finish_reason"] = "stop"
            elif finish_reason == "max_tokens":
                choice["finish_reason"] = "length"
            elif finish_reason == "tool_calls":
                choice["finish_reason"] = "tool_calls"

        openai_chunk["choices"].append(choice)
        return f"data: {json.dumps(openai_chunk)}\n\n"

    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def openai_models_to_gemini_models(
    openai_models: list[dict[str, Any]],
) -> ListModelsResponse:
    """Convert OpenAI models list to Gemini models format."""
    gemini_models = []

    for model_data in openai_models:
        model_id = model_data.get("id", "")

        # Create Gemini-style model entry
        gemini_model = Model(
            name=f"models/{model_id}",
            base_model_id=model_id,
            version="001",  # Default version
            display_name=model_id.replace("-", " ").title(),
            description=f"Model {model_id} via LLM Interactive Proxy",
            input_token_limit=32768,  # Default reasonable limit
            output_token_limit=4096,  # Default reasonable limit
            supported_generation_methods=["generateContent", "streamGenerateContent"],
            temperature=1.0,
            max_temperature=2.0,
            top_p=1.0,
            top_k=40,
        )
        gemini_models.append(gemini_model)

    return ListModelsResponse(models=gemini_models)


def extract_model_from_gemini_path(path: str) -> str:
    """Extract model name from Gemini API path like /v1beta/models/gemini-pro:generateContent."""
    # Path format: /v1beta/models/{model}:generateContent or /v1beta/models/{model}:streamGenerateContent
    if "/models/" in path:
        # Extract the part between /models/ and the next :
        parts = path.split("/models/")[1]
        model = parts.split(":")[0]
        return model
    return "gemini-pro"  # Default fallback


def is_streaming_request(path: str) -> bool:
    """Check if the request is for streaming based on the path."""
    return ":streamGenerateContent" in path


def _parts_to_text(parts: list[Part]) -> str:
    lines: list[str] = []
    for part in parts:
        if part.text:
            lines.append(part.text)
        elif part.inline_data:
            lines.append(f"[Attachment: {part.inline_data.mime_type}]")
        elif part.file_data:
            lines.append(f"[File: {part.file_data.file_uri}]")
    return "\n".join(lines) if lines else ""


def _openai_part_to_gemini_part(
    part_item: MessageContentPartText | MessageContentPartImage | Any,
) -> Part | None:
    if isinstance(part_item, MessageContentPartText):
        return Part(text=part_item.text)  # type: ignore[call-arg]
    if isinstance(part_item, MessageContentPartImage):
        url = part_item.image_url.url
        if url.startswith("data:"):
            try:
                header, b64_data = url.split(",", 1)
                mime = header.split(";")[0][5:]
                return Part(inline_data=Blob(mime_type=mime, data=b64_data))  # type: ignore[call-arg]
            except ValueError:
                return Part(text=f"[Image: {url}]")  # type: ignore[call-arg]
        return Part(
            file_data=FileData(mime_type="application/octet-stream", file_uri=url)
        )  # type: ignore[call-arg]
    return None


def _tool_call_to_function_call(tool_call: dict[str, Any] | Any) -> Part:
    try:
        args_obj = json.loads(tool_call["function"]["arguments"])  # type: ignore[index]
        name = tool_call["function"]["name"]  # type: ignore[index]
    except (json.JSONDecodeError, KeyError, TypeError):
        args_obj = {
            "_raw": getattr(getattr(tool_call, "function", {}), "arguments", "")
        }
        name = getattr(getattr(tool_call, "function", {}), "name", "function")
    fc = {"name": name, "args": args_obj}
    return Part(function_call=fc)  # type: ignore[call-arg]


def _openai_delta_to_part(choice_fragment: dict[str, Any]) -> Part | None:
    delta = choice_fragment.get("delta")
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    if not content:
        return None
    return Part(text=content)  # type: ignore[call-arg]
