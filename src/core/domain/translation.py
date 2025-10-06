from __future__ import annotations

import json
import mimetypes
from typing import Any

from src.core.domain.base_translator import BaseTranslator
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
    FunctionCall,
    ToolCall,
)


class Translation(BaseTranslator):
    """
    A class for translating requests and responses between different API formats.
    """

    @staticmethod
    def validate_json_against_schema(
        json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Validate JSON data against a JSON schema.

        Args:
            json_data: The JSON data to validate
            schema: The JSON schema to validate against

        Returns:
            A tuple of (is_valid, error_message)
        """
        try:
            import jsonschema

            jsonschema.validate(json_data, schema)
            return True, None
        except ImportError:
            # jsonschema not available, perform basic validation
            return Translation._basic_schema_validation(json_data, schema)
        except Exception as e:
            # Check if this is a jsonschema error, even if the import failed
            if "jsonschema" in str(e) and "ValidationError" in str(e):
                return False, str(e)
            # Fallback for other validation errors
            return False, f"Schema validation error: {e!s}"

    @staticmethod
    def _basic_schema_validation(
        json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Perform basic JSON schema validation without jsonschema library.

        This is a fallback validation that checks basic schema requirements.
        """
        try:
            # Check type
            schema_type = schema.get("type")
            if schema_type == "object" and not isinstance(json_data, dict):
                return False, f"Expected object, got {type(json_data).__name__}"
            elif schema_type == "array" and not isinstance(json_data, list):
                return False, f"Expected array, got {type(json_data).__name__}"
            elif schema_type == "string" and not isinstance(json_data, str):
                return False, f"Expected string, got {type(json_data).__name__}"
            elif schema_type == "number" and not isinstance(json_data, int | float):
                return False, f"Expected number, got {type(json_data).__name__}"
            elif schema_type == "integer" and not isinstance(json_data, int):
                return False, f"Expected integer, got {type(json_data).__name__}"
            elif schema_type == "boolean" and not isinstance(json_data, bool):
                return False, f"Expected boolean, got {type(json_data).__name__}"

            # Check required properties for objects
            if schema_type == "object" and isinstance(json_data, dict):
                required = schema.get("required", [])
                for prop in required:
                    if prop not in json_data:
                        return False, f"Missing required property: {prop}"

            return True, None
        except Exception as e:
            return False, f"Basic validation error: {e!s}"

    @staticmethod
    def _detect_image_mime_type(url: str) -> str:
        """Detect the MIME type for an image URL or data URI."""
        if url.startswith("data:"):
            header = url.split(",", 1)[0]
            header = header.split(";", 1)[0]
            if ":" in header:
                candidate = header.split(":", 1)[1]
                if candidate:
                    return candidate
            return "image/jpeg"

        clean_url = url.split("?", 1)[0].split("#", 1)[0]
        if "." in clean_url:
            extension = clean_url.rsplit(".", 1)[-1].lower()
            if extension:
                mime_type = mimetypes.types_map.get(f".{extension}")
                if mime_type and mime_type.startswith("image/"):
                    return mime_type
                if extension == "jpg":
                    return "image/jpeg"
        return "image/jpeg"

    @staticmethod
    def _process_gemini_image_part(part: Any) -> dict[str, Any] | None:
        """Convert a multimodal image part to Gemini format."""
        from src.core.domain.chat import MessageContentPartImage

        if not isinstance(part, MessageContentPartImage) or not part.image_url:
            return None

        url_str = str(part.image_url.url or "").strip()
        if not url_str:
            return None

        # Inline data URIs are allowed
        if url_str.startswith("data:"):
            mime_type = Translation._detect_image_mime_type(url_str)
            try:
                _, base64_data = url_str.split(",", 1)
            except ValueError:
                base64_data = ""
            return {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64_data,
                }
            }

        # For non-inline URIs, only allow http/https schemes. Reject file/ftp and local paths.
        try:
            from urllib.parse import urlparse

            scheme = (urlparse(url_str).scheme or "").lower()
        except Exception:
            scheme = ""

        allowed_schemes = {"http", "https"}

        if scheme not in allowed_schemes:
            # Also treat Windows/local file paths (no scheme or drive-letter scheme) as invalid
            return None

        mime_type = Translation._detect_image_mime_type(url_str)
        return {
            "file_data": {
                "mime_type": mime_type,
                "file_uri": url_str,
            }
        }

    @staticmethod
    def _normalize_usage_metadata(
        usage: dict[str, Any], source_format: str
    ) -> dict[str, Any]:
        """Normalize usage metadata from different API formats to a standard structure."""
        if source_format == "gemini":
            return {
                "prompt_tokens": usage.get("promptTokenCount", 0),
                "completion_tokens": usage.get("candidatesTokenCount", 0),
                "total_tokens": usage.get("totalTokenCount", 0),
            }
        elif source_format == "anthropic":
            return {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0)
                + usage.get("output_tokens", 0),
            }
        elif source_format in {"openai", "openai-responses"}:
            prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
            completion_tokens = usage.get(
                "completion_tokens", usage.get("output_tokens", 0)
            )
            total_tokens = usage.get("total_tokens")
            if total_tokens is None:
                total_tokens = prompt_tokens + completion_tokens

            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            }
        else:
            # Default normalization
            return {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

    @staticmethod
    def _map_gemini_finish_reason(finish_reason: str | None) -> str | None:
        """Map Gemini finish reasons to canonical values."""
        if finish_reason is None:
            return None

        normalized = str(finish_reason).lower()
        mapping = {
            "stop": "stop",
            "max_tokens": "length",
            "safety": "content_filter",
            "tool_calls": "tool_calls",
        }
        return mapping.get(normalized, "stop")

    @staticmethod
    def _normalize_stop_sequences(stop: Any) -> list[str] | None:
        """Normalize stop sequences to a consistent format."""
        if stop is None:
            return None

        if isinstance(stop, str):
            return [stop]

        if isinstance(stop, list):
            # Ensure all elements are strings
            return [str(s) for s in stop]

        # Convert other types to string
        return [str(stop)]

    @staticmethod
    def _normalize_tool_arguments(args: Any) -> str:
        """Normalize tool call arguments to a JSON string."""
        if args is None:
            return "{}"

        if isinstance(args, str):
            stripped = args.strip()
            if not stripped:
                return "{}"
            try:
                json.loads(stripped)
                return stripped
            except json.JSONDecodeError:
                # Attempt to parse Python-literal style dicts/lists safely
                try:
                    import ast

                    literal = ast.literal_eval(stripped)
                    # Only convert common JSON-compatible literal types
                    if (
                        isinstance(
                            literal, dict | list | tuple | str | int | float | bool
                        )
                        or literal is None
                    ):
                        return json.dumps(
                            literal if not isinstance(literal, tuple) else list(literal)
                        )
                except Exception:
                    pass
                # Safe fallback - keep raw content under a namespaced key to avoid corruption
                return json.dumps({"_raw": stripped})

        if isinstance(args, dict):
            return json.dumps(args)

        if isinstance(args, list | tuple):
            return json.dumps(list(args))

        try:
            return json.dumps(args)
        except TypeError:
            return json.dumps({"_raw": str(args)})

    @staticmethod
    def _process_gemini_function_call(function_call: dict[str, Any]) -> ToolCall:
        """Process a Gemini function call part into a ToolCall."""
        import uuid

        name = function_call.get("name", "")
        raw_args = function_call.get("args", function_call.get("arguments"))
        normalized_args = Translation._normalize_tool_arguments(raw_args)

        return ToolCall(
            id=f"call_{uuid.uuid4().hex[:12]}",
            type="function",
            function=FunctionCall(name=name, arguments=normalized_args),
        )

    @staticmethod
    def gemini_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate a Gemini request to a CanonicalChatRequest.
        """
        from src.core.domain.gemini_translation import (
            gemini_request_to_canonical_request,
        )

        return gemini_request_to_canonical_request(request)

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
        import time

        if not isinstance(response, dict):
            # Handle non-dict responses
            return CanonicalChatResponse(
                id=f"chatcmpl-anthropic-{int(time.time())}",
                object="chat.completion",
                created=int(time.time()),
                model="unknown",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=str(response)
                        ),
                        finish_reason="stop",
                    )
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

        # Extract choices
        choices = []
        if "content" in response:
            for idx, item in enumerate(response["content"]):
                if item.get("type") == "text":
                    choice = ChatCompletionChoice(
                        index=idx,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=item.get("text", "")
                        ),
                        finish_reason=response.get("stop_reason", "stop"),
                    )
                    choices.append(choice)

        # Extract usage
        usage = response.get("usage", {})
        normalized_usage = Translation._normalize_usage_metadata(usage, "anthropic")

        return CanonicalChatResponse(
            id=response.get("id", f"chatcmpl-anthropic-{int(time.time())}"),
            object="chat.completion",
            created=int(time.time()),
            model=response.get("model", "unknown"),
            choices=choices,
            usage=normalized_usage,
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
                                Translation._process_gemini_function_call(function_call)
                            )

                    content = "".join(text_parts)

                # Map finish reason
                finish_reason = Translation._map_gemini_finish_reason(
                    candidate.get("finishReason")
                )

                # Create choice
                choice = ChatCompletionChoice(
                    index=idx,
                    message=ChatCompletionChoiceMessage(
                        role="assistant",
                        content=content,
                        tool_calls=tool_calls,
                    ),
                    finish_reason=finish_reason,
                )
                choices.append(choice)

        # Extract usage metadata
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if isinstance(response, dict) and "usageMetadata" in response:
            usage_metadata = response["usageMetadata"]
            usage = Translation._normalize_usage_metadata(usage_metadata, "gemini")

        # If no choices were extracted, create a default one
        if not choices:
            choices = [
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(role="assistant", content=""),
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
    def gemini_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """
        Translate a Gemini streaming chunk to a canonical dictionary format.

        Args:
            chunk: The Gemini streaming chunk.

        Returns:
            A dictionary representing the canonical chunk format.
        """
        import time
        import uuid

        if not isinstance(chunk, dict):
            return {"error": "Invalid chunk format: expected a dictionary"}

        response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        model = "gemini-pro"  # Default model

        content_pieces: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        finish_reason = None

        if "candidates" in chunk:
            for candidate in chunk["candidates"]:
                if "content" in candidate and "parts" in candidate["content"]:
                    for part in candidate["content"]["parts"]:
                        if "text" in part:
                            content_pieces.append(part["text"])
                        elif "functionCall" in part:
                            try:
                                tool_calls.append(
                                    Translation._process_gemini_function_call(
                                        part["functionCall"]
                                    ).model_dump()
                                )
                            except Exception:
                                continue
                if "finishReason" in candidate:
                    finish_reason = Translation._map_gemini_finish_reason(
                        candidate["finishReason"]
                    )

        delta: dict[str, Any] = {"role": "assistant"}
        if content_pieces:
            delta["content"] = "".join(content_pieces)
        if tool_calls:
            delta["tool_calls"] = tool_calls

        return {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
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
        import time

        if not isinstance(response, dict):
            return CanonicalChatResponse(
                id=f"chatcmpl-openai-{int(time.time())}",
                object="chat.completion",
                created=int(time.time()),
                model="unknown",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=str(response)
                        ),
                        finish_reason="stop",
                    )
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
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
        normalized_usage = Translation._normalize_usage_metadata(usage, "openai")

        return CanonicalChatResponse(
            id=response.get("id", "chatcmpl-openai-unk"),
            object=response.get("object", "chat.completion"),
            created=response.get("created", int(__import__("time").time())),
            model=response.get("model", "unknown"),
            choices=choices,
            usage=normalized_usage,
        )

    @staticmethod
    def responses_to_domain_response(response: Any) -> CanonicalChatResponse:
        """Translate an OpenAI Responses API response to a canonical response."""
        import time

        if not isinstance(response, dict):
            return Translation.openai_to_domain_response(response)

        # If the backend already returned OpenAI-style choices, reuse that logic.
        if response.get("choices"):
            return Translation.openai_to_domain_response(response)

        output_items = response.get("output") or []
        choices: list[ChatCompletionChoice] = []

        for idx, item in enumerate(output_items):
            if not isinstance(item, dict):
                continue

            role = item.get("role", "assistant")
            content_parts = item.get("content")
            if not isinstance(content_parts, list):
                content_parts = []

            text_segments: list[str] = []
            tool_calls: list[ToolCall] = []

            for part in content_parts:
                if not isinstance(part, dict):
                    continue

                part_type = part.get("type")
                if part_type in {"output_text", "text", "input_text"}:
                    text_value = part.get("text") or part.get("value") or ""
                    if text_value:
                        text_segments.append(str(text_value))
                elif part_type == "tool_call":
                    function_payload = (
                        part.get("function") or part.get("function_call") or {}
                    )
                    normalized_args = Translation._normalize_tool_arguments(
                        function_payload.get("arguments")
                        or function_payload.get("args")
                        or function_payload.get("arguments_json")
                    )
                    tool_calls.append(
                        ToolCall(
                            id=part.get("id") or f"tool_call_{idx}_{len(tool_calls)}",
                            function=FunctionCall(
                                name=function_payload.get("name", ""),
                                arguments=normalized_args,
                            ),
                        )
                    )

            content_text = "\n".join(
                segment for segment in text_segments if segment
            ).strip()

            finish_reason = item.get("finish_reason") or item.get("status")
            if finish_reason == "completed":
                finish_reason = "stop"
            elif finish_reason == "incomplete":
                finish_reason = "length"
            elif finish_reason in {"in_progress", "generating"}:
                finish_reason = None
            elif finish_reason is None and (content_text or tool_calls):
                finish_reason = "stop"

            message = ChatCompletionChoiceMessage(
                role=role,
                content=content_text or None,
                tool_calls=tool_calls or None,
            )

            choices.append(
                ChatCompletionChoice(
                    index=idx,
                    message=message,
                    finish_reason=finish_reason,
                )
            )

        if not choices:
            # Fallback to OpenAI conversion to avoid returning an empty response
            return Translation.openai_to_domain_response(response)

        usage = response.get("usage") or {}
        normalized_usage = Translation._normalize_usage_metadata(
            usage, "openai-responses"
        )

        return CanonicalChatResponse(
            id=response.get("id", f"resp-{int(time.time())}"),
            object=response.get("object", "response"),
            created=response.get("created", int(time.time())),
            model=response.get("model", "unknown"),
            choices=choices,
            usage=normalized_usage,
            system_fingerprint=response.get("system_fingerprint"),
        )

    @staticmethod
    def openai_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """
        Translate an OpenAI streaming chunk to a canonical dictionary format.

        Args:
            chunk: The OpenAI streaming chunk.

        Returns:
            A dictionary representing the canonical chunk format.
        """
        import json
        import time
        import uuid

        if isinstance(chunk, bytes | bytearray):
            try:
                chunk = chunk.decode("utf-8")
            except Exception:
                return {"error": "Invalid chunk format: unable to decode bytes"}

        if isinstance(chunk, str):
            stripped_chunk = chunk.strip()

            if not stripped_chunk:
                return {"error": "Invalid chunk format: empty string"}

            if stripped_chunk.startswith(":"):
                # Comment/heartbeat lines (e.g., ": ping") should be ignored by emitting
                # an empty delta so downstream processors keep the stream alive.
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "unknown",
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": None},
                    ],
                }

            if stripped_chunk.startswith("data:"):
                stripped_chunk = stripped_chunk[5:].strip()

            if stripped_chunk == "[DONE]":
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "unknown",
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"},
                    ],
                }

            try:
                chunk = json.loads(stripped_chunk)
            except json.JSONDecodeError as exc:
                return {
                    "error": "Invalid chunk format: expected JSON after 'data:' prefix",
                    "details": {"message": str(exc)},
                }

        if not isinstance(chunk, dict):
            return {"error": "Invalid chunk format: expected a dictionary"}

        # Basic validation for essential keys
        if "id" not in chunk or "choices" not in chunk:
            return {"error": "Invalid chunk: missing 'id' or 'choices'"}

        # For simplicity, we'll return the chunk as a dictionary.
        # In a more complex scenario, you might map this to a Pydantic model.
        return dict(chunk)

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
    def _validate_request_parameters(request: CanonicalChatRequest) -> None:
        """Validate required parameters in a domain request."""
        if not request.model:
            raise ValueError("Model is required")

        if not request.messages:
            raise ValueError("Messages are required")

        # Validate message structure
        for message in request.messages:
            if not message.role:
                raise ValueError("Message role is required")

            # Validate content based on role
            if message.role != "system" and not message.content:
                raise ValueError(f"Content is required for {message.role} messages")

        # Validate tool parameters if present
        if request.tools:
            for tool in request.tools:
                if isinstance(tool, dict):
                    if "function" not in tool:
                        raise ValueError("Tool must have a function")
                    if "name" not in tool.get("function", {}):
                        raise ValueError("Tool function must have a name")

    @staticmethod
    def from_domain_to_gemini_request(request: CanonicalChatRequest) -> dict[str, Any]:
        """
        Translate a CanonicalChatRequest to a Gemini request.
        """

        Translation._validate_request_parameters(request)

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
            config["stopSequences"] = Translation._normalize_stop_sequences(
                request.stop
            )
        # Check for CLI override first (--thinking-budget flag)
        import os

        cli_thinking_budget = os.environ.get("THINKING_BUDGET")
        if cli_thinking_budget is not None:
            try:
                budget = int(cli_thinking_budget)
                config["thinkingConfig"] = {
                    "thinkingBudget": budget,
                    "includeThoughts": True,
                }
            except ValueError:
                pass  # Invalid value, ignore

        # Otherwise, use reasoning_effort if provided
        elif request.reasoning_effort is not None:
            # Gemini uses thinkingBudget (max reasoning tokens)
            # Map reasoning_effort levels to approximate token budgets
            # -1 = dynamic/unlimited (let model decide)
            # 0 = no thinking
            # positive int = max thinking tokens
            effort_to_budget = {
                "low": 512,
                "medium": 2048,
                "high": -1,  # Dynamic/unlimited
            }
            budget = effort_to_budget.get(request.reasoning_effort, -1)
            config["thinkingConfig"] = {
                "thinkingBudget": budget,
                "includeThoughts": True,  # Include reasoning in output
            }

        # Process messages with proper handling of multimodal content and tool calls
        contents: list[dict[str, Any]] = []

        for message in request.messages:
            # Map assistant role to 'model' for Gemini compatibility; keep others as-is
            gemini_role = "model" if message.role == "assistant" else message.role
            msg_dict = {"role": gemini_role}
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
                    if hasattr(part, "type") and part.type == "image_url":
                        processed_image = Translation._process_gemini_image_part(part)
                        if processed_image:
                            parts.append(processed_image)
                    elif hasattr(part, "type") and part.type == "text":
                        from src.core.domain.chat import MessageContentPartText

                        # Handle text part
                        if isinstance(part, MessageContentPartText) and hasattr(
                            part, "text"
                        ):
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

        result = {"contents": contents, "generationConfig": config}

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
                elif not isinstance(tool, dict):
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

        # Handle tool_choice for Gemini
        if request.tool_choice:
            mode = "AUTO"  # Default
            allowed_functions = None

            if isinstance(request.tool_choice, str):
                if request.tool_choice == "none":
                    mode = "NONE"
                elif request.tool_choice == "auto":
                    mode = "AUTO"
                elif request.tool_choice in ["any", "required"]:
                    mode = "ANY"
            elif (
                isinstance(request.tool_choice, dict)
                and request.tool_choice.get("type") == "function"
            ):
                function_spec = request.tool_choice.get("function", {})
                function_name = function_spec.get("name")
                if function_name:
                    mode = "ANY"
                    allowed_functions = [function_name]

            fcc: dict[str, Any] = {"mode": mode}
            if allowed_functions:
                fcc["allowedFunctionNames"] = allowed_functions
            result["toolConfig"] = {"functionCallingConfig": fcc}

        # Handle structured output for Responses API
        if request.extra_body and "response_format" in request.extra_body:
            response_format = request.extra_body["response_format"]
            if response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema = json_schema.get("schema", {})

                # For Gemini, add JSON mode and schema constraint to generation config
                generation_config = result["generationConfig"]
                if isinstance(generation_config, dict):
                    generation_config["responseMimeType"] = "application/json"
                    generation_config["responseSchema"] = schema

                # Add schema name and description as additional context if available
                schema_name = json_schema.get("name")
                schema_description = json_schema.get("description")
                if schema_name or schema_description:
                    # Add schema context to the last user message or create a system-like instruction
                    schema_context = "Generate a JSON response"
                    if schema_name:
                        schema_context += f" for '{schema_name}'"
                    if schema_description:
                        schema_context += f": {schema_description}"
                    schema_context += (
                        ". The response must conform to the provided JSON schema."
                    )

                    # Add this as context to help the model understand the structured output requirement
                    if (
                        contents
                        and isinstance(contents[-1], dict)
                        and contents[-1].get("role") == "user"
                    ):
                        # Append to the last user message
                        last_message = contents[-1]
                        if (
                            isinstance(last_message, dict)
                            and last_message.get("parts")
                            and isinstance(last_message["parts"], list)
                        ):
                            last_message["parts"].append(
                                {"text": f"\n\n{schema_context}"}
                            )
                    else:
                        # Add as a new user message
                        contents.append(
                            {"role": "user", "parts": [{"text": schema_context}]}
                        )

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
            payload["stop"] = Translation._normalize_stop_sequences(request.stop)
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

        # Handle structured output for Responses API
        if request.extra_body and "response_format" in request.extra_body:
            response_format = request.extra_body["response_format"]
            if response_format.get("type") == "json_schema":
                # For OpenAI, we can pass the response_format directly
                payload["response_format"] = response_format

        return payload

    @staticmethod
    def anthropic_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """
        Translate an Anthropic streaming chunk to a canonical dictionary format.

        Args:
            chunk: The Anthropic streaming chunk.

        Returns:
            A dictionary representing the canonical chunk format.
        """
        import time
        import uuid

        if not isinstance(chunk, dict):
            return {"error": "Invalid chunk format: expected a dictionary"}

        response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        model = "claude-3-opus-20240229"  # Default model

        content = ""
        finish_reason = None

        if chunk.get("type") == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                content = delta.get("text", "")

        return {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
        }

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
                    from src.core.domain.chat import (
                        MessageContentPartImage,
                        MessageContentPartText,
                    )

                    if isinstance(part, MessageContentPartImage):
                        # Handle image part
                        if part.image_url:
                            url_str = str(part.image_url.url)
                            # Only include data URLs; skip http/https URLs
                            if url_str.startswith("data:"):
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
                    elif isinstance(part, MessageContentPartText):
                        # Handle text part
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
                elif not isinstance(tool, dict):
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
            payload["stop_sequences"] = Translation._normalize_stop_sequences(
                request.stop
            )

        # Add metadata if present in extra_body
        if request.extra_body and isinstance(request.extra_body, dict):
            metadata = request.extra_body.get("metadata")
            if metadata:
                payload["metadata"] = metadata

            # Handle structured output for Responses API
            response_format = request.extra_body.get("response_format")
            if response_format and response_format.get("type") == "json_schema":
                json_schema = response_format.get("json_schema", {})
                schema = json_schema.get("schema", {})
                schema_name = json_schema.get("name")
                schema_description = json_schema.get("description")
                strict = json_schema.get("strict", True)

                # For Anthropic, add comprehensive JSON schema instruction to system message
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

                schema_instruction += "\n\nRespond only with the JSON object, no additional text or formatting."

                if payload.get("system"):
                    if isinstance(payload["system"], str):
                        payload["system"] += schema_instruction
                    else:
                        # If not a string, we cannot append. Replace it.
                        payload["system"] = schema_instruction
                else:
                    payload["system"] = (
                        f"You are a helpful assistant.{schema_instruction}"
                    )

        return payload

    @staticmethod
    def code_assist_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate a Code Assist API request to a CanonicalChatRequest.

        The Code Assist API uses the same format as OpenAI for the core request,
        but with additional project field and different endpoint.
        """
        # Code Assist API request format is essentially the same as OpenAI
        # but may include a "project" field
        if isinstance(request, dict):
            # Remove Code Assist specific fields and treat as OpenAI format
            cleaned_request = {k: v for k, v in request.items() if k != "project"}
            return Translation.openai_to_domain_request(cleaned_request)
        else:
            # Handle object format by extracting fields
            return Translation.openai_to_domain_request(request)

    @staticmethod
    def code_assist_to_domain_response(response: Any) -> CanonicalChatResponse:
        """
        Translate a Code Assist API response to a CanonicalChatResponse.

        The Code Assist API wraps the response in a "response" object and uses
        different structure than standard Gemini API.
        """
        import time

        if not isinstance(response, dict):
            # Handle non-dict responses
            return CanonicalChatResponse(
                id=f"chatcmpl-code-assist-{int(time.time())}",
                object="chat.completion",
                created=int(time.time()),
                model="unknown",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=str(response)
                        ),
                        finish_reason="stop",
                    )
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )

        # Extract from Code Assist response wrapper
        response_wrapper = response.get("response", {})
        candidates = response_wrapper.get("candidates", [])
        generated_text = ""

        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            content = candidate.get("content", {})
            parts = content.get("parts", [])

            if parts and len(parts) > 0:
                generated_text = parts[0].get("text", "")

        # Create canonical response
        return CanonicalChatResponse(
            id=f"chatcmpl-code-assist-{int(time.time())}",
            object="chat.completion",
            created=int(time.time()),
            model=response.get("model", "code-assist-model"),
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(
                        role="assistant", content=generated_text
                    ),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        )

    @staticmethod
    def code_assist_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """
        Translate a Code Assist API streaming chunk to a canonical dictionary format.

        Code Assist API uses Server-Sent Events (SSE) format with "data: " prefix.
        """
        import time
        import uuid

        if chunk is None:
            # Handle end of stream
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "code-assist-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }

        if not isinstance(chunk, dict):
            return {"error": "Invalid chunk format: expected a dictionary"}

        response_id = f"chatcmpl-{uuid.uuid4().hex[:16]}"
        created = int(time.time())
        model = "code-assist-model"

        content = ""
        finish_reason = None

        # Extract from Code Assist response wrapper
        response_wrapper = chunk.get("response", {})
        candidates = response_wrapper.get("candidates", [])

        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            content_obj = candidate.get("content", {})
            parts = content_obj.get("parts", [])

            if parts and len(parts) > 0:
                content = parts[0].get("text", "")

            if "finishReason" in candidate:
                finish_reason = candidate["finishReason"]

        return {
            "id": response_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
        }

    @staticmethod
    def raw_text_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate a raw text request to a CanonicalChatRequest.

        Raw text format is typically used for simple text processing where
        the input is just a plain text string.
        """

        if isinstance(request, str):
            # Create a simple request with the text as user message
            from src.core.domain.chat import ChatMessage

            return CanonicalChatRequest(
                model="text-model",
                messages=[ChatMessage(role="user", content=request)],
            )
        elif isinstance(request, dict):
            # If it's already a dict, treat it as OpenAI format
            return Translation.openai_to_domain_request(request)
        else:
            # Handle object format
            return Translation.openai_to_domain_request(request)

    @staticmethod
    def raw_text_to_domain_response(response: Any) -> CanonicalChatResponse:
        """
        Translate a raw text response to a CanonicalChatResponse.

        Raw text format is typically used for simple text responses.
        """
        import time

        if isinstance(response, str):
            return CanonicalChatResponse(
                id=f"chatcmpl-raw-text-{int(time.time())}",
                object="chat.completion",
                created=int(time.time()),
                model="text-model",
                choices=[
                    ChatCompletionChoice(
                        index=0,
                        message=ChatCompletionChoiceMessage(
                            role="assistant", content=response
                        ),
                        finish_reason="stop",
                    )
                ],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            )
        elif isinstance(response, dict):
            # If it's already a dict, treat it as OpenAI format
            return Translation.openai_to_domain_response(response)
        else:
            # Handle object format
            return Translation.openai_to_domain_response(response)

    @staticmethod
    def raw_text_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """
        Translate a raw text stream chunk to a canonical dictionary format.

        Raw text chunks are typically plain text strings.
        """
        import time
        import uuid

        if chunk is None:
            # Handle end of stream
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "text-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            }

        if isinstance(chunk, str):
            # Raw text chunk
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "text-model",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"role": "assistant", "content": chunk},
                        "finish_reason": None,
                    }
                ],
            }
        elif isinstance(chunk, dict):
            # Check if it's a wrapped text dict like {"text": "content"}
            if "text" in chunk and isinstance(chunk["text"], str):
                return {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:16]}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": "text-model",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": chunk["text"]},
                            "finish_reason": None,
                        }
                    ],
                }
            else:
                # If it's already a dict, treat it as OpenAI format
                return Translation.openai_to_domain_stream_chunk(chunk)
        else:
            return {"error": "Invalid raw text chunk format"}

    @staticmethod
    def responses_to_domain_request(request: Any) -> CanonicalChatRequest:
        """
        Translate a Responses API request to a CanonicalChatRequest.

        The Responses API request includes structured output requirements via response_format.
        This method converts the request to the internal domain format while preserving
        the JSON schema information for later use by backends.
        """
        from src.core.domain.responses_api import ResponsesRequest

        # Handle both dict and object formats
        if isinstance(request, dict):
            # Convert dict to ResponsesRequest for validation
            responses_request = ResponsesRequest(**request)
        elif hasattr(request, "model_dump"):
            # Already a Pydantic model
            responses_request = (
                request
                if isinstance(request, ResponsesRequest)
                else ResponsesRequest(**request.model_dump())
            )
        else:
            # Try to extract attributes
            responses_request = ResponsesRequest(
                model=request.model,
                messages=getattr(request, "messages", []),
                response_format=request.response_format,
                max_tokens=getattr(request, "max_tokens", None),
                temperature=getattr(request, "temperature", None),
                top_p=getattr(request, "top_p", None),
                n=getattr(request, "n", None),
                stream=getattr(request, "stream", None),
                stop=getattr(request, "stop", None),
                presence_penalty=getattr(request, "presence_penalty", None),
                frequency_penalty=getattr(request, "frequency_penalty", None),
                logit_bias=getattr(request, "logit_bias", None),
                user=getattr(request, "user", None),
                seed=getattr(request, "seed", None),
                session_id=getattr(request, "session_id", None),
                agent=getattr(request, "agent", None),
                extra_body=getattr(request, "extra_body", None),
            )

        # Prepare extra_body with response format
        extra_body = responses_request.extra_body or {}
        extra_body["response_format"] = responses_request.response_format.model_dump()

        # Convert to CanonicalChatRequest
        canonical_request = CanonicalChatRequest(
            model=responses_request.model,
            messages=responses_request.messages,
            temperature=responses_request.temperature,
            top_p=responses_request.top_p,
            max_tokens=responses_request.max_tokens,
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
        )

        return canonical_request

    @staticmethod
    def from_domain_to_responses_response(response: ChatResponse) -> dict[str, Any]:
        """
        Translate a domain ChatResponse to a Responses API response format.

        This method converts the internal domain response to the OpenAI Responses API format,
        including parsing structured outputs and handling JSON schema validation results.
        """
        import json
        import time

        # Convert choices to Responses API format
        choices = []
        for choice in response.choices:
            if choice.message:
                # Try to parse the content as JSON for structured output
                parsed_content = None
                content = choice.message.content or ""

                # Clean up content for JSON parsing
                cleaned_content = content.strip()

                # Handle cases where the model might wrap JSON in markdown code blocks
                if cleaned_content.startswith("```json") and cleaned_content.endswith(
                    "```"
                ):
                    cleaned_content = cleaned_content[7:-3].strip()
                elif cleaned_content.startswith("```") and cleaned_content.endswith(
                    "```"
                ):
                    cleaned_content = cleaned_content[3:-3].strip()

                # Attempt to parse JSON content
                if cleaned_content:
                    try:
                        parsed_content = json.loads(cleaned_content)
                        # If parsing succeeded, use the cleaned content as the actual content
                        content = cleaned_content
                    except json.JSONDecodeError:
                        # Content is not valid JSON, leave parsed as None
                        # Try to extract JSON from the content if it contains other text
                        try:
                            # Look for JSON-like patterns in the content
                            import re

                            json_pattern = r"\{.*\}"
                            json_match = re.search(
                                json_pattern, cleaned_content, re.DOTALL
                            )
                            if json_match:
                                potential_json = json_match.group(0)
                                parsed_content = json.loads(potential_json)
                                content = potential_json
                        except (json.JSONDecodeError, AttributeError):
                            # Still not valid JSON, leave parsed as None
                            pass

                response_choice = {
                    "index": choice.index,
                    "message": {
                        "role": choice.message.role,
                        "content": content,
                        "parsed": parsed_content,
                    },
                    "finish_reason": choice.finish_reason or "stop",
                }
                choices.append(response_choice)

        # Build the Responses API response
        responses_response = {
            "id": response.id,
            "object": "response",
            "created": response.created or int(time.time()),
            "model": response.model,
            "choices": choices,
        }

        # Add usage information if available
        if response.usage:
            responses_response["usage"] = response.usage

        # Add system fingerprint if available
        if hasattr(response, "system_fingerprint") and response.system_fingerprint:
            responses_response["system_fingerprint"] = response.system_fingerprint

        return responses_response

    @staticmethod
    def from_domain_to_responses_request(
        request: CanonicalChatRequest,
    ) -> dict[str, Any]:
        """
        Translate a CanonicalChatRequest to an OpenAI Responses API request format.

        This method converts the internal domain request to the OpenAI Responses API format,
        extracting the response_format from extra_body and structuring it properly.
        """
        # Start with basic OpenAI request format
        payload = Translation.from_domain_to_openai_request(request)

        # Extract and restructure response_format from extra_body
        if request.extra_body and "response_format" in request.extra_body:
            response_format = request.extra_body["response_format"]

            # Ensure the response_format is properly structured for Responses API
            if isinstance(response_format, dict):
                payload["response_format"] = response_format
            else:
                # Handle case where response_format might be a Pydantic model
                if hasattr(response_format, "model_dump"):
                    payload["response_format"] = response_format.model_dump()
                else:
                    payload["response_format"] = response_format

            # Remove response_format from extra_body to avoid duplication
            extra_body_copy = dict(request.extra_body)
            del extra_body_copy["response_format"]

            # Add any remaining extra_body parameters
            if extra_body_copy:
                payload.update(extra_body_copy)

        return payload

    @staticmethod
    def enhance_structured_output_response(
        response: ChatResponse,
        original_request_extra_body: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """
        Enhance a ChatResponse with structured output validation and repair.

        This method validates the response against the original JSON schema
        and attempts repair if validation fails.

        Args:
            response: The original ChatResponse
            original_request_extra_body: The extra_body from the original request containing schema info

        Returns:
            Enhanced ChatResponse with validated/repaired structured output
        """
        if not original_request_extra_body:
            return response

        response_format = original_request_extra_body.get("response_format")
        if not response_format or response_format.get("type") != "json_schema":
            return response

        json_schema_info = response_format.get("json_schema", {})
        schema = json_schema_info.get("schema", {})

        if not schema:
            return response

        # Process each choice
        enhanced_choices = []
        for choice in response.choices:
            if not choice.message or not choice.message.content:
                enhanced_choices.append(choice)
                continue

            content = choice.message.content.strip()

            # Try to parse and validate the JSON
            try:
                parsed_json = json.loads(content)

                # Validate against schema
                is_valid, error_msg = Translation.validate_json_against_schema(
                    parsed_json, schema
                )

                if is_valid:
                    # Content is valid, keep as is
                    enhanced_choices.append(choice)
                else:
                    # Try to repair the JSON
                    repaired_json = Translation._attempt_json_repair(
                        parsed_json, schema, error_msg
                    )
                    if repaired_json is not None:
                        # Use repaired JSON
                        repaired_content = json.dumps(repaired_json, indent=2)
                        enhanced_message = ChatCompletionChoiceMessage(
                            role=choice.message.role,
                            content=repaired_content,
                            tool_calls=choice.message.tool_calls,
                        )
                        enhanced_choice = ChatCompletionChoice(
                            index=choice.index,
                            message=enhanced_message,
                            finish_reason=choice.finish_reason,
                        )
                        enhanced_choices.append(enhanced_choice)
                    else:
                        # Repair failed, keep original
                        enhanced_choices.append(choice)

            except json.JSONDecodeError:
                # Not valid JSON, try to extract and repair
                extracted_and_repaired_content: str | None = (
                    Translation._extract_and_repair_json(content, schema)
                )
                if extracted_and_repaired_content is not None:
                    enhanced_message = ChatCompletionChoiceMessage(
                        role=choice.message.role,
                        content=extracted_and_repaired_content,
                        tool_calls=choice.message.tool_calls,
                    )
                    enhanced_choice = ChatCompletionChoice(
                        index=choice.index,
                        message=enhanced_message,
                        finish_reason=choice.finish_reason,
                    )
                    enhanced_choices.append(enhanced_choice)
                else:
                    # Repair failed, keep original
                    enhanced_choices.append(choice)

        # Create enhanced response
        enhanced_response = CanonicalChatResponse(
            id=response.id,
            object=response.object,
            created=response.created,
            model=response.model,
            choices=enhanced_choices,
            usage=response.usage,
            system_fingerprint=getattr(response, "system_fingerprint", None),
        )

        return enhanced_response

    @staticmethod
    def _attempt_json_repair(
        json_data: dict[str, Any], schema: dict[str, Any], error_msg: str | None
    ) -> dict[str, Any] | None:
        """
        Attempt to repair JSON data to conform to schema.

        This is a basic repair mechanism that handles common issues.
        """
        try:
            repaired = dict(json_data)

            # Add missing required properties
            if schema.get("type") == "object":
                required = schema.get("required", [])
                properties = schema.get("properties", {})

                for prop in required:
                    if prop not in repaired:
                        # Add default value based on property type
                        prop_schema = properties.get(prop, {})
                        prop_type = prop_schema.get("type", "string")

                        if prop_type == "string":
                            repaired[prop] = ""
                        elif prop_type == "number":
                            repaired[prop] = 0.0
                        elif prop_type == "integer":
                            repaired[prop] = 0
                        elif prop_type == "boolean":
                            repaired[prop] = False
                        elif prop_type == "array":
                            repaired[prop] = []
                        elif prop_type == "object":
                            repaired[prop] = {}
                        else:
                            repaired[prop] = None

            # Validate the repaired JSON
            is_valid, _ = Translation.validate_json_against_schema(repaired, schema)
            return repaired if is_valid else None

        except Exception:
            return None

    @staticmethod
    def _extract_and_repair_json(content: str, schema: dict[str, Any]) -> str | None:
        """
        Extract JSON from content and attempt repair.
        """
        try:
            import re

            # Try to find JSON-like patterns
            json_patterns = [
                r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",  # Simple nested objects
                r"\{.*\}",  # Any content between braces
            ]

            for pattern in json_patterns:
                matches = re.findall(pattern, content, re.DOTALL)
                for match in matches:
                    try:
                        parsed = json.loads(match)
                        if isinstance(parsed, dict):
                            # Try to repair this JSON
                            repaired = Translation._attempt_json_repair(
                                parsed, schema, None
                            )
                            if repaired is not None:
                                return json.dumps(repaired, indent=2)
                    except json.JSONDecodeError:
                        continue

            return None
        except Exception:
            return None
