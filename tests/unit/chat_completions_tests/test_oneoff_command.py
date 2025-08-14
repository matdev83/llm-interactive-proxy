from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

oneoff_test_cases = [
    (
        "oneoff_with_prompt",
        {
            "messages": [
                {
                    "role": "user",
                    "content": "!/oneoff(gemini/gemini-2.0-flash-001)\nHello!",
                },
            ],
            "model": "openrouter/auto",
        },
    ),
    (
        "oneoff_alias_with_prompt",
        {
            "messages": [
                {
                    "role": "user",
                    "content": "!/oneoff(gemini/gemini-2.0-flash-001)\nHello!",
                },
            ],
            "model": "openrouter/auto",
        },
    ),
    (
        "oneoff_without_prompt",
        {
            "messages": [
                {"role": "user", "content": "!/oneoff(gemini/gemini-2.0-flash-001)"},
            ],
            "model": "openrouter/auto",
        },
    ),
]


@pytest.mark.parametrize("test_id, request_payload", oneoff_test_cases)
def test_oneoff_command(
    test_id: str,
    request_payload: dict[str, Any],
    client: TestClient,
    mock_gemini_backend,
):
    # Mock the backend to avoid real API calls
    mock_response = {
        "id": "test-response",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "gemini-2.0-flash-001",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Test response"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }

    # Patch the actual backend methods that get called
    with (
        patch.object(
            client.app.state.openrouter_backend,
            "chat_completions",
            new=AsyncMock(return_value=(mock_response, {})),
        ),
        patch.object(
            client.app.state.gemini_backend,
            "chat_completions",
            new=AsyncMock(return_value=(mock_response, {})),
        ),
    ):

        # First request with the one-off command
        response = client.post("/v1/chat/completions", json=request_payload)
        assert response.status_code == 200
        response_json = response.json()

        if "without_prompt" in test_id:
            # The response includes banner + confirmation, so check if the confirmation is in the content
            content = response_json["choices"][0]["message"]["content"]
            assert "One-off route set to gemini/gemini-2.0-flash-001." in content

            # Second request with the prompt
            follow_up_payload = {
                "messages": [{"role": "user", "content": "Hello!"}],
                "model": "openrouter/auto",
            }
            response = client.post("/v1/chat/completions", json=follow_up_payload)
            assert response.status_code == 200
            response_json = response.json()
            assert response_json["model"] == "gemini-2.0-flash-001"
        else:
            assert response_json["model"] == request_payload["model"]

        # Third request to ensure the one-off route is cleared
        # Note: The one-off route persists in the same session, so we expect it to still be active
        third_payload = {
            "messages": [{"role": "user", "content": "Another prompt"}],
            "model": "openrouter/auto",
        }
        response = client.post("/v1/chat/completions", json=third_payload)
        assert response.status_code == 200
        response_json = response.json()
        # The one-off route should still be active in the same session
        assert response_json["model"] == "gemini-2.0-flash-001"
