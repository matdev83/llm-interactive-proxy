"""TDD tests for verbosity on OpenAI Chat Completions and Responses translators."""

from __future__ import annotations

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.translators.openai.request import from_domain_to_openai_request
from src.core.domain.translators.responses.request import (
    from_domain_to_responses_request,
    responses_to_domain_request,
)


def test_openai_chat_translator_includes_top_level_verbosity() -> None:
    request = CanonicalChatRequest(
        model="gpt-5.4-mini",
        messages=[ChatMessage(role="user", content="hi")],
        verbosity="medium",
    )
    payload = from_domain_to_openai_request(request)
    assert payload.get("verbosity") == "medium"


def test_openai_chat_translator_omits_verbosity_when_unset() -> None:
    request = CanonicalChatRequest(
        model="gpt-5.4-mini",
        messages=[ChatMessage(role="user", content="hi")],
    )
    payload = from_domain_to_openai_request(request)
    assert "verbosity" not in payload


def test_responses_translator_injects_text_verbosity() -> None:
    request = CanonicalChatRequest(
        model="gpt-5.4-mini",
        messages=[ChatMessage(role="user", content="hi")],
        verbosity="low",
    )
    payload = from_domain_to_responses_request(request)
    assert payload.get("text") == {"verbosity": "low"}
    # Chat Completions top-level verbosity must not leak onto Responses wire
    assert "verbosity" not in payload


def test_responses_translator_merges_verbosity_into_existing_text() -> None:
    request = CanonicalChatRequest(
        model="gpt-5.4-mini",
        messages=[ChatMessage(role="user", content="hi")],
        verbosity="high",
        extra_body={"text": {"format": {"type": "text"}}},
    )
    payload = from_domain_to_responses_request(request)
    assert payload.get("text") == {
        "format": {"type": "text"},
        "verbosity": "high",
    }
    assert "verbosity" not in payload


def test_responses_translator_preserves_client_text_verbosity_without_canonical() -> (
    None
):
    request = CanonicalChatRequest(
        model="gpt-5.4-mini",
        messages=[ChatMessage(role="user", content="hi")],
        extra_body={"text": {"verbosity": "medium", "format": {"type": "text"}}},
    )
    payload = from_domain_to_responses_request(request)
    assert payload.get("text") == {
        "verbosity": "medium",
        "format": {"type": "text"},
    }


def test_responses_inbound_translator_populates_canonical_verbosity() -> None:
    request = responses_to_domain_request(
        {
            "model": "gpt-5.4-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "text": {"verbosity": "high", "format": {"type": "text"}},
        }
    )

    assert request.verbosity == "high"
    assert request.extra_body is not None
    assert request.extra_body["text"] == {
        "verbosity": "high",
        "format": {"type": "text"},
    }
