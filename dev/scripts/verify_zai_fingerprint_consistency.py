#!/usr/bin/env python
"""Verify ZAI connector fingerprint consistency fix.

Tests that the ZAI connector detects the client agent and uses matching
headers to avoid WAF/429 rejections from fingerprint mismatches.

Usage:
    ./.venv/Scripts/python.exe dev/scripts/verify_zai_fingerprint_consistency.py
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def test_opencode_fingerprint() -> None:
    """OpenCode client should get OpenCode headers, not Kilo-Code."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    # Create request with OpenCode agent
    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        agent="opencode/1.2.26 ai-sdk/provider-utils/3.0.20",
    )

    headers = backend.get_headers(request=request)

    # Should use OpenCode fingerprint
    assert headers["User-Agent"] == "opencode", (
        f"Expected OpenCode UA, got: {headers.get('User-Agent')}"
    )

    # Should NOT have Kilo-Code specific headers
    assert "Referer" not in headers, "OpenCode should not have Referer header"
    assert "Origin" not in headers, "OpenCode should not have Origin header"
    assert "HTTP-Referer" not in headers, "OpenCode should not have HTTP-Referer"
    assert "X-Title" not in headers, "OpenCode should not have X-Title"
    assert "X-KiloCode-Version" not in headers, "OpenCode should not have X-KiloCode-Version"

    print("✅ OpenCode fingerprint: PASS")


def test_kilocode_fingerprint() -> None:
    """Kilo-Code client (or no agent) should get Kilo-Code headers."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    # Create request without OpenCode agent (defaults to Kilo-Code)
    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
    )

    headers = backend.get_headers(request=request)

    # Should use Kilo-Code fingerprint
    assert headers["User-Agent"] == "Kilo-Code/4.111.0", (
        f"Expected Kilo-Code UA, got: {headers.get('User-Agent')}"
    )

    # Should have Kilo-Code specific headers
    assert headers["Referer"] == "https://kilocode.ai"
    assert headers["Origin"] == "https://kilocode.ai"
    assert headers["HTTP-Referer"] == "https://kilocode.ai"
    assert headers["X-Title"] == "Kilo Code"
    assert headers["X-KiloCode-Version"] == "4.111.0"

    print("✅ Kilo-Code fingerprint: PASS")


def test_agent_detection_from_extra_body() -> None:
    """Agent in extra_body should also be detected."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    # Create request with OpenCode agent in extra_body
    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[ChatMessage(role="user", content="test")],
        extra_body={"agent": "opencode/1.0.0"},
    )

    detected = backend._detect_client_agent(request)
    assert detected == "opencode", f"Expected 'opencode', got: {detected}"

    headers = backend.get_headers(request=request)
    assert headers["User-Agent"] == "opencode"

    print("✅ Agent detection from extra_body: PASS")


def main() -> int:
    print("=" * 70)
    print("ZAI FINGERPRINT CONSISTENCY VERIFICATION")
    print("=" * 70)
    print()

    try:
        test_opencode_fingerprint()
        test_kilocode_fingerprint()
        test_agent_detection_from_extra_body()

        print()
        print("=" * 70)
        print("ALL TESTS PASSED ✅")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\n❌ FAIL: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
