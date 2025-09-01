from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatResponse,
)
from src.core.domain.translation import Translation


class TranslationService:
    """
    A centralized service for translating requests and responses between different API formats.
    """

    def __init__(self) -> None:
        self._converters: dict[str, dict[str, Callable[..., Any]]] = {
            "request": {
                "gemini": Translation.gemini_to_domain_request,
                "openai": Translation.openai_to_domain_request,
                "openrouter": Translation.openrouter_to_domain_request,
                "anthropic": Translation.anthropic_to_domain_request,
            },
            "response": {
                "gemini": Translation.gemini_to_domain_response,
                "openai": Translation.openai_to_domain_response,
                "anthropic": Translation.anthropic_to_domain_response,
            },
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
        self._converters[direction][format] = converter

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

        if source_format == "gemini":
            return Translation.gemini_to_domain_request(request)
        elif source_format == "openai":
            return Translation.openai_to_domain_request(request)
        elif source_format == "openrouter":
            return Translation.openrouter_to_domain_request(request)
        elif source_format == "anthropic":
            return Translation.anthropic_to_domain_request(request)
        converter = self._converters["request"].get(source_format)
        if not converter:
            raise NotImplementedError(
                f"Request converter for format '{source_format}' not implemented."
            )
        return CanonicalChatRequest.model_validate(converter(request))

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
        if target_format == "gemini":
            return Translation.from_domain_to_gemini_request(request)
        elif target_format == "openai":
            return Translation.from_domain_to_openai_request(request)
        elif target_format == "anthropic":
            return Translation.from_domain_to_anthropic_request(request)

        converter = self._converters["request"].get(target_format)
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
        if source_format == "gemini":
            return Translation.gemini_to_domain_response(response)
        elif source_format == "openai":
            return Translation.openai_to_domain_response(response)
        elif source_format == "anthropic":
            return Translation.anthropic_to_domain_response(response)
        converter = self._converters["response"].get(source_format)
        if not converter:
            raise NotImplementedError(
                f"Response converter for format '{source_format}' not implemented."
            )
        return CanonicalChatResponse.model_validate(converter(response))

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

    def to_domain_stream_chunk(self, chunk: Any, source_format: str) -> Any:
        """
        Translates a streaming chunk from a specific API format to the internal domain stream chunk.

        Args:
            chunk: The stream chunk object in the source format.
            source_format: The source API format (e.g., "anthropic", "gemini").

        Returns:
            The stream chunk in the internal domain format.
        """
        if source_format == "gemini":
            # For Gemini, the raw chunk is already in a format that can be directly yielded
            # or minimally processed to match the expected stream format.
            # We will convert it to a canonical stream chunk format if needed later.
            return chunk
        elif source_format == "openai":
            return Translation.openai_to_domain_stream_chunk(chunk)
        elif source_format == "anthropic":
            return Translation.anthropic_to_domain_stream_chunk(chunk)
        # Add more specific stream chunk converters here as needed
        raise NotImplementedError(
            f"Stream chunk converter for format '{source_format}' not implemented."
        )

    def from_domain_stream_chunk(self, chunk: Any, target_format: str) -> Any:
        """
        Translates an internal domain stream chunk to a specific API format.

        Args:
            chunk: The internal domain stream chunk object.
            target_format: The target API format (e.g., "anthropic", "gemini").

        Returns:
            The stream chunk in the target format.
        """
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
        # Extract content from first choice (Anthropic always returns a single completion)
        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""

        return {
            "id": response.id,
            "type": "completion",
            "role": "assistant",
            "content": content,
            "model": response.model,
            "stop_reason": (
                response.choices[0].finish_reason if response.choices else "stop"
            ),
            "stop_sequence": None,
            "usage": response.usage,
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

    def from_domain_response(self, response: ChatResponse, target_format: str) -> Any:
        """
        Translates an internal domain ChatResponse to a specific API format.

        Args:
            response: The internal ChatResponse object.
            target_format: The target API format (e.g., "anthropic", "gemini").

        Returns:
            The response object in the target format.
        """
        if target_format == "openai":
            return self.from_domain_to_openai_response(response)
        elif target_format == "anthropic":
            return self.from_domain_to_anthropic_response(response)
        elif target_format == "gemini":
            return self.from_domain_to_gemini_response(response)

        raise NotImplementedError(
            f"Response converter for format '{target_format}' not implemented."
        )
