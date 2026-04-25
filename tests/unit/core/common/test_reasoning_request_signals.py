"""Tests for chat request reasoning / thinking signal extraction."""

from __future__ import annotations

from src.core.common.reasoning_request_signals import (
    chat_request_indicates_reasoning_output,
)
from src.core.domain.chat import ChatMessage, ChatRequest


def test_extra_body_thinking_type_enabled() -> None:
    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
        extra_body={"thinking": {"type": "enabled"}},
    )
    assert chat_request_indicates_reasoning_output(req) is True


def test_reasoning_effort_string_triggers() -> None:
    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
        reasoning_effort="high",
    )
    assert chat_request_indicates_reasoning_output(req) is True


def test_plain_request_false() -> None:
    req = ChatRequest(
        model="m",
        messages=[ChatMessage(role="user", content="hi")],
    )
    assert chat_request_indicates_reasoning_output(req) is False
