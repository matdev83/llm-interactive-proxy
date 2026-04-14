"""Tests for OpenAI Codex upstream rate-limit log helpers."""

from __future__ import annotations

import logging

import pytest
from src.connectors.openai_codex.codex_rate_limit_logging import (
    classify_usage_limit_window,
    emit_openai_codex_managed_oauth_rate_limit,
    parse_codex_usage_limit_upstream,
)


def test_parse_codex_usage_limit_upstream_extracts_fields() -> None:
    payload = {
        "error": {
            "type": "usage_limit_reached",
            "message": "The usage limit has been reached",
            "plan_type": "plus",
            "resets_at": 1776358224,
            "resets_in_seconds": 191966,
        }
    }
    parsed = parse_codex_usage_limit_upstream(payload)
    assert parsed is not None
    assert parsed["plan_type"] == "plus"
    assert parsed["resets_in_seconds"] == 191966.0
    assert parsed["resets_at_unix"] == 1776358224
    assert parsed["error_type"] == "usage_limit_reached"


def test_parse_codex_usage_limit_upstream_returns_none_for_other_errors() -> None:
    assert parse_codex_usage_limit_upstream({"error": {"type": "other"}}) is None
    assert parse_codex_usage_limit_upstream(None) is None


@pytest.mark.parametrize(
    ("seconds", "expected_substring"),
    [
        (1800.0, "short_rolling"),
        (30 * 3600.0, "multi_hour"),
        (200_000.0, "extended"),
    ],
)
def test_classify_usage_limit_window(seconds: float, expected_substring: str) -> None:
    assert expected_substring in classify_usage_limit_window(seconds)


def test_emit_openai_codex_managed_oauth_rate_limit_emits_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    emit_openai_codex_managed_oauth_rate_limit(
        managed_account_id="acct-1",
        email="user@example.com",
        chatgpt_account_id="cgpt-9",
        retry_after_seconds=60.0,
        session_id="sess-x",
        upstream_json={
            "error": {
                "type": "usage_limit_reached",
                "message": "The usage limit has been reached",
                "plan_type": "team",
                "resets_at": 1776435084,
                "resets_in_seconds": 268828,
            }
        },
    )
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.WARNING
    assert "acct-1" in rec.message
    assert "user@example.com" in rec.message
    assert "team" in rec.message
    assert getattr(rec, "openai_codex_rate_limit", None) is True
