"""Tests for Codex request translator TRACE preview helpers."""

from __future__ import annotations

import pytest
from src.connectors._openai_codex_request_translator import (
    CodexRequestTranslator,
    _format_content_preview_for_log,
)
from src.connectors.openai_codex.contracts import MessagePart, ProcessedMessage
from src.core.app.constants.logging_constants import TRACE_LEVEL


def test_format_content_preview_serializes_message_part_list() -> None:
    content = [MessagePart(type="text", text="hello codex")]
    preview = _format_content_preview_for_log(content)
    assert "hello codex" in preview
    assert preview.startswith("[")


def test_format_content_preview_plain_string() -> None:
    preview = _format_content_preview_for_log("short")
    assert "short" in preview


def test_log_message_preview_no_traceback_for_message_parts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    msg = ProcessedMessage(
        role="user",
        content=[MessagePart(type="text", text="x")],
    )
    with caplog.at_level(TRACE_LEVEL):
        CodexRequestTranslator._log_message_preview(msg, "user", canonical=True)
    assert "Traceback" not in caplog.text
    assert "content_preview=" in caplog.text
