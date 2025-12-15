from __future__ import annotations

from collections.abc import Collection
from typing import Any

import pytest
from src.core.domain.chat import (
    CanonicalChatRequest,
    CanonicalChatResponse,
    ChatResponse,
)
from src.core.domain.translators.registry import TranslatorRegistry


class _DummyTranslator:
    def __init__(self, *, format_names: Collection[str]) -> None:
        self._format_names = tuple(format_names)

    @property
    def format_names(self) -> Collection[str]:
        return self._format_names

    def to_domain_request(self, request: Any) -> CanonicalChatRequest:
        raise NotImplementedError

    def from_domain_request(self, request: CanonicalChatRequest) -> dict[str, Any]:
        raise NotImplementedError

    def to_domain_response(self, response: Any) -> CanonicalChatResponse:
        raise NotImplementedError

    def from_domain_response(self, response: ChatResponse) -> dict[str, Any]:
        raise NotImplementedError


def test_translator_registry_register_and_get() -> None:
    registry = TranslatorRegistry()
    translator = _DummyTranslator(format_names={"openai"})

    registry.register(translator)

    assert registry.has("openai") is True
    assert registry.get("openai") is translator


def test_translator_registry_alias_openai_responses_routes_to_responses() -> None:
    registry = TranslatorRegistry()
    translator = _DummyTranslator(format_names={"responses"})

    registry.register(translator)

    assert registry.has("openai-responses") is True
    assert registry.get("openai-responses") is translator
    assert registry.get("responses") is translator


def test_translator_registry_register_factory_is_lazy_and_cached() -> None:
    registry = TranslatorRegistry()
    created: list[_DummyTranslator] = []

    def _factory() -> _DummyTranslator:
        translator = _DummyTranslator(format_names={"openai"})
        created.append(translator)
        return translator

    registry.register_factory("openai", _factory)

    assert registry.has("openai") is True
    assert created == []

    first = registry.get("openai")
    assert created == [first]

    second = registry.get("openai")
    assert second is first
    assert created == [first]


def test_translator_registry_rejects_non_translator() -> None:
    registry = TranslatorRegistry()

    with pytest.raises(TypeError, match="Translator must implement TranslatorProtocol"):
        registry.register(object())  # type: ignore[arg-type]


def test_translator_registry_get_unknown_raises_key_error() -> None:
    registry = TranslatorRegistry()

    with pytest.raises(KeyError, match="No translator registered for format"):
        registry.get("does-not-exist")


@pytest.mark.parametrize(
    "format_name",
    [
        "openai",
        "OpenAI",
        " OPENAI ",
        "openAi",
    ],
)
def test_translator_registry_get_normalizes_openai_format_name(
    format_name: str,
) -> None:
    registry = TranslatorRegistry()
    translator = _DummyTranslator(format_names={"openai"})

    registry.register(translator)

    assert registry.get(format_name) is translator


@pytest.mark.parametrize(
    "format_name",
    [
        "openai-responses",
        "OpenAI-Responses",
        " openai-responses ",
        "OPENAI-RESPONSES",
    ],
)
def test_translator_registry_get_normalizes_openai_responses_alias(
    format_name: str,
) -> None:
    registry = TranslatorRegistry()
    translator = _DummyTranslator(format_names={"responses"})

    registry.register(translator)

    assert registry.get(format_name) is translator
