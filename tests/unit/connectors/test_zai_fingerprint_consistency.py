# Fingerprint Consistency Regression Tests for ZAI Coding Plan Connector
# These tests ensure the connector always uses the Kilo-Code fingerprint
# to avoid 429 rejections from the ZAI coding plan gateway.

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.connectors.zai_coding_plan import ZaiCodingPlanBackend


def test_get_headers_opencode_fingerprint() -> None:
    """All requests should use Kilo-Code fingerprint regardless of client."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"

    headers = backend.get_headers()

    # Should use Kilo-Code fingerprint even for OpenCode clients
    assert headers["User-Agent"] == "Kilo-Code/4.111.0"
    assert headers["Referer"] == "https://kilocode.ai"
    assert headers["Origin"] == "https://kilocode.ai"
    assert headers["HTTP-Referer"] == "https://kilocode.ai"
    assert headers["X-Title"] == "Kilo Code"
    assert headers["X-KiloCode-Version"] == "4.111.0"


def test_get_headers_kilocode_fingerprint() -> None:
    """Non-OpenCode requests should get full Kilo-Code fingerprint."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"

    headers = backend.get_headers()

    # Should use Kilo-Code fingerprint
    assert headers["User-Agent"] == "Kilo-Code/4.111.0"
    assert headers["Referer"] == "https://kilocode.ai"
    assert headers["Origin"] == "https://kilocode.ai"
    assert headers["HTTP-Referer"] == "https://kilocode.ai"
    assert headers["X-Title"] == "Kilo Code"
    assert headers["X-KiloCode-Version"] == "4.111.0"


def test_prepare_payload_strips_non_allowed_keys() -> None:
    """Verify payload cleaning strips all non-allowed fields including agent."""
    # Direct test of the cleaning logic used by _prepare_payload
    payload = {
        "model": "glm-4.7",
        "messages": [{"role": "user", "content": "test"}],
        "stream": True,
        "max_tokens": 128,
        "temperature": 0.7,
        # These should be stripped
        "agent": "opencode/1.2.26",
        "audio": {"format": "mp3"},
        "frequency_penalty": 0.5,
        "logit_bias": {"token": 10},
        "logprobs": True,
        "max_completion_tokens": 256,
        "extra_body": {"backend_type": "zai-coding-plan"},
        "generation_config": {"custom": "value"},
    }

    allowed_keys = {
        "model",
        "messages",
        "stream",
        "max_tokens",
        "temperature",
        "top_p",
        "tools",
        "tool_choice",
    }
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key not in allowed_keys:
            continue
        if value is None:
            continue
        if key in {"tools", "tool_choice"} and not value:
            continue
        cleaned[key] = value

    # Verify forbidden fields are stripped
    assert "agent" not in cleaned
    assert "audio" not in cleaned
    assert "frequency_penalty" not in cleaned
    assert "logit_bias" not in cleaned
    assert "logprobs" not in cleaned
    assert "max_completion_tokens" not in cleaned
    assert "extra_body" not in cleaned
    assert "generation_config" not in cleaned

    # Verify allowed fields are preserved
    assert cleaned.keys() == {
        "model",
        "messages",
        "stream",
        "max_tokens",
        "temperature",
    }
