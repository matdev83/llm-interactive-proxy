from __future__ import annotations

from dataclasses import dataclass

import pytest
from src.core.domain.translation import Translation
from src.core.domain.translators.openrouter_translator import OpenRouterTranslator


@dataclass
class _OpenRouterRequestObject:
    model: str
    messages: list[dict[str, str]]
    top_k: int | None = None
    top_p: float | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stop: list[str] | None = None
    seed: int | None = None
    reasoning_effort: str | None = None
    extra_params: dict[str, object] | None = None
    stream: bool | None = None
    extra_body: dict[str, object] | None = None
    tools: list[dict[str, object]] | None = None
    tool_choice: object | None = None


def test_openrouter_translator_format_names() -> None:
    translator = OpenRouterTranslator()
    assert "openrouter" in set(translator.format_names)


def test_openrouter_translator_to_domain_request_matches_translation_facade_dict() -> (
    None
):
    payload = {
        "model": "openrouter:test-model",
        "messages": [{"role": "user", "content": "Hello"}],
        "top_k": 50,
        "top_p": 0.9,
        "temperature": 0.2,
        "max_tokens": 123,
        "stop": ["\n\n"],
        "seed": 123,
        "reasoning_effort": "high",
        "extra_params": {"foo": "bar"},
        "stream": False,
        "tools": [{"type": "function", "function": {"name": "lookup"}}],
        "tool_choice": "auto",
    }

    translator = OpenRouterTranslator()
    expected = Translation.openrouter_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_openrouter_translator_to_domain_request_matches_translation_facade_object() -> (
    None
):
    payload = _OpenRouterRequestObject(
        model="openrouter:test-model",
        messages=[{"role": "user", "content": "Hello"}],
        top_k=50,
        top_p=0.9,
        temperature=0.2,
        max_tokens=123,
        stop=["\n\n"],
        seed=123,
        reasoning_effort="high",
        extra_params={"foo": "bar"},
        stream=False,
        tools=[{"type": "function", "function": {"name": "lookup"}}],
        tool_choice="auto",
    )

    translator = OpenRouterTranslator()
    expected = Translation.openrouter_to_domain_request(payload).model_dump()
    actual = translator.to_domain_request(payload).model_dump()
    assert actual == expected


def test_openrouter_translator_to_domain_request_requires_model() -> None:
    translator = OpenRouterTranslator()
    with pytest.raises(ValueError, match="Model not found in request"):
        translator.to_domain_request({"messages": [{"role": "user", "content": "x"}]})
