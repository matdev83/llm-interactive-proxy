"""
Tests for RedactionMiddleware to ensure prompt redaction and command filtering.
"""

from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.redaction_middleware import RedactionMiddleware


@pytest.mark.asyncio
async def test_redaction_middleware_redacts_text_and_parts() -> None:
    """Verify that secrets and proxy commands are removed from different content shapes."""
    # Arrange
    api_keys = ["sk-TESTSECRET1234567890"]
    mw = RedactionMiddleware(api_keys=api_keys, command_prefix="!/")

    # Request includes both string content and list-of-parts content
    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(
                role="user",
                content=f"Use {api_keys[0]} and !/hello now",
            ),
            ChatMessage(
                role="user",
                content=[
                    {"type": "text", "text": f"Another {api_keys[0]} here"},
                    {"type": "text", "text": "and a !/help command"},
                ],
            ),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert
    # First message (string content) got redacted and command removed
    first = processed.messages[0].content
    assert isinstance(first, str)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in first
    assert "!/hello" not in first

    # Second message (list of parts) got redacted and commands removed
    second = processed.messages[1].content
    assert isinstance(second, list)
    texts = []
    for p in second:
        if hasattr(p, "text"):
            texts.append(p.text)
        elif isinstance(p, dict) and "text" in p:
            texts.append(p["text"])
    combined = " ".join(t for t in texts if t)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in combined
    assert "!/help" not in combined
