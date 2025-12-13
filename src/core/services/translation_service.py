from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, cast

from pydantic import ValidationError

from src.core.app.constants.logging_constants import TRACE_LEVEL
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatResponse,
)
from src.core.domain.translation import Translation
from src.core.domain.translators.defaults import (
    ensure_default_translator_factories_registered,
)
from src.core.domain.translators.registry import (
    TranslatorRegistry,
    get_global_translator_registry,
)
from src.core.interfaces.translator_protocol import StreamingTranslatorProtocol
from src.core.services.translation_service_streaming import (
    dict_to_canonical_stream_chunk,
)

logger = logging.getLogger(__name__)


class TranslationService:
    """Central service for translating payloads between API formats."""

    def __init__(self, translator_registry: TranslatorRegistry | None = None) -> None:
        self._registry = translator_registry or get_global_translator_registry()
        ensure_default_translator_factories_registered(self._registry)

        def _to_domain_request(format_name: str) -> Callable[[Any], Any]:
            def _convert(request: Any) -> Any:
                return self._registry.get(format_name).to_domain_request(request)

            return _convert

        def _to_domain_response(format_name: str) -> Callable[[Any], Any]:
            def _convert(response: Any) -> Any:
                return self._registry.get(format_name).to_domain_response(response)

            return _convert

        def _from_domain_request(
            format_name: str,
        ) -> Callable[[CanonicalChatRequest], Any]:
            def _convert(request: CanonicalChatRequest) -> Any:
                return self._registry.get(format_name).from_domain_request(request)

            return _convert

        def _from_domain_response(format_name: str) -> Callable[[ChatResponse], Any]:
            def _convert(response: ChatResponse) -> Any:
                return self._registry.get(format_name).from_domain_response(response)

            return _convert

        self._to_domain_request_converters: dict[str, Callable[..., Any]] = {
            "gemini": _to_domain_request("gemini"),
            "openai": _to_domain_request("openai"),
            "openrouter": _to_domain_request("openrouter"),
            "anthropic": _to_domain_request("anthropic"),
            "code_assist": _to_domain_request("code_assist"),
            "raw_text": _to_domain_request("raw_text"),
            "responses": _to_domain_request("responses"),
            "openai-responses": _to_domain_request("openai-responses"),
        }
        self._to_domain_response_converters: dict[str, Callable[..., Any]] = {
            "gemini": _to_domain_response("gemini"),
            "openai": _to_domain_response("openai"),
            "openai-responses": _to_domain_response("openai-responses"),
            "responses": _to_domain_response("responses"),
            "anthropic": _to_domain_response("anthropic"),
            "code_assist": _to_domain_response("code_assist"),
            "raw_text": _to_domain_response("raw_text"),
        }

        self._from_domain_request_converters: dict[
            str, Callable[[CanonicalChatRequest], Any]
        ] = {
            "gemini": _from_domain_request("gemini"),
            "openai": _from_domain_request("openai"),
            "responses": _from_domain_request("responses"),
            "openai-responses": _from_domain_request("openai-responses"),
            "anthropic": _from_domain_request("anthropic"),
        }
        self._from_domain_response_converters: dict[
            str, Callable[[ChatResponse], Any]
        ] = {
            "openai": _from_domain_response("openai"),
            "openai-responses": _from_domain_response("openai-responses"),
            "responses": _from_domain_response("responses"),
            "anthropic": _from_domain_response("anthropic"),
            "gemini": _from_domain_response("gemini"),
        }

    def register_converter(
        self,
        direction: str,
        format: str,
        converter: Callable[..., Any],
    ) -> None:
        """Register a new converter.

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

    def _get_streaming_translator(
        self, format_name: str
    ) -> StreamingTranslatorProtocol:
        translator = self._registry.get(format_name)
        if not isinstance(translator, StreamingTranslatorProtocol):
            raise NotImplementedError(
                f"Stream chunk converter for format '{format_name}' not implemented."
            )
        return translator

    def to_domain_request(
        self, request: Any, source_format: str
    ) -> CanonicalChatRequest:
        """Translate an incoming request from a vendor format into CanonicalChatRequest."""
        from src.core.domain.chat import (
            CanonicalChatRequest as _Canonical,
        )
        from src.core.domain.chat import (
            ChatRequest as _ChatRequest,
        )

        if isinstance(request, _Canonical | _ChatRequest):
            if isinstance(request, _Canonical):
                return request
            return _Canonical.model_validate(request.model_dump())

        if source_format in {"responses", "openai-responses"}:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Converting Responses API request to domain format - model=%s",
                    getattr(request, "model", "unknown"),
                )

            has_response_format = False
            if isinstance(request, dict):
                if request.get("response_format"):
                    has_response_format = True
            elif hasattr(request, "response_format") and getattr(
                request, "response_format", None
            ):
                has_response_format = True

            if not has_response_format:
                raise ValidationError.from_exception_data(
                    title="ResponsesRequest",
                    line_errors=[
                        {
                            "type": "missing",
                            "loc": ("response_format",),
                            "input": (
                                request
                                if isinstance(request, dict)
                                else getattr(request, "__dict__", {})
                            ),
                        }
                    ],
                )

            try:
                responses_converter = self._to_domain_request_converters["responses"]
                domain_request = cast(
                    CanonicalChatRequest, responses_converter(request)
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Successfully converted Responses API request to domain format - model=%s",
                        getattr(request, "model", "unknown"),
                    )
                return domain_request
            except ValidationError:
                raise
            except (ValueError, KeyError) as exc:
                if isinstance(exc, json.JSONDecodeError):
                    if logger.isEnabledFor(logging.ERROR):
                        logger.error(
                            "JSON decode error in Responses API request - model=%s, error=%s",
                            getattr(request, "model", "unknown"),
                            exc,
                        )
                    raise ValueError(f"Invalid JSON in request: {exc}") from exc
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Invalid format in Responses API request - model=%s, error=%s",
                        getattr(request, "model", "unknown"),
                        exc,
                    )
                raise ValueError(f"Invalid request format: {exc}") from exc
            except Exception as exc:
                if logger.isEnabledFor(logging.ERROR):
                    logger.error(
                        "Unexpected error converting Responses API request - model=%s, error=%s",
                        getattr(request, "model", "unknown"),
                        exc,
                        exc_info=True,
                    )
                raise

        converter = self._to_domain_request_converters.get(source_format)
        if converter is None:
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
        """Translate a CanonicalChatRequest to a vendor request format."""
        converter = self._from_domain_request_converters.get(target_format)
        if converter is None:
            raise NotImplementedError(
                f"Request converter for format '{target_format}' not implemented."
            )
        return converter(request)

    def to_domain_response(
        self, response: Any, source_format: str
    ) -> CanonicalChatResponse:
        """Translate a vendor response format into CanonicalChatResponse."""
        converter = self._to_domain_response_converters.get(source_format)
        if converter is None:
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
        return self._registry.get("gemini").from_domain_request(request)

    def from_domain_to_openai_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        return self._registry.get("openai").from_domain_request(request)

    def from_domain_to_anthropic_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        return self._registry.get("anthropic").from_domain_request(request)

    def to_domain_stream_chunk(
        self, chunk: Any, source_format: str, target_format: str = "domain"
    ) -> Any:
        """Translate a streaming chunk to the internal format (lazy when possible)."""
        if source_format == target_format:
            return chunk

        canonical_formats = {
            "gemini",
            "openai",
            "raw_text",
            "openai-responses",
            "responses",
            "openrouter",
        }

        if logger.isEnabledFor(TRACE_LEVEL):
            chunk_keys = list(chunk.keys()) if isinstance(chunk, dict) else "N/A"
            logger.log(
                TRACE_LEVEL,
                "[STREAMING] TranslationService.to_domain_stream_chunk: "
                "Transforming chunk, source_format=%s, chunk_keys=%s",
                source_format,
                chunk_keys,
            )

        try:
            translator = self._get_streaming_translator(source_format)
        except KeyError as exc:
            raise NotImplementedError(
                f"Stream chunk converter for format '{source_format}' not implemented."
            ) from exc

        result: dict[str, Any] | CanonicalStreamChunk = (
            translator.to_domain_stream_chunk(chunk)
        )

        if isinstance(result, CanonicalStreamChunk):
            result = result.model_dump(exclude_none=True)
        if isinstance(result, dict):
            choices_val = result.get("choices")
            if isinstance(choices_val, list):
                result["choices"] = [
                    c.model_dump(exclude_none=True) if hasattr(c, "model_dump") else c
                    for c in choices_val
                ]

        if logger.isEnabledFor(TRACE_LEVEL):
            result_type = type(result).__name__
            result_keys = list(result.keys()) if isinstance(result, dict) else "N/A"
            logger.log(
                TRACE_LEVEL,
                "[STREAMING] TranslationService.to_domain_stream_chunk: "
                "Transformation complete, result_type=%s, result_keys=%s",
                result_type,
                result_keys,
            )

        if source_format in canonical_formats and isinstance(result, dict):
            return dict_to_canonical_stream_chunk(result)
        return result

    def from_domain_stream_chunk(
        self, chunk: Any, target_format: str, source_format: str = "domain"
    ) -> Any:
        """Translate an internal stream chunk to a vendor streaming format (lazy when possible)."""
        if source_format == target_format:
            return chunk

        if target_format == "openai":
            return self.from_domain_to_openai_stream_chunk(chunk)
        if target_format == "anthropic":
            return self.from_domain_to_anthropic_stream_chunk(chunk)
        if target_format == "gemini":
            return self.from_domain_to_gemini_stream_chunk(chunk)

        raise NotImplementedError(
            f"Stream chunk converter for format '{target_format}' not implemented."
        )

    def from_domain_to_openai_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get_streaming_translator("openai").from_domain_stream_chunk(chunk),
        )

    def from_domain_to_anthropic_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get_streaming_translator("anthropic").from_domain_stream_chunk(chunk),
        )

    def from_domain_to_gemini_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._get_streaming_translator("gemini").from_domain_stream_chunk(chunk),
        )

    def from_domain_to_openai_response(self, response: ChatResponse) -> dict[str, Any]:
        return self._registry.get("openai").from_domain_response(response)

    def from_domain_to_anthropic_response(
        self, response: ChatResponse
    ) -> dict[str, Any]:
        return self._registry.get("anthropic").from_domain_response(response)

    def from_domain_to_gemini_response(self, response: ChatResponse) -> dict[str, Any]:
        return self._registry.get("gemini").from_domain_response(response)

    def from_domain_response(
        self, response: ChatResponse, target_format: str = "openai"
    ) -> Any:
        if target_format in {"responses", "openai-responses"}:
            return self.from_domain_to_responses_response(response)

        converter = self._from_domain_response_converters.get(target_format)
        if converter is None:
            raise NotImplementedError(
                f"Response converter for format '{target_format}' not implemented."
            )
        return converter(response)

    def from_domain_to_responses_response(
        self, response: ChatResponse
    ) -> dict[str, Any]:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Converting domain response to Responses API format - response_id=%s",
                getattr(response, "id", "unknown"),
            )

        try:
            converted_response = self._registry.get("responses").from_domain_response(
                response
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Successfully converted response to Responses API format - response_id=%s",
                    getattr(response, "id", "unknown"),
                )
            return converted_response
        except Exception as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to convert response to Responses API format - response_id=%s, error=%s",
                    getattr(response, "id", "unknown"),
                    exc,
                )
            raise

    def from_domain_to_responses_request(
        self, request: CanonicalChatRequest
    ) -> dict[str, Any]:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Converting domain request to Responses API format - model=%s",
                request.model,
            )

        try:
            converted_request = self._registry.get("responses").from_domain_request(
                request
            )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Successfully converted request to Responses API format - model=%s",
                    request.model,
                )
            return converted_request
        except Exception as exc:
            if logger.isEnabledFor(logging.ERROR):
                logger.error(
                    "Failed to convert request to Responses API format - model=%s, error=%s",
                    request.model,
                    exc,
                )
            raise

    def enhance_structured_output_response(
        self,
        response: ChatResponse,
        original_request_extra_body: dict[str, Any] | None = None,
    ) -> ChatResponse:
        return Translation.enhance_structured_output_response(
            response, original_request_extra_body
        )

    def validate_json_against_schema(
        self, json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        return Translation.validate_json_against_schema(json_data, schema)
