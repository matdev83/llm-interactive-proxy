# Fingerprint Consistency Regression Tests for ZAI Coding Plan Connector
# These tests ensure consistent client fingerprinting to avoid WAF/429 rejections.

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def test_detect_client_agent_opencode() -> None:
    """OpenCode agent in request.agent should be detected."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )

    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
    )

    assert backend._detect_client_agent(request) == "opencode"


def test_detect_client_agent_kilocode_default() -> None:
    """No agent or non-opencode agent should default to Kilo-Code."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )

    # No agent
    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
    )
    assert backend._detect_client_agent(request) == "kilocode"

    # Different agent
    request2 = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        agent="cline/1.0.0",
    )
    assert backend._detect_client_agent(request2) == "kilocode"


def test_detect_client_agent_from_extra_body() -> None:
    """OpenCode agent in extra_body should also be detected."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )

    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        extra_body={"agent": "opencode/1.0.0"},
    )

    assert backend._detect_client_agent(request) == "opencode"


def test_get_headers_opencode_fingerprint() -> None:
    """OpenCode requests should get minimal headers without Kilo-Code metadata."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"

    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
    )

    headers = backend.get_headers(request=request)

    # Should use OpenCode fingerprint
    assert headers["User-Agent"] == "opencode"

    # Should NOT have Kilo-Code specific headers
    assert "Referer" not in headers
    assert "Origin" not in headers
    assert "HTTP-Referer" not in headers
    assert "X-Title" not in headers
    assert "X-KiloCode-Version" not in headers


def test_get_headers_kilocode_fingerprint() -> None:
    """Non-OpenCode requests should get full Kilo-Code fingerprint."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(), config=MagicMock(), translation_service=MagicMock()
    )
    backend.api_key = "NOT-A-REAL-KEY-just-for-testing"

    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
    )

    headers = backend.get_headers(request=request)

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
