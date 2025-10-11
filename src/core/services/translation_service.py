from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatResponse,
)
from src.core.domain.translation import Translation

logger = logging.getLogger(__name__)


class TranslationService:
    """
    A centralized service for translating requests and responses between different API formats.
    """

    def __init__(self) -> None:
        # Converters that translate vendor specific payloads into the canonical
        # domain models. These are used when a frontend request/response needs to
        # be normalized before handing it to the rest of the system.
        self._to_domain_request_converters: dict[str, Callable[..., Any]] = {
            "gemini": Translation.gemini_to_domain_request,
            "openai": Translation.openai_to_domain_request,
            "openrouter": Translation.openrouter_to_domain_request,
            "anthropic": Translation.anthropic_to_domain_request,
            "code_assist": Translation.code_assist_to_domain_request,
            "raw_text": Translation.raw_text_to_domain_request,
            "responses": Translation.responses_to_domain_request,
        }
        self._to_domain_response_converters: dict[str, Callable[..., Any]] = {
            "gemini": Translation.gemini_to_domain_response,
            "openai": Translation.openai_to_domain_response,
            "openai-responses": Translation.responses_to_domain_response,
            "anthropic": Translation.anthropic_to_domain_response,
            "code_assist": Translation.code_assist_to_domain_response,
            "raw_text": Translation.raw_text_to_domain_response,
        }

        # Converters that translate canonical payloads to provider specific
        # formats. These are used when calling backends.
        self._from_domain_request_converters: dict[
            str, Callable[[CanonicalChatRequest], Any]
        ] = {
            "gemini": self.from_domain_to_gemini_request,
            "openai": self.from_domain_to_openai_request,
            "openai-responses": self.from_domain_to_responses_request,
            "anthropic": self.from_domain_to_anthropic_request,
        }
        self._from_domain_response_converters: dict[
            str, Callable[[ChatResponse], Any]
        ] = {
            "openai": self.from_domain_to_openai_response,
            "openai-responses": self.from_domain_to_responses_response,
            "anthropic": self.from_domain_to_anthropic_response,
            "gemini": self.from_domain_to_gemini_response,
        }

    def register_converter(
        self,
        direction: str,
        format: str,
        converter: Callable[..., Any],
    ) -> None:
        """
        Register a new converter.

        Args:
            direction: The direction of the conversion (e.g., "request", "response").
            format: The API format (e.g., "anthropic", "gemini").
            converter: The converter function.
        """
        converters = self._get_converter_mapping(direction)
        converters[format] = converter

    def _get_converter_mapping(self, direction: str) -> dict[str, Callable[..., Any]]:
        mapping: dict[str, dict[str, Callable[..., Any]]] = {
            "request": self._to_domain_request_converters,
            "to_domain_request": self._to_domain_request_converters,
            "response": self._to_domain_response_converters,
            "to_domain_response": self._to_domain_response_converters,
            "from_domain_request": self._from_domain_request_converters,
            "from_domain_response": self._from_domain_response_converters,
        }
        try:
            return mapping[direction]
        except KeyError as exc:  # pragma: no cover - defensive guard
            raise KeyError(f"Unknown converter direction: {direction}") from exc

    def to_domain_request(
        self, request: Any, source_format: str
    ) -> CanonicalChatRequest:
        """
        Translates an incoming request from a specific API format to the internal domain ChatRequest.

        Args:
            request: The request object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            A ChatRequest object.

        Raises:
            ValueError: If the source format is not supported.
            TypeError: If the request object is not in the expected format.
        """
        """
        Translates an incoming request from a specific API format to the internal domain ChatRequest.

        Args:
            request: The request object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            A ChatRequest object.
        """
        # If the request is already in canonical/domain form, return it as-is
        from src.core.domain.chat import (
            CanonicalChatRequest as _Canonical,
        )
        from src.core.domain.chat import (
            ChatRequest as _ChatRequest,
        )

        if isinstance(request, _Canonical | _ChatRequest):
            return _Canonical.model_validate(request.model_dump())

        if source_format == "responses":
            logger.debug(
                f"Converting Responses API request to domain format - model={getattr(request, 'model', 'unknown')}"
            )
            try:
                domain_request = Translation.responses_to_domain_request(request)
                logger.debug(
                    f"Successfully converted Responses API request to domain format - model={getattr(request, 'model', 'unknown')}"
                )
                return domain_request
            except ValidationError:
                raise
            except (ValueError, KeyError) as e:
                if isinstance(e, json.JSONDecodeError):
                    logger.error(
                        f"JSON decode error in Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}"
                    )
                    raise ValueError(f"Invalid JSON in request: {e}") from e
                logger.error(
                    f"Invalid format in Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}"
                )
                raise ValueError(f"Invalid request format: {e}") from e
            except Exception as e:
                logger.error(
                    f"Unexpected error converting Responses API request - model={getattr(request, 'model', 'unknown')}, error={e}",
                    exc_info=True,
                )
                raise
        converter = self._to_domain_request_converters.get(source_format)
        if not converter:
            raise NotImplementedError(
                f"Request converter for format '{source_format}' not implemented."
            )
        converted = converter(request)
        if isinstance(converted, CanonicalChatRequest):
            return converted
        return CanonicalChatRequest.model_validate(converted)

    def from_domain_request(
        self, request: CanonicalChatRequest, target_format: str
    ) -> Any:
        """
        Translates an internal domain ChatRequest to a specific API format.

        Args:
            request: The internal ChatRequest object.
            target_format: The target API format (e.g., "anthropic", "gemini").

        Returns:
            The request object in the target format.
        """
        converter = self._from_domain_request_converters.get(target_format)
        if not converter:
            raise NotImplementedError(
                f"Request converter for format '{target_format}' not implemented."
            )
        return converter(request)

    def to_domain_response(
        self, response: Any, source_format: str
    ) -> CanonicalChatResponse:
        """
        Translates a response from a specific API format to the internal domain ChatResponse.

        Args:
            response: The response object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            A ChatResponse object.
        """
        converter = self._to_domain_response_converters.get(source_format)
        if not converter:
            raise NotImplementedError(
                f"Response converter for format '{source_format}' not implemented."
            )
        converted = converter(response)
        if isinstance(converted, CanonicalChatResponse):
            return converted
        return CanonicalChatResponse.model_validate(converted)

    def from_domain_to_gemini_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        """Translates a CanonicalChatRequest to a Gemini request."""
        return Translation.from_domain_to_gemini_request(request)

    def from_domain_to_openai_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        """Translates a CanonicalChatRequest to an OpenAI request."""
        return Translation.from_domain_to_openai_request(request)

    def from_domain_to_anthropic_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        """Translates a CanonicalChatRequest to an Anthropic request."""
        return Translation.from_domain_to_anthropic_request(request)

    def to_domain_stream_chunk(
        self, chunk: Any, source_format: str, target_format: str = "domain"
    ) -> Any:
        """
        Translates a streaming chunk from a specific API format to the internal domain stream chunk.
        Implements lazy translation - only translates when format mismatch occurs.

        Args:
            chunk: The stream chunk object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").
            target_format: The target format (default: "domain").

        Returns:
            The stream chunk in the target format (only translated if needed).
        """
        # Lazy translation: skip if source and target formats match
        if source_format == target_format:
            return chunk

        # Only translate when there's a format mismatch
        if source_format == "gemini":
            return Translation.gemini_to_domain_stream_chunk(chunk)
        elif source_format == "openai":
            return Translation.openai_to_domain_stream_chunk(chunk)
        elif source_format == "openai-responses":
            return Translation.responses_to_domain_stream_chunk(chunk)
        elif source_format == "anthropic":
            return Translation.anthropic_to_domain_stream_chunk(chunk)
        elif source_format == "code_assist":
            return Translation.code_assist_to_domain_stream_chunk(chunk)
        elif source_format == "raw_text":
            return Translation.raw_text_to_domain_stream_chunk(chunk)
        # Add more specific stream chunk converters here as needed
        raise NotImplementedError(
            f"Stream chunk converter for format '{source_format}' not implemented."
        )

    def from_domain_stream_chunk(
        self, chunk: Any, target_format: str, source_format: str = "domain"
    ) -> Any:
        """
        Translates an internal domain stream chunk to a specific API format.
        Implements lazy translation - only translates when format mismatch occurs.

        Args:
            chunk: The internal domain stream chunk object.
            target_format: The target API format (e.g., "anthropic", "gemini").
            source_format: The source format (default: "domain").

        Returns:
            The stream chunk in the target format (only translated if needed).
        """
        # Lazy translation: skip if source and target formats match
        if source_format == target_format:
            return chunk

        # Only translate when there's a format mismatch
        if target_format == "openai":
            return self.from_domain_to_openai_stream_chunk(chunk)
        elif target_format == "anthropic":
            return self.from_domain_to_anthropic_stream_chunk(chunk)
        elif target_format == "gemini":
            return self.from_domain_to_gemini_stream_chunk(chunk)

        raise NotImplementedError(
            f"Stream chunk converter for format '{target_format}' not implemented."
        )

    def from_domain_to_openai_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        """Translates a domain stream chunk to an OpenAI stream format."""
        # Basic implementation that assumes chunk contains delta or content
        content = getattr(chunk, "content", None) or getattr(chunk, "delta", {}).get(
            "content", ""
        )

        return {
            "id": getattr(chunk, "id", "chatcmpl-stream"),
            "object": "chat.completion.chunk",
            "created": getattr(chunk, "created", int(__import__("time").time())),
            "model": getattr(chunk, "model", "unknown"),
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": content},
                    "finish_reason": getattr(chunk, "finish_reason", None),
                }
            ],
        }

    def from_domain_to_anthropic_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        """Translates a domain stream chunk to an Anthropic stream format."""
        # Basic implementation assuming chunk contains content
        content = getattr(chunk, "content", "") or ""

        return {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": content},
        }

    def from_domain_to_gemini_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        """Translates a domain stream chunk to a Gemini stream format."""
        # Basic implementation assuming chunk contains content
        content = getattr(chunk, "content", "") or ""

        return {
            "candidates": [
                {
                    "content": {"parts": [{"text": content}], "role": "model"},
                    "finishReason": (
                        "STOP" if getattr(chunk, "is_last", False) else None
                    ),
                }
            ]
        }

    def from_domain_to_openai_response(self, response: ChatResponse) -> dict[str, Any]:
        """Translates a domain ChatResponse to an OpenAI response format."""
        return {
            "id": response.id,
            "object": "chat.completion",
            "created": response.created,
            "model": response.model,
            "choices": [
                {
                    "index": choice.index,
                    "message": {
                        "role": choice.message.role,
                        "content": choice.message.content,
                        **(
                            {"tool_calls": choice.message.tool_calls}
                            if choice.message.tool_calls
                            else {}
                        ),
                    },
                    "finish_reason": choice.finish_reason,
                }
                for choice in response.choices
            ],
            "usage": response.usage,
        }

    def from_domain_to_anthropic_response(
        self, response: ChatResponse
    ) -> dict[str, Any]:
        """Translates a domain ChatResponse to an Anthropic response format."""
        content_blocks: list[dict[str, Any]] = []

        first_choice = response.choices[0] if response.choices else None
        message = first_choice.message if first_choice else None

        if message and message.content:
            content_blocks.append({"type": "text", "text": message.content})

        if message and message.tool_calls:
            for tool_call in message.tool_calls:
                arguments_raw = tool_call.function.arguments
                try:
                    arguments = json.loads(arguments_raw)
                except Exception:
                    arguments = {"_raw": arguments_raw}

                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tool_call.id,
                        "name": tool_call.function.name,
                        "input": arguments,
                    }
                )

        stop_reason = first_choice.finish_reason if first_choice else "stop"

        usage: dict[str, Any] | None = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.get("prompt_tokens", 0),
                "output_tokens": response.usage.get("completion_tokens", 0),
            }

        return {
            "id": response.id,
            "type": "message",
            "role": "assistant",
            "model": response.model,
            "content": content_blocks,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage,
        }

    def from_domain_to_gemini_response(self, response: ChatResponse) -> dict[str, Any]:
        """Translates a domain ChatResponse to a Gemini response format."""
        candidates = []
        for choice in response.choices:
            if choice.message:
                candidates.append(
                    {
                        "content": {
                            "parts": [{"text": choice.message.content or ""}],
                            "role": choice.message.role,
                        },
                        "finishReason": (
                            choice.finish_reason.upper()
                            if choice.finish_reason
                            else "STOP"
                        ),
                        "index": choice.index,
                        "safetyRatings": [],
                    }
                )

        return {
            "candidates": candidates,
            "promptFeedback": {"safetyRatings": []},
            "usageMetadata": (
                {
                    "promptTokenCount": (
                        response.usage.get("prompt_tokens", 0) if response.usage else 0
                    ),
                    "candidatesTokenCount": (
                        response.usage.get("completion_tokens", 0)
                        if response.usage
                        else 0
                    ),
                    "totalTokenCount": (
                        response.usage.get("total_tokens", 0) if response.usage else 0
                    ),
                }
                if response.usage
                else {}
            ),
        }

    def from_domain_response(
        self, response: ChatResponse, target_format: str = "openai"
    ) -> Any:
        """
        Translates an internal domain ChatResponse to a specific API format.

        Args:
            response: The internal ChatResponse object.
            target_format: The target API format (e.g., "anthropic", "gemini", "responses").

        Returns:
            The response object in the target format.
        """
        # Handle special case for responses format
        if target_format == "responses":
            return self.from_domain_to_responses_response(response)

        converter = self._from_domain_response_converters.get(target_format)
        if not converter:
            raise NotImplementedError(
                f"Response converter for format '{target_format}' not implemented."
            )
        return converter(response)

    def from_domain_to_responses_response(
        self, response: ChatResponse
    ) -> dict[str, Any]:
        """Translates a domain ChatResponse to a Responses API response format."""
        logger.debug(
            f"Converting domain response to Responses API format - response_id={getattr(response, 'id', 'unknown')}"
        )

        try:
            converted_response = Translation.from_domain_to_responses_response(response)
            logger.debug(
                f"Successfully converted response to Responses API format - response_id={getattr(response, 'id', 'unknown')}"
            )
            return converted_response
        except Exception as e:
            logger.error(
                f"Failed to convert response to Responses API format - response_id={getattr(response, 'id', 'unknown')}, error={e}"
            )
            raise

    def from_domain_to_responses_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        """Translates a CanonicalChatRequest to a Responses API request format."""
        logger.debug(
            f"Converting domain request to Responses API format - model={request.model}"
        )

        try:
            converted_request = Translation.from_domain_to_responses_request(request)
            logger.debug(
                f"Successfully converted request to Responses API format - model={request.model}"
            )
            return converted_request
        except Exception as e:
            logger.error(
                f"Failed to convert request to Responses API format - model={request.model}, error={e}"
            )
            raise

    def enhance_structured_output_response(
        self,
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
        return Translation.enhance_structured_output_response(
            response, original_request_extra_body
        )

    def validate_json_against_schema(
        self, json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Validate JSON data against a JSON schema.

        Args:
            json_data: The JSON data to validate
            schema: The JSON schema to validate against

        Returns:
            A tuple of (is_valid, error_message)
        """
        return Translation.validate_json_against_schema(json_data, schema)
