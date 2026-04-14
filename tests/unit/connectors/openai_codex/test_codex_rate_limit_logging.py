"""Tests for OpenAI Codex upstream rate-limit log helpers."""

from __future__ import annotations

import logging

import pytest
from src.connectors.openai_codex.codex_rate_limit_logging import (
    _available_again_iso,
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


def test_available_again_iso_falls_back_when_resets_at_invalid() -> None:
    """Out-of-range ``resets_at`` must not raise; use ``retry_after_seconds``."""
    iso = _available_again_iso(
        resets_at_unix=2**62,
        retry_after_seconds=42.0,
    )
    assert iso is not None
    assert "T" in iso


def test_available_again_iso_returns_none_when_no_valid_hint() -> None:
    assert _available_again_iso(resets_at_unix=2**62, retry_after_seconds=None) is None
    assert _available_again_iso(resets_at_unix=500, retry_after_seconds=None) is None


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


def test_emit_openai_codex_managed_oauth_rate_limit_with_none_upstream_json(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    emit_openai_codex_managed_oauth_rate_limit(
        managed_account_id="acct-2",
        email="b@example.com",
        chatgpt_account_id=None,
        retry_after_seconds=120.0,
        session_id="sess-y",
        upstream_json=None,
    )
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.levelno == logging.WARNING
    assert "acct-2" in rec.message
    assert getattr(rec, "codex_error_type", None) is None
    assert getattr(rec, "plan_type", None) is None
    assert getattr(rec, "limit_window", "") == "short_rolling (~few_hour_window)"


def test_emit_openai_codex_managed_oauth_rate_limit_non_usage_limit_payload(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    emit_openai_codex_managed_oauth_rate_limit(
        managed_account_id="acct-3",
        email=None,
        chatgpt_account_id="cgpt-z",
        retry_after_seconds=None,
        session_id=None,
        upstream_json={"error": {"type": "server_error", "message": "temporary"}},
    )
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert getattr(rec, "codex_error_type", None) is None
    assert "unknown" in getattr(rec, "limit_window", "")
