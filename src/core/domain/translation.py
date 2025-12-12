from __future__ import annotations

import json  # noqa: F401
from typing import Any, cast

from src.core.domain.base_translator import BaseTranslator
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatResponse,
    ToolCall,
)
from src.core.domain.translation_utils import (
    json_utils,
    media_utils,
    tool_utils,
    usage_utils,
)
from src.core.domain.translation_utils.content_utils import (
    _safe_string as _safe_string_value,
)
from src.core.domain.translation_utils.gemini_schema_utils import (
    _sanitize_gemini_parameters as _sanitize_gemini_parameters_impl,
)
from src.core.domain.translation_utils.schema_validation import (
    basic_schema_validation,
    validate_json_against_schema,
)
from src.core.domain.translation_utils.structured_output import (
    attempt_json_repair,
    enhance_structured_output_response,
    extract_and_repair_json,
    iter_json_candidates,
)
from src.core.domain.translators.defaults import (
    ensure_default_translator_factories_registered,
)
from src.core.domain.translators.registry import (
    TranslatorRegistry,
    get_global_translator_registry,
)
from src.core.services.tool_text_renderer import render_tool_call  # noqa: F401

_MAX_SANITIZE_DEPTH = 100


class Translation(BaseTranslator):
    """Backward-compatible translation facade.

    The previous implementation bundled all translation logic in this class. This refactor
    keeps the public API stable while delegating format-specific work to dedicated
    translators registered in a TranslatorRegistry.
    """

    _codex_tool_call_index_base: dict[str, int] = {}
    _codex_tool_call_item_index: dict[str, dict[str, int]] = {}
    _codex_function_name_cache: dict[str, str] = {}

    @classmethod
    def _registry(cls) -> TranslatorRegistry:
        registry = get_global_translator_registry()
        ensure_default_translator_factories_registered(registry)
        return registry

    @classmethod
    def _translator(cls, format_name: str) -> Any:
        return cls._registry().get(format_name)

    @classmethod
    def _reset_tool_call_state(cls, response_id: str | None) -> None:
        if not response_id:
            return
        cls._codex_tool_call_index_base.pop(response_id, None)
        cls._codex_tool_call_item_index.pop(response_id, None)

    @classmethod
    def _cache_function_name(cls, call_id: str, name: str) -> None:
        if call_id and name:
            cls._codex_function_name_cache[call_id] = name

    @classmethod
    def _get_cached_function_name(cls, call_id: str) -> str:
        return cls._codex_function_name_cache.get(call_id, "")

    @classmethod
    def _assign_tool_call_index(
        cls,
        response_id: str | None,
        output_index: Any,
        item_id: str | None,
    ) -> int:
        if not response_id:
            return 0

        if not isinstance(output_index, int):
            if item_id:
                return cls._codex_tool_call_item_index.get(response_id, {}).get(
                    item_id, 0
                )
            return 0

        base = cls._codex_tool_call_index_base.get(response_id)
        if base is None or output_index < base:
            cls._codex_tool_call_index_base[response_id] = output_index
            base = output_index

        index = output_index - base
        if index < 0:
            index = 0

        if item_id:
            cls._codex_tool_call_item_index.setdefault(response_id, {})[item_id] = index

        return index

    @staticmethod
    def validate_json_against_schema(
        json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        return validate_json_against_schema(json_data, schema)

    @staticmethod
    def _basic_schema_validation(
        json_data: dict[str, Any], schema: dict[str, Any]
    ) -> tuple[bool, str | None]:
        return basic_schema_validation(json_data, schema)

    @staticmethod
    def _detect_image_mime_type(url: str) -> str:
        return media_utils._detect_image_mime_type(url)

    @staticmethod
    def _process_gemini_image_part(part: Any) -> dict[str, Any] | None:
        return media_utils._process_gemini_image_part(part)

    @staticmethod
    def _normalize_usage_metadata(
        usage: dict[str, Any], source_format: str
    ) -> dict[str, Any]:
        return usage_utils._normalize_usage_metadata(usage, source_format)

    @staticmethod
    def _normalize_responses_input_to_messages(
        input_payload: Any,
    ) -> list[dict[str, Any]]:
        from src.core.domain.translators.responses.request import (
            _normalize_responses_input_to_messages,
        )

        return _normalize_responses_input_to_messages(input_payload)

    @staticmethod
    def _normalize_responses_content(content: Any) -> Any:
        from src.core.domain.translators.responses.request import (
            _normalize_responses_content,
        )

        return _normalize_responses_content(content)

    @staticmethod
    def _normalize_responses_content_part(
        content: dict[str, Any]
    ) -> list[dict[str, Any]]:
        from src.core.domain.translators.responses.request import (
            _normalize_responses_content_part,
        )

        return _normalize_responses_content_part(content)

    @staticmethod
    def _safe_string(value: Any) -> str:
        return _safe_string_value(value)

    @staticmethod
    def _map_gemini_finish_reason(finish_reason: str | None) -> str | None:
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
        if stop is None:
            return None
        if isinstance(stop, str):
            return [stop]
        if isinstance(stop, list):
            return [str(s) for s in stop]
        return [str(stop)]

    @staticmethod
    def _normalize_tool_arguments(args: Any) -> str:
        return tool_utils._normalize_tool_arguments(args)

    @staticmethod
    def _is_json_serializable(
        value: Any,
        *,
        max_depth: int,
        _depth: int = 0,
        _seen: set[int] | None = None,
    ) -> bool:
        return json_utils._is_json_serializable(
            value,
            max_depth=max_depth,
            _depth=_depth,
            _seen=_seen,
        )

    @staticmethod
    def _sanitize_dict_for_json(
        data: dict[str, Any],
        *,
        max_depth: int = _MAX_SANITIZE_DEPTH,
        _depth: int = 0,
        _seen: set[int] | None = None,
    ) -> dict[str, Any]:
        return json_utils._sanitize_dict_for_json(
            data,
            max_depth=max_depth,
            _depth=_depth,
            _seen=_seen,
        )

    @staticmethod
    def _sanitize_list_for_json(
        data: list[Any],
        *,
        max_depth: int = _MAX_SANITIZE_DEPTH,
        _depth: int = 0,
        _seen: set[int] | None = None,
    ) -> list[Any]:
        return json_utils._sanitize_list_for_json(
            data,
            max_depth=max_depth,
            _depth=_depth,
            _seen=_seen,
        )

    @staticmethod
    def _process_gemini_function_call(
        function_call: dict[str, Any], part: dict[str, Any] | None = None
    ) -> ToolCall:
        return tool_utils._process_gemini_function_call(function_call, part=part)

    @staticmethod
    def gemini_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("gemini").to_domain_request(request),
        )

    @staticmethod
    def anthropic_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("anthropic").to_domain_request(request),
        )

    @staticmethod
    def anthropic_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("anthropic").to_domain_response(response),
        )

    @staticmethod
    def gemini_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("gemini").to_domain_response(response),
        )

    @staticmethod
    def gemini_to_domain_stream_chunk(
        chunk: Any,
    ) -> dict[str, Any] | CanonicalStreamChunk:
        translator = Translation._translator("gemini")
        return cast(
            dict[str, Any] | CanonicalStreamChunk,
            cast(Any, translator).to_domain_stream_chunk(chunk),
        )

    @staticmethod
    def openai_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("openai").to_domain_request(request),
        )

    @staticmethod
    def openai_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("openai").to_domain_response(response),
        )

    @staticmethod
    def responses_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("responses").to_domain_response(response),
        )

    @staticmethod
    def openai_to_domain_stream_chunk(
        chunk: Any,
    ) -> dict[str, Any] | CanonicalStreamChunk:
        translator = Translation._translator("openai")
        return cast(
            dict[str, Any] | CanonicalStreamChunk,
            cast(Any, translator).to_domain_stream_chunk(chunk),
        )

    @staticmethod
    def responses_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        translator = Translation._translator("responses")
        return cast(dict[str, Any], cast(Any, translator).to_domain_stream_chunk(chunk))

    @staticmethod
    def openrouter_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("openrouter").to_domain_request(request),
        )

    @staticmethod
    def _validate_request_parameters(request: CanonicalChatRequest) -> None:
        from src.core.domain.translators.gemini.request import (
            _validate_request_parameters,
        )

        _validate_request_parameters(request)

    @staticmethod
    def from_domain_to_gemini_request(request: CanonicalChatRequest) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Translation._translator("gemini").from_domain_request(request),
        )

    @staticmethod
    def _sanitize_gemini_parameters(schema: dict[str, Any]) -> dict[str, Any]:
        return _sanitize_gemini_parameters_impl(schema)

    @staticmethod
    def from_domain_to_openai_request(request: CanonicalChatRequest) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Translation._translator("openai").from_domain_request(request),
        )

    @staticmethod
    def anthropic_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        translator = Translation._translator("anthropic")
        return cast(dict[str, Any], cast(Any, translator).to_domain_stream_chunk(chunk))

    @staticmethod
    def from_domain_to_anthropic_request(
        request: CanonicalChatRequest,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Translation._translator("anthropic").from_domain_request(request),
        )

    @staticmethod
    def code_assist_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("code_assist").to_domain_request(request),
        )

    @staticmethod
    def code_assist_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("code_assist").to_domain_response(response),
        )

    @staticmethod
    def code_assist_to_domain_stream_chunk(chunk: Any) -> dict[str, Any]:
        translator = Translation._translator("code_assist")
        return cast(dict[str, Any], cast(Any, translator).to_domain_stream_chunk(chunk))

    @staticmethod
    def raw_text_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("raw_text").to_domain_request(request),
        )

    @staticmethod
    def raw_text_to_domain_response(response: Any) -> CanonicalChatResponse:
        return cast(
            CanonicalChatResponse,
            Translation._translator("raw_text").to_domain_response(response),
        )

    @staticmethod
    def raw_text_to_domain_stream_chunk(
        chunk: Any,
    ) -> dict[str, Any] | CanonicalStreamChunk:
        translator = Translation._translator("raw_text")
        return cast(
            dict[str, Any] | CanonicalStreamChunk,
            cast(Any, translator).to_domain_stream_chunk(chunk),
        )

    @staticmethod
    def responses_to_domain_request(request: Any) -> CanonicalChatRequest:
        return cast(
            CanonicalChatRequest,
            Translation._translator("responses").to_domain_request(request),
        )

    @staticmethod
    def from_domain_to_responses_response(response: ChatResponse) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Translation._translator("responses").from_domain_response(response),
        )

    @staticmethod
    def from_domain_to_responses_request(
        request: CanonicalChatRequest,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            Translation._translator("responses").from_domain_request(request),
        )

    @staticmethod
    def _filter_responses_extra_body(extra_body: dict[str, Any]) -> dict[str, Any]:
        from src.core.domain.translators.responses.request import (
            _filter_responses_extra_body,
        )

        return _filter_responses_extra_body(extra_body)

    @staticmethod
    def enhance_structured_output_response(
        response: ChatResponse,
        original_request_extra_body: dict[str, Any] | None = None,
    ) -> ChatResponse:
        return enhance_structured_output_response(
            response, original_request_extra_body=original_request_extra_body
        )

    @staticmethod
    def _attempt_json_repair(
        json_data: dict[str, Any], schema: dict[str, Any], error_msg: str | None
    ) -> dict[str, Any] | None:
        return attempt_json_repair(json_data, schema, error_msg)

    @staticmethod
    def _iter_json_candidates(
        content: str,
        *,
        max_candidates: int = 20,
        max_object_size: int = 512 * 1024,
    ) -> list[str]:
        return iter_json_candidates(
            content,
            max_candidates=max_candidates,
            max_object_size=max_object_size,
        )

    @staticmethod
    def _extract_and_repair_json(content: str, schema: dict[str, Any]) -> str | None:
        return extract_and_repair_json(content, schema)


__all__ = ["Translation"]
