#!/usr/bin/env python
"""Verify ZAI connector uses consistent Kilo-Code fingerprint for all clients.

The ZAI coding plan gateway requires specific client identification headers
(Referer, Origin, X-Title, X-KiloCode-Version) to validate the subscription.
All requests must use the Kilo-Code fingerprint regardless of the actual client.

Usage:
    ./.venv/Scripts/python.exe dev/scripts/verify_zai_fingerprint_consistency.py
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from src.connectors.zai_coding_plan import ZaiCodingPlanBackend


def _check_kilo_headers(headers: dict[str, str]) -> None:
    """Assert full Kilo-Code fingerprint is present."""
    assert headers["User-Agent"] == "Kilo-Code/4.111.0", (
        f"Expected Kilo-Code UA, got: {headers.get('User-Agent')}"
    )
    assert headers["Referer"] == "https://kilocode.ai"
    assert headers["Origin"] == "https://kilocode.ai"
    assert headers["HTTP-Referer"] == "https://kilocode.ai"
    assert headers["X-Title"] == "Kilo Code"
    assert headers["X-KiloCode-Version"] == "4.111.0"
    assert "x-llmproxy-loop-guard" not in headers


def test_opencode_fingerprint() -> None:
    """OpenCode client must still get Kilo-Code fingerprint."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    headers = backend.get_headers(identity=None)
    _check_kilo_headers(headers)
    print("PASS: OpenCode client gets Kilo-Code fingerprint")


def test_kilocode_fingerprint() -> None:
    """Kilo-Code client (no agent) gets Kilo-Code headers."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    headers = backend.get_headers(identity=None)
    _check_kilo_headers(headers)
    print("PASS: Kilo-Code client gets Kilo-Code fingerprint")


def test_identity_override_fingerprint() -> None:
    """Identity header overrides must still yield Kilo-Code fingerprint."""
    backend = ZaiCodingPlanBackend(
        client=AsyncMock(),
        config=MagicMock(),
        translation_service=MagicMock(),
    )
    backend.api_key = "test-key"

    from src.core.domain.configuration.app_identity_config import AppIdentityConfig

    identity = AppIdentityConfig.model_validate(
        {
            "title": {"default_value": "Other Client", "passthrough_name": "x-title"},
            "url": {
                "default_value": "https://other.ai",
                "passthrough_name": "http-referer",
            },
            "user_agent": {
                "default_value": "OtherClient/1.0",
                "passthrough_name": "user-agent",
            },
        }
    )

    headers = backend.get_headers(identity=identity)
    _check_kilo_headers(headers)
    print("PASS: Identity overrides still yield Kilo-Code fingerprint")


def main() -> int:
    print("=" * 70)
    print("ZAI FINGERPRINT CONSISTENCY VERIFICATION")
    print("=" * 70)
    print()

    try:
        test_opencode_fingerprint()
        test_kilocode_fingerprint()
        test_identity_override_fingerprint()

        print()
        print("=" * 70)
        print("ALL TESTS PASSED")
        print("=" * 70)
        return 0
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
