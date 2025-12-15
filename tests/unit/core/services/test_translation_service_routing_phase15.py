from __future__ import annotations

from collections.abc import Collection
from typing import Any

import pytest
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    CanonicalStreamChunk,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
)
from src.core.domain.translators.registry import TranslatorRegistry
from src.core.services.translation_service import TranslationService


class _SpyTranslator:
    def __init__(self, *, format_names: Collection[str]) -> None:
        self._format_names = tuple(format_names)
        self.calls: list[tuple[str, Any]] = []

    @property
    def format_names(self) -> Collection[str]:
        return self._format_names

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        self.calls.append(("to_domain_request", request))
        return CanonicalChatRequest(
            model="spy",
            messages=[ChatMessage(role="user", content="x")],
        )

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        self.calls.append(("from_domain_request", request))
        return {"ok": True}

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        self.calls.append(("to_domain_response", response))
        return CanonicalChatResponse(
            id="spy",
            created=0,
            model="spy",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatCompletionChoiceMessage(role="assistant", content="x"),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        self.calls.append(("from_domain_response", response))
        return {"ok": True}

    def to_domain_stream_chunk(
        self, chunk: Any
    ) -> dict[str, Any] | CanonicalStreamChunk:
        self.calls.append(("to_domain_stream_chunk", chunk))
        return {
            "id": "stream",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "spy",
            "choices": [{"index": 0, "delta": {"content": "x"}, "finish_reason": None}],
        }

    def from_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        self.calls.append(("from_domain_stream_chunk", chunk))
        return {"stream": True}


def test_translation_service_routes_responses_request_via_injected_registry() -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"responses"})
    registry.register(translator)
    service = TranslationService(translator_registry=registry)

    payload = {
        "model": "gpt",
        "messages": [],
        "response_format": {"type": "json_schema"},
    }
    result = service.to_domain_request(payload, source_format="responses")

    assert result.model == "spy"
    assert ("to_domain_request", payload) in translator.calls


def test_translation_service_routes_openai_responses_alias_via_registry() -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"responses"})
    registry.register(translator)
    service = TranslationService(translator_registry=registry)

    result = service.to_domain_response({"id": "x"}, source_format="openai-responses")
    assert result.id == "spy"
    assert ("to_domain_response", {"id": "x"}) in translator.calls

    canonical = CanonicalChatRequest(
        model="spy", messages=[ChatMessage(role="user", content="x")]
    )
    service.from_domain_request(canonical, target_format="openai-responses")
    assert any(call[0] == "from_domain_request" for call in translator.calls)


def test_translation_service_routes_streaming_chunks_via_registry() -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"openai"})
    registry.register(translator)
    service = TranslationService(translator_registry=registry)

    result = service.to_domain_stream_chunk({"anything": True}, source_format="openai")
    assert isinstance(result, CanonicalStreamChunk)
    assert ("to_domain_stream_chunk", {"anything": True}) in translator.calls


def test_translation_service_raises_for_unknown_format() -> None:
    service = TranslationService(translator_registry=TranslatorRegistry())

    with pytest.raises(NotImplementedError):
        service.to_domain_response({"id": "x"}, source_format="unknown-format")
