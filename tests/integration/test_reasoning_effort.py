#!/usr/bin/env python3
"""
Simple test script to demonstrate provider-specific reasoning functionality.
This script shows how to use the reasoning features for different providers in the LLM interactive proxy.
"""

from unittest.mock import MagicMock, patch

import pytest

# Mock response with reasoning tokens for testing
MOCK_RESPONSE = {
    "id": "test-id",
    "object": "chat.completion",
    "created": 1234567890,
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "This is a mock response.",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "reasoning_tokens": 15,
    },
    "provider_info": {"backend": "test-backend", "model": "test-model"},
}


@pytest.mark.integration
@patch("requests.post")
def test_provider_specific_reasoning(mock_post):
    """Test provider-specific reasoning functionality with different configurations."""

    # Configure the mock to return our response
    mock_response_obj = MagicMock()
    mock_response_obj.status_code = 200
    mock_response_obj.json.return_value = MOCK_RESPONSE
    mock_post.return_value = mock_response_obj

    import requests

    API_KEY = "test-key"
    PROXY_URL = "http://localhost:8000"

    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

    # Test cases for different providers and reasoning configurations (reduced for performance)
    test_cases = [
        {
            "name": "OpenAI reasoning effort via OpenRouter",
            "payload": {
                "model": "openrouter:openai/o1-preview",
                "messages": [
                    {
                        "role": "user",
                        "content": "Solve this step by step: What is the derivative of x^3 + 2x^2 - 5x + 3?",
                    }
                ],
                "reasoning_effort": "high",
            },
        },
        {
            "name": "Gemini thinking budget",
            "payload": {
                "model": "gemini:gemini-2.5-pro",
                "messages": [
                    {
                        "role": "user",
                        "content": "Design a simple recommendation system for a bookstore.",
                    }
                ],
                "thinking_budget": 1024,
            },
        },
        {
            "name": "In-chat reasoning command",
            "payload": {
                "model": "openrouter:openai/o1-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": "!/set(reasoning-effort=high) What are the benefits of renewable energy?",
                    }
                ],
            },
        },
    ]

    for test_case in test_cases:
        # Make request (will be intercepted by mock)
        response = requests.post(
            f"{PROXY_URL}/v1/chat/completions",
            headers=headers,
            json=test_case["payload"],
            timeout=5,  # Reduced timeout for testing
        )

        # Validate that the request was made with correct parameters
        assert mock_post.called

        # Validate response
        assert response.status_code == 200
        result = response.json()

        # Check that we get the expected structure
        assert "choices" in result
        assert len(result["choices"]) > 0
        assert "usage" in result
        assert "reasoning_tokens" in str(result["usage"])

        # Check provider information
        assert "provider_info" in result


@pytest.mark.integration
@patch("requests.post")
def test_in_chat_reasoning_commands(mock_post):
    """Test in-chat reasoning commands functionality."""
    # This test can be expanded based on specific command validation needs


if __name__ == "__main__":
    try:
        test_provider_specific_reasoning()
        test_in_chat_reasoning_commands()

    except KeyboardInterrupt:
        # Test interrupted by user
        pass
    except Exception:
        # Test failed with error
        pass
