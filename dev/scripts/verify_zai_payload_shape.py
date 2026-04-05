#!/usr/bin/env python
"""Diagnostic script to verify ZAI connector payload shape.

This script creates a mock ZAI backend and captures the actual payload
that would be sent to the ZAI API after _prepare_payload cleaning.

Usage:
    ./.venv/Scripts/python.exe dev/scripts/verify_zai_payload_shape.py
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from src.connectors.zai_coding_plan import ZaiCodingPlanBackend
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


async def main() -> int:
    # Create a mock backend
    mock_client = AsyncMock()
    mock_config = MagicMock()
    mock_translation_service = MagicMock()

    backend = ZaiCodingPlanBackend(
        client=mock_client,
        config=mock_config,
        translation_service=mock_translation_service,
    )

    # Set up the backend (mimicking initialize())
    backend.api_key = "test-key-not-real"
    backend.api_base_url = "https://api.z.ai/api/coding/paas/v4"
    backend.available_models = ["glm-4.7"]
    backend._provider_models = {"glm-4.7"}
    backend._model_discovery_succeeded = True
    backend._max_tokens_limit = 200000
    backend._default_max_tokens = 8192

    # Create a CanonicalChatRequest with extra fields that should be stripped
    request = CanonicalChatRequest(
        model="glm-4.7",
        messages=[
            ChatMessage(role="system", content="You are a test assistant."),
            ChatMessage(role="user", content="Hello"),
        ],
        stream=True,
        max_tokens=128,
        temperature=0.7,
        # These fields should be stripped by _prepare_payload
        agent="test-agent/1.0",
        audio={"format": "mp3"},
        frequency_penalty=0.5,
        logit_bias={"token": 10},
        logprobs=True,
        max_completion_tokens=256,
        extra_body={
            "backend_type": "zai-coding-plan",
            "session_id": "test-session",
        },
        generation_config={"custom": "value"},
    )

    # Mock the translation service to return a realistic OpenAI payload
    def mock_from_domain_request(req, format):
        """Simulate what the translation service returns."""
        payload = {
            "model": req.model,
            "messages": [m.model_dump(exclude_none=True) for m in req.messages],
            "stream": req.stream,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            # Translation service might include some of these
            "frequency_penalty": req.frequency_penalty,
            "logprobs": req.logprobs,
            "max_completion_tokens": req.max_completion_tokens,
        }
        # Filter out None values (like the real translator does)
        return {k: v for k, v in payload.items() if v is not None}

    mock_translation_service.from_domain_request.side_effect = mock_from_domain_request

    # Call _prepare_payload
    payload = await backend._prepare_payload(request, request.messages, "glm-4.7")

    print("=" * 70)
    print("ZAI CONNECTOR PAYLOAD DIAGNOSTIC")
    print("=" * 70)
    print("\nInput CanonicalChatRequest fields:")
    print(f"  - agent: {request.agent}")
    print(f"  - audio: {request.audio}")
    print(f"  - frequency_penalty: {request.frequency_penalty}")
    print(f"  - logit_bias: {request.logit_bias}")
    print(f"  - logprobs: {request.logprobs}")
    print(f"  - max_completion_tokens: {request.max_completion_tokens}")
    print(f"  - extra_body: {request.extra_body}")
    print(f"  - generation_config: {request.generation_config}")

    print("\nActual HTTP payload after _prepare_payload cleaning:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))

    print("\nPayload keys:", sorted(payload.keys()))

    # Check for forbidden fields
    forbidden_in_payload = {
        "agent",
        "audio",
        "extra_body",
        "frequency_penalty",
        "generation_config",
        "logit_bias",
        "logprobs",
        "max_completion_tokens",
        "backend_type",
        "session_id",
    }
    found_forbidden = forbidden_in_payload.intersection(payload.keys())

    if found_forbidden:
        print(f"\n❌ FAIL: Found forbidden keys in payload: {sorted(found_forbidden)}")
        return 1
    else:
        print("\n✅ PASS: No forbidden keys in payload")
        print("   Only allowed keys present:", sorted(payload.keys()))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
