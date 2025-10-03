#!/usr/bin/env python3
"""
Simple integration test for reasoning aliases backend integration.
"""

from unittest.mock import MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session


class TestBackendIntegration:
    """Test backend integration with reasoning aliases."""

    @pytest.mark.asyncio
    async def test_reasoning_config_applied_to_request(self):
        """Test that reasoning configuration is applied to backend requests."""
        # Create a mock session with reasoning mode
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with all the parameters using a proper object
        class MockReasoningMode:
            def __init__(self):
                self.temperature = 0.8
                self.top_p = 0.9
                self.reasoning_effort = "high"
                self.thinking_budget = 1000
                self.reasoning_config = {"test": "config"}
                self.gemini_generation_config = {"test": "gemini"}

        reasoning_mode = MockReasoningMode()
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
            temperature=0.5,
            top_p=0.8,
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        # We need to create an instance to call the method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify parameters were applied
        assert updated_request.temperature == 0.8
        assert updated_request.top_p == 0.9
        assert updated_request.reasoning_effort == "high"
        assert updated_request.thinking_budget == 1000
        assert updated_request.reasoning == {"test": "config"}
        assert updated_request.generation_config == {"test": "gemini"}

    @pytest.mark.asyncio
    async def test_prompt_prefix_suffix_applied(self):
        """Test that prompt prefix and suffix are applied to user messages."""
        # Create a mock session with reasoning mode that has prefix/suffix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with prefix/suffix using a proper object
        class MockReasoningMode:
            def __init__(self):
                self.user_prompt_prefix = "PREFIX: "
                self.user_prompt_suffix = " SUFFIX"
                self.temperature = None  # Don't override temperature
                self.top_p = None
                self.reasoning_effort = None
                self.thinking_budget = None
                self.reasoning_config = None
                self.gemini_generation_config = None

        reasoning_mode = MockReasoningMode()

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request with multiple user messages
        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Hello world"),
                ChatMessage(role="assistant", content="Hi there"),
                ChatMessage(role="user", content="How are you?"),
            ],
            temperature=0.5,
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify that user messages have prefix and suffix applied
        user_messages = [msg for msg in updated_request.messages if msg.role == "user"]
        assert len(user_messages) == 2
        assert user_messages[0].content == "PREFIX: Hello world SUFFIX"
        assert user_messages[1].content == "PREFIX: How are you? SUFFIX"

        # Verify that assistant messages are unchanged
        assistant_messages = [
            msg for msg in updated_request.messages if msg.role == "assistant"
        ]
        assert len(assistant_messages) == 1
        assert assistant_messages[0].content == "Hi there"

    @pytest.mark.asyncio
    async def test_no_reasoning_config_unchanged_request(self):
        """Test that requests are unchanged when no reasoning config is present."""
        # Create a mock session with no reasoning mode
        session = MagicMock(spec=Session)
        session.get_reasoning_mode = MagicMock(return_value=None)

        # Create a request
        original_request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
            temperature=0.5,
            top_p=0.8,
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, original_request, session
        )

        # Verify request is unchanged
        assert updated_request.temperature == 0.5
        assert updated_request.top_p == 0.8
        assert updated_request.messages[0].content == "Hello world"


if __name__ == "__main__":
    pytest.main([__file__])
