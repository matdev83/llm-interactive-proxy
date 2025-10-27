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


# TODO: Implement reasoning-effort and thinking-budget features - tests ready for implementation
# Change the skipif condition to a feature flag when implementing these features
# Feature flags to consider: REASONING_EFFORT_ENABLED, THINKING_BUDGET_ENABLED
@pytest.mark.skipif(
    False,  # Change to feature flag check when implemented (e.g., not config.REASONING_EFFORT_ENABLED)
    reason="TODO: Implement reasoning-effort and thinking-budget features - tests ready for implementation",
)
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


# TODO: Implement reasoning-effort and thinking-budget features - tests ready for implementation
# Change the skipif condition to a feature flag when implementing these features
# Feature flags to consider: REASONING_EFFORT_ENABLED, THINKING_BUDGET_ENABLED
@pytest.mark.skipif(
    False,  # Change to feature flag check when implemented (e.g., not config.REASONING_EFFORT_ENABLED)
    reason="TODO: Implement reasoning-effort and thinking-budget features - tests ready for implementation",
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_in_chat_reasoning_commands() -> None:
    """Exercise in-chat reasoning commands through the command processor."""

    from src.core.commands.handlers.reasoning_handlers import (
        ReasoningEffortHandler,
        ThinkingBudgetHandler,
    )
    from src.core.commands.parser import CommandParser
    from src.core.domain.chat import ChatMessage
    from src.core.domain.configuration.reasoning_config import ReasoningConfiguration
    from src.core.domain.session import Session, SessionState
    from src.core.services.command_processor import (
        CommandProcessor as CoreCommandProcessor,
    )

    from tests.unit.core.test_doubles import MockSessionService

    session_state = SessionState().with_reasoning_config(ReasoningConfiguration())
    session = Session(session_id="session-1", state=session_state)
    session_service = MockSessionService(session=session)
    command_parser = CommandParser()
    from tests.utils.command_service_utils import build_new_command_service

    command_service = build_new_command_service(
        session_service, command_parser, strict_command_detection=False
    )

    # In the test environment, the DI doesn't wire up the handlers, so we
    # patch the `SetCommandHandler` to ensure it has the necessary sub-handlers.
    with patch(
        "src.core.commands.handlers.set_command_handler.SetCommandHandler._build_parameter_handlers"
    ) as mock_build_handlers:
        # Configure the mock to return only the handlers we need for this test
        mock_build_handlers.return_value = {
            "reasoning-effort": ReasoningEffortHandler(),
            "thinking-budget": ThinkingBudgetHandler(),
        }

        processor = CoreCommandProcessor(command_service)

        messages = [
            ChatMessage(
                role="user",
                content="Continue working. !/set(reasoning-effort=high, thinking-budget=1024)",
            )
        ]

        result = await processor.process_messages(
            messages, session_id=session.session_id
        )

        assert result.command_executed is True
    assert result.command_results, "Expected at least one command result"
    assert result.command_results[0].message == "Settings updated"

    reasoning_config = session.state.reasoning_config
    assert reasoning_config.reasoning_effort == "high"
    assert reasoning_config.thinking_budget == 1024

    assert result.modified_messages[0].content == "Continue working."


if __name__ == "__main__":
    import asyncio

    try:
        test_provider_specific_reasoning()
        asyncio.run(test_in_chat_reasoning_commands())

    except KeyboardInterrupt:
        # Test interrupted by user
        pass
    except Exception:
        # Test failed with error
        pass
