from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


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
    def _normalize_responses_input_to_messages(
        input_payload: Any,
    ) -> list[dict[str, Any]]:
        """Coerce OpenAI Responses API input payloads into chat messages."""

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

                content = Translation._normalize_responses_content(entry.get("content"))
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

                return message

            # Fallback: convert to string representation
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

        # Unknown type - coerce to a single user message
        return [{"role": "user", "content": str(input_payload)}]

    @staticmethod
    def _normalize_responses_content(content: Any) -> Any:
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
            normalized_parts = Translation._normalize_responses_content_part(content)
            if not normalized_parts:
                return None
            if len(normalized_parts) == 1 and normalized_parts[0].get("type") == "text":
                return normalized_parts[0]["text"]
            return normalized_parts

        if isinstance(content, list | tuple):
            collected_parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, dict):
                    collected_parts.extend(
                        Translation._normalize_responses_content_part(part)
                    )
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

    @staticmethod
    def _normalize_responses_content_part(part: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalize a single Responses API content part."""

        part_type = str(part.get("type") or "").lower()
        normalized_parts: list[dict[str, Any]] = []

        if part_type in {"text", "input_text", "output_text"}:
            text_value = part.get("text")
            if text_value is None:
                text_value = part.get("value")
            normalized_parts.append(
                {"type": "text", "text": Translation._safe_string(text_value)}
            )
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
                normalized_parts.append(
                    {"type": "image_url", "image_url": image_payload}
                )
        elif part_type == "tool_call":
            # Tool call parts are handled elsewhere in the pipeline; ignore here.
            return []
        else:
            # Preserve already-normalized structures (e.g., function calls) as-is
            normalized_parts.append(part)

        return [p for p in normalized_parts if p]

    @staticmethod
    def _safe_string(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, bytes | bytearray):
            return value.decode("utf-8", "ignore")
        return str(value)

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

            # First, try to load it as-is. It might be a valid JSON string.
            try:
                json.loads(stripped)
                return stripped
            except json.JSONDecodeError:
                # If it fails, it might be a string using single quotes.
                # We will try to fix it, but only if it doesn't create an invalid JSON.
                pass

            try:
                # Attempt to replace single quotes with double quotes for JSON compatibility.
                # This is a common issue with LLM-generated JSON in string format.
                # However, we must be careful not to corrupt strings that contain single quotes.
                fixed_string = stripped.replace("'", '"')
                json.loads(fixed_string)
                return fixed_string
            except (json.JSONDecodeError, TypeError):
                # If replacement fails, it's likely not a simple quote issue.
                # This can happen if the string contains legitimate single quotes.
                # Return empty object instead of _raw format to maintain tool calling contract.
                return "{}"

        if isinstance(args, dict):
            try:
                return json.dumps(args)
            except TypeError:
                # Handle dicts with non-serializable values
                sanitized_dict = Translation._sanitize_dict_for_json(args)
                return json.dumps(sanitized_dict)

        if isinstance(args, list | tuple):
            try:
                return json.dumps(list(args))
            except TypeError:
                # Handle lists with non-serializable items
                sanitized_list = Translation._sanitize_list_for_json(list(args))
                return json.dumps(sanitized_list)

        # For primitive types that should be JSON serializable
        if isinstance(args, int | float | bool):
            return json.dumps(args)

        # For non-serializable objects, return empty object instead of _raw format
        # This maintains the tool calling contract while preventing failures
        return "{}"

    @staticmethod
    def _sanitize_dict_for_json(data: dict[str, Any]) -> dict[str, Any]:
        """Sanitize a dictionary by removing or converting non-JSON-serializable values."""
        sanitized = {}
        for key, value in data.items():
            try:
                # Test if the value is JSON serializable
                json.dumps(value)
                sanitized[key] = value
            except TypeError:
                # Handle non-serializable values
                if isinstance(value, dict):
                    sanitized[key] = Translation._sanitize_dict_for_json(value)
                elif isinstance(value, list | tuple):
                    sanitized[key] = Translation._sanitize_list_for_json(list(value))
                elif isinstance(value, str | int | float | bool) or value is None:
                    sanitized[key] = value
                else:
                    # For complex objects, skip them to maintain valid tool arguments
                    continue
        return sanitized

    @staticmethod
    def _sanitize_list_for_json(data: list[Any]) -> list[Any]:
        """Sanitize a list by removing or converting non-JSON-serializable items."""
        sanitized = []
        for item in data:
            try:
                # Test if the item is JSON serializable
                json.dumps(item)
                sanitized.append(item)
            except TypeError:
                # Handle non-serializable items
                if isinstance(item, dict):
                    sanitized.append(Translation._sanitize_dict_for_json(item))
                elif isinstance(item, list | tuple):
                    sanitized.append(Translation._sanitize_list_for_json(list(item)))
                elif isinstance(item, str | int | float | bool) or item is None:
                    sanitized.append(item)
                else:
                    # For complex objects, skip them to maintain valid tool arguments
                    continue
        return sanitized

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
        # Use the helper method to safely access request parameters
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
        if (
            normalized_stop is None or normalized_stop == [] or normalized_stop == ""
        ) and stop_sequences not in (None, [], ""):
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
            presence_penalty=Translation._get_request_param(
                request, "presence_penalty"
            ),
            frequency_penalty=Translation._get_request_param(
                request, "frequency_penalty"
            ),
            logit_bias=Translation._get_request_param(request, "logit_bias"),
            user=Translation._get_request_param(request, "user"),
            reasoning_effort=Translation._get_request_param(
                request, "reasoning_effort"
            ),
            seed=Translation._get_request_param(request, "seed"),
            tools=Translation._get_request_param(request, "tools"),
            tool_choice=Translation._get_request_param(request, "tool_choice"),
            extra_body=Translation._get_request_param(request, "extra_body"),
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
            raw_tool_calls = msg.get("tool_calls")
            if isinstance(raw_tool_calls, list):
                # Validate each tool call in the list before including it
                validated_tool_calls = []
                for tc in raw_tool_calls:
                    # Convert dict to ToolCall if necessary
                    if isinstance(tc, dict):
                        # Create a ToolCall object from the dict
                        # Assuming the dict has the necessary structure for ToolCall
                        # We'll need to import ToolCall if not already available
                        # For now, we'll use a simple approach
                        try:
                            # Create ToolCall from dict, assuming proper structure
                            tool_call_obj = ToolCall(**tc)
                            validated_tool_calls.append(tool_call_obj)
                        except (TypeError, ValueError):
                            # If conversion fails, skip this tool call
                            pass
                    elif isinstance(tc, ToolCall):
                        validated_tool_calls.append(tc)
                    else:
                        # Log or handle invalid tool call
                        # For now, we'll skip invalid ones
                        pass
                tool_calls = validated_tool_calls if validated_tool_calls else None

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
            # Fallback to output_text aggregation used by the Responses API when
            # the structured output array is empty. This happens when the
            # backend only returns plain text without additional metadata.
            output_text = response.get("output_text")
            fallback_text_segments: list[str] = []
            if isinstance(output_text, list):
                fallback_text_segments = [
                    str(segment) for segment in output_text if segment
                ]
            elif isinstance(output_text, str) and output_text:
                fallback_text_segments = [output_text]

            if fallback_text_segments:
                aggregated_text = "".join(fallback_text_segments)
                status = response.get("status")
                fallback_finish_reason: str | None
                if status == "completed":
                    fallback_finish_reason = "stop"
                elif status == "incomplete":
                    fallback_finish_reason = "length"
                elif status in {"in_progress", "generating"}:
                    fallback_finish_reason = None
                else:
                    fallback_finish_reason = "stop" if aggregated_text else None

                message = ChatCompletionChoiceMessage(
                    role="assistant",
                    content=aggregated_text,
                    tool_calls=None,
                )

                choices.append(
                    ChatCompletionChoice(
                        index=0,
                        message=message,
                        finish_reason=fallback_finish_reason,
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
    def responses_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        """Translate an OpenAI Responses streaming chunk to canonical format."""
        import json
        import time

        if isinstance(chunk, bytes | bytearray):
            try:
                chunk = chunk.decode("utf-8")
            except UnicodeDecodeError:
                return {
                    "error": "Invalid chunk format: unable to decode bytes",
                }

        if isinstance(chunk, str):
            stripped_chunk = chunk.strip()

            if not stripped_chunk:
                return {"error": "Invalid chunk format: empty string"}

            if stripped_chunk.startswith(":"):
                return {
                    "id": f"resp-{int(time.time())}",
                    "object": "response.chunk",
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
                    "id": f"resp-{int(time.time())}",
                    "object": "response.chunk",
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

        chunk_id = chunk.get("id", f"resp-{int(time.time())}")
        created = chunk.get("created", int(time.time()))
        model = chunk.get("model", "unknown")
        object_type = chunk.get("object", "response.chunk")
        choices = chunk.get("choices") or []

        if not isinstance(choices, list) or not choices:
            choices = [
                {"index": 0, "delta": {}, "finish_reason": None},
            ]

        primary_choice = choices[0] or {}
        finish_reason = primary_choice.get("finish_reason")
        delta = primary_choice.get("delta") or {}

        if not isinstance(delta, dict):
            delta = {"content": str(delta)}

        content_value = delta.get("content")
        if isinstance(content_value, list):
            text_parts: list[str] = []
            for part in content_value:
                if not isinstance(part, dict):
                    continue
                part_type = part.get("type")
                if part_type in {"output_text", "text", "input_text"}:
                    text_value = part.get("text") or part.get("value") or ""
                    if text_value:
                        text_parts.append(str(text_value))
            delta["content"] = "".join(text_parts)
        elif isinstance(content_value, dict):
            delta["content"] = json.dumps(content_value)
        elif content_value is None:
            delta.pop("content", None)
        else:
            delta["content"] = str(content_value)

        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            normalized_tool_calls: list[dict[str, Any]] = []
            for tool_call in tool_calls:
                if isinstance(tool_call, dict):
                    call_data = dict(tool_call)
                else:
                    function = getattr(tool_call, "function", None)
                    call_data = {
                        "id": getattr(tool_call, "id", ""),
                        "type": getattr(tool_call, "type", "function"),
                        "function": {
                            "name": getattr(function, "name", ""),
                            "arguments": getattr(function, "arguments", "{}"),
                        },
                    }

                function_payload = call_data.get("function") or {}
                if isinstance(function_payload, dict):
                    arguments = function_payload.get("arguments")
                    if isinstance(arguments, dict | list):
                        function_payload["arguments"] = json.dumps(arguments)
                    elif arguments is None:
                        function_payload["arguments"] = "{}"
                    else:
                        function_payload["arguments"] = str(arguments)

                normalized_tool_calls.append(call_data)

            if normalized_tool_calls:
                delta["tool_calls"] = normalized_tool_calls
            else:
                delta.pop("tool_calls", None)

        return {
            "id": chunk_id,
            "object": object_type,
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": primary_choice.get("index", 0),
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

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

            # Allow assistant messages that carry only tool_calls (no textual content)
            if message.role != "system":
                has_text = bool(message.content)
                has_tool_calls = bool(getattr(message, "tool_calls", None))
                if not has_text and not (
                    message.role == "assistant" and has_tool_calls
                ):
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
            budget = effort_to_budget.get(request.reasoning_effort.lower(), -1)
            config["thinkingConfig"] = {
                "thinkingBudget": budget,
                "includeThoughts": True,  # Include reasoning in output
            }

        # Process messages with proper handling of multimodal content and tool calls
        contents: list[dict[str, Any]] = []
        # Track tool_call id -> function name to map tool responses
        tool_name_by_id: dict[str, str] = {}

        for message in request.messages:
            # Map assistant role to 'model' for Gemini compatibility; keep others as-is
            if message.role == "assistant":
                gemini_role = "model"
            elif message.role == "tool":
                # Gemini expects function responses from the "user" role
                gemini_role = "user"
            else:
                gemini_role = message.role
            msg_dict: dict[str, Any] = {"role": gemini_role}
            parts: list[dict[str, Any]] = []

            # Add assistant tool calls as functionCall parts
            if message.role == "assistant" and getattr(message, "tool_calls", None):
                try:
                    for tc in message.tool_calls or []:
                        tc_dict = tc if isinstance(tc, dict) else tc.model_dump()
                        fn = (tc_dict.get("function") or {}).get("name", "")
                        args_raw = (tc_dict.get("function") or {}).get("arguments", "")
                        # Remember mapping for subsequent tool responses
                        if "id" in tc_dict:
                            tool_name_by_id[tc_dict["id"]] = fn
                        # Parse arguments as JSON when possible
                        import json as _json

                        try:
                            args_val = (
                                _json.loads(args_raw)
                                if isinstance(args_raw, str)
                                else args_raw
                            )
                        except Exception:
                            args_val = args_raw
                        parts.append({"functionCall": {"name": fn, "args": args_val}})
                except Exception:
                    # Best-effort; continue even if a tool call cannot be parsed
                    pass

            # Handle content which could be string, list of parts, or None
            if isinstance(message.content, str):
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

            # Map tool role messages to functionResponse parts
            if message.role == "tool":
                # Try to map tool_call_id back to the function name
                name = tool_name_by_id.get(getattr(message, "tool_call_id", ""), "")
                resp_obj: dict[str, Any]
                val = message.content
                # Try to parse JSON result if provided
                if isinstance(val, str):
                    import json as _json

                    try:
                        resp_obj = _json.loads(val)
                    except Exception:
                        resp_obj = {"text": val}
                elif isinstance(val, dict):
                    resp_obj = val
                else:
                    resp_obj = {"text": str(val)}

                parts.append({"functionResponse": {"name": name, "response": resp_obj}})

            # Add parts to message
            msg_dict["parts"] = parts  # type: ignore

            # Only add non-empty messages
            if parts:
                contents.append(msg_dict)

        result = {"contents": contents, "generationConfig": config}

        # Add tools if present
        if request.tools:
            # Gemini Code Assist only allows multiple tools when they are all
            # search tools. For function calling, we must group ALL functions
            # into a SINGLE tool entry with a combined function_declarations list.
            function_declarations: list[dict[str, Any]] = []

            for tool in request.tools:
                # Accept dict-like or model-like entries
                tool_dict: dict[str, Any]
                if isinstance(tool, dict):
                    tool_dict = tool
                else:
                    try:
                        tool_dict = tool.model_dump()  # type: ignore[attr-defined]
                    except Exception:
                        tool_dict = {}
                function = (
                    tool_dict.get("function") if isinstance(tool_dict, dict) else None
                )
                if not function:
                    # Skip non-function tools for now (unsupported/mixed types)
                    continue

                params = Translation._sanitize_gemini_parameters(
                    function.get("parameters", {})
                )
                function_declarations.append(
                    {
                        "name": function.get("name", ""),
                        "description": function.get("description", ""),
                        "parameters": params,
                    }
                )

            if function_declarations:
                result["tools"] = [{"function_declarations": function_declarations}]

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
    def _sanitize_gemini_parameters(schema: dict[str, Any]) -> dict[str, Any]:
        """Sanitize OpenAI tool JSON schema for Gemini Code Assist function_declarations.

        The Code Assist API rejects certain JSON Schema keywords (e.g., "$schema",
        and sometimes draft-specific fields like "exclusiveMinimum"). This method
        removes unsupported keywords while preserving the core shape (type,
        properties, required, items, enum, etc.).

        Args:
            schema: Original JSON schema dict from OpenAI tool definition

        Returns:
            A sanitized schema dict suitable for Gemini Code Assist.
        """
        if not isinstance(schema, dict):
            return {}

        blacklist = {
            "$schema",
            "$id",
            "$comment",
            "exclusiveMinimum",
            "exclusiveMaximum",
        }

        def _clean(obj: Any) -> Any:
            if isinstance(obj, dict):
                cleaned: dict[str, Any] = {}
                for k, v in obj.items():
                    if k in blacklist:
                        continue
                    cleaned[k] = _clean(v)
                return cleaned
            if isinstance(obj, list):
                return [_clean(x) for x in obj]
            return obj

        cleaned = _clean(schema)
        return cleaned if isinstance(cleaned, dict) else {}

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
            content = candidate.get("content") or {}
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
        tool_calls: list[dict[str, Any]] | None = None

        # Extract from Code Assist response wrapper
        response_wrapper = chunk.get("response", {})
        candidates = response_wrapper.get("candidates", [])

        if candidates and len(candidates) > 0:
            candidate = candidates[0]
            content_obj = candidate.get("content") or {}
            parts = content_obj.get("parts", [])

            if parts and len(parts) > 0:
                # Collect text and function calls
                text_parts: list[str] = []
                for part in parts:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part.get("text", ""))
                    elif isinstance(part, dict) and "functionCall" in part:
                        try:
                            if tool_calls is None:
                                tool_calls = []
                            tool_calls.append(
                                Translation._process_gemini_function_call(
                                    part["functionCall"]
                                ).model_dump()
                            )
                        except Exception:
                            # Ignore malformed functionCall parts
                            continue
                content = "".join(text_parts)

            if "finishReason" in candidate:
                finish_reason = candidate["finishReason"]

        delta: dict[str, Any] = {"role": "assistant"}
        if tool_calls:
            delta["tool_calls"] = tool_calls
            # Enforce OpenAI semantics: when tool_calls are present, do not include content
            delta.pop("content", None)
            # Force finish_reason to tool_calls to signal clients to execute tools
            finish_reason = "tool_calls"
        elif content:
            delta["content"] = content

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

        # Normalize incoming payload regardless of format (dict, model, or object)
        def _prepare_payload(payload: dict[str, Any]) -> dict[str, Any]:
            normalized_payload = dict(payload)
            if "messages" not in normalized_payload and "input" in normalized_payload:
                normalized_payload["messages"] = (
                    Translation._normalize_responses_input_to_messages(
                        normalized_payload["input"]
                    )
                )
            return normalized_payload

        if isinstance(request, dict):
            request_payload = _prepare_payload(request)
            responses_request = ResponsesRequest(**request_payload)
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
                request_payload["messages"] = (
                    Translation._normalize_responses_input_to_messages(input_value)
                )

            responses_request = ResponsesRequest(**request_payload)

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
                raw_content = choice.message.content or ""

                # Clean up content for JSON parsing
                cleaned_content = raw_content.strip()

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
                        raw_content = cleaned_content
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
                                raw_content = potential_json
                        except (json.JSONDecodeError, AttributeError):
                            # Still not valid JSON, leave parsed as None
                            pass

                message_payload: dict[str, Any] = {
                    "role": choice.message.role,
                    "content": raw_content or None,
                    "parsed": parsed_content,
                }

                tool_calls_payload: list[dict[str, Any]] = []
                if choice.message.tool_calls:
                    for tool_call in choice.message.tool_calls:
                        if hasattr(tool_call, "model_dump"):
                            tool_data = tool_call.model_dump()
                        elif isinstance(tool_call, dict):
                            tool_data = dict(tool_call)
                        else:
                            function = getattr(tool_call, "function", None)
                            tool_data = {
                                "id": getattr(tool_call, "id", ""),
                                "type": getattr(tool_call, "type", "function"),
                                "function": {
                                    "name": getattr(function, "name", ""),
                                    "arguments": getattr(function, "arguments", "{}"),
                                },
                            }

                        function_payload = tool_data.get("function")
                        if isinstance(function_payload, dict):
                            arguments = function_payload.get("arguments")
                            if isinstance(arguments, dict | list):
                                function_payload["arguments"] = json.dumps(arguments)
                            elif arguments is None:
                                function_payload["arguments"] = "{}"

                        tool_calls_payload.append(tool_data)

                if tool_calls_payload:
                    message_payload["tool_calls"] = tool_calls_payload

                response_choice = {
                    "index": choice.index,
                    "message": message_payload,
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

        if request.extra_body:
            extra_body_copy = dict(request.extra_body)

            # Extract and restructure response_format from extra_body
            response_format = extra_body_copy.pop("response_format", None)
            if response_format is not None:
                # Ensure the response_format is properly structured for Responses API
                if isinstance(response_format, dict):
                    payload["response_format"] = response_format
                elif hasattr(response_format, "model_dump"):
                    payload["response_format"] = response_format.model_dump()
                else:
                    payload["response_format"] = response_format

            # Add any remaining extra_body parameters that are safe for Responses API
            safe_extra_body = Translation._filter_responses_extra_body(extra_body_copy)
            if safe_extra_body:
                payload.update(safe_extra_body)

        return payload

    @staticmethod
    def _filter_responses_extra_body(extra_body: dict[str, Any]) -> dict[str, Any]:
        """Filter extra_body entries to include only Responses API specific parameters."""

        if not extra_body:
            return {}

        allowed_keys: set[str] = {"metadata"}

        return {key: value for key, value in extra_body.items() if key in allowed_keys}

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
    def _iter_json_candidates(
        content: str,
        *,
        max_candidates: int = 20,
        max_object_size: int = 512 * 1024,
    ) -> list[str]:
        """Find potential JSON object substrings using a linear-time scan."""

        candidates: list[str] = []
        depth = 0
        start_index: int | None = None
        escape_next = False
        string_delimiter: str | None = None

        for index, char in enumerate(content):
            if string_delimiter is not None:
                if escape_next:
                    escape_next = False
                    continue
                if char == "\\":
                    escape_next = True
                    continue
                if char == string_delimiter:
                    string_delimiter = None
                continue

            if char in ('"', "'"):
                string_delimiter = char
                continue

            if char == "{":
                if depth == 0:
                    start_index = index
                depth += 1
            elif char == "}":
                if depth == 0:
                    continue
                depth -= 1
                if depth == 0 and start_index is not None:
                    candidate = content[start_index : index + 1]
                    start_index = None
                    if len(candidate) > max_object_size:
                        if logger.isEnabledFor(logging.WARNING):
                            logger.warning(
                                "Skipping oversized JSON candidate (%d bytes)",
                                len(candidate),
                            )
                        continue
                    candidates.append(candidate)
                    if len(candidates) >= max_candidates:
                        break

        return candidates

    @staticmethod
    def _extract_and_repair_json(content: str, schema: dict[str, Any]) -> str | None:
        """Extract JSON from content and attempt repair."""

        try:
            for candidate in Translation._iter_json_candidates(content):
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    continue

                if not isinstance(parsed, dict):
                    continue

                repaired = Translation._attempt_json_repair(parsed, schema, None)
                if repaired is not None:
                    return json.dumps(repaired, indent=2)

            return None
        except Exception:
            return None
