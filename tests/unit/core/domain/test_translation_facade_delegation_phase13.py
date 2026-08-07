from __future__ import annotations

from collections.abc import Collection
from typing import Any

from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    ChatMessage,
    ChatResponse,
)
from src.core.domain.translation import Translation
from src.core.domain.translators.registry import TranslatorRegistry


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
            model="spy", messages=[ChatMessage(role="user", content="x")]
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

    def to_domain_stream_chunk(self, chunk: Any) -> dict[str, Any]:
        self.calls.append(("to_domain_stream_chunk", chunk))
        return {"stream": "ok"}


def test_translation_facade_delegates_gemini_to_domain_request(
    monkeypatch: Any,
) -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"gemini"})
    registry.register(translator)

    import src.core.domain.translation as translation_module

    monkeypatch.setattr(
        translation_module, "get_global_translator_registry", lambda: registry
    )

    result = Translation.gemini_to_domain_request({"anything": True})
    assert result.model == "spy"
    assert ("to_domain_request", {"anything": True}) in translator.calls


def test_translation_facade_delegates_anthropic_to_domain_response(
    monkeypatch: Any,
) -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"anthropic"})
    registry.register(translator)

    import src.core.domain.translation as translation_module

    monkeypatch.setattr(
        translation_module, "get_global_translator_registry", lambda: registry
    )

    payload = {"id": "x"}
    result = Translation.anthropic_to_domain_response(payload)
    assert result.id == "spy"
    assert ("to_domain_response", payload) in translator.calls


def test_translation_facade_delegates_openai_to_domain_stream_chunk(
    monkeypatch: Any,
) -> None:
    registry = TranslatorRegistry()
    translator = _SpyTranslator(format_names={"openai"})
    registry.register(translator)

    import src.core.domain.translation as translation_module

    monkeypatch.setattr(
        translation_module, "get_global_translator_registry", lambda: registry
    )

    payload = {"chunk": True}
    result = Translation.openai_to_domain_stream_chunk(payload)
    assert result == {"stream": "ok"}
    assert ("to_domain_stream_chunk", payload) in translator.calls
