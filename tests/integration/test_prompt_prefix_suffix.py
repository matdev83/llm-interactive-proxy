#!/usr/bin/env python3
"""
Tests for prompt prefix/suffix functionality in reasoning aliases.
"""

from unittest.mock import MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session


class TestPromptPrefixSuffix:
    """Test prompt prefix and suffix functionality."""

    @pytest.mark.asyncio
    async def test_string_content_prefix_suffix(self):
        """Test that prefix and suffix are applied to string content."""
        # Create a mock session with reasoning mode that has prefix/suffix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with prefix/suffix using a proper object
        class MockReasoningMode:
            def __init__(self):
                self.user_prompt_prefix = "Think carefully: "
                self.user_prompt_suffix = " Show your work."
                self.temperature = None  # Don't override temperature
                self.top_p = None
                self.reasoning_effort = None
                self.thinking_budget = None
                self.reasoning_config = None
                self.gemini_generation_config = None

        reasoning_mode = MockReasoningMode()
        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request with string content
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Solve 2+2")],
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

        # Verify that prefix and suffix are applied
        assert (
            updated_request.messages[0].content
            == "Think carefully: Solve 2+2 Show your work."
        )

    @pytest.mark.asyncio
    async def test_empty_prefix_suffix(self):
        """Test that empty prefix/suffix don't affect content."""
        # Create a mock session with reasoning mode that has empty prefix/suffix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with empty prefix/suffix using a proper object
        class MockReasoningMode:
            def __init__(self):
                self.user_prompt_prefix = ""
                self.user_prompt_suffix = ""
                self.temperature = None  # Don't override temperature
                self.top_p = None
                self.reasoning_effort = None
                self.thinking_budget = None
                self.reasoning_config = None
                self.gemini_generation_config = None

        reasoning_mode = MockReasoningMode()

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
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

        # Verify content is unchanged
        assert updated_request.messages[0].content == "Hello world"

    @pytest.mark.asyncio
    async def test_none_prefix_suffix(self):
        """Test that None prefix/suffix don't affect content."""
        # Create a mock session with reasoning mode that has None prefix/suffix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with None prefix/suffix using a proper object
        class MockReasoningMode:
            def __init__(self):
                self.user_prompt_prefix = None
                self.user_prompt_suffix = None
                self.temperature = None  # Don't override temperature
                self.top_p = None
                self.reasoning_effort = None
                self.thinking_budget = None
                self.reasoning_config = None
                self.gemini_generation_config = None

        reasoning_mode = MockReasoningMode()

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello world")],
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

        # Verify content is unchanged
        assert updated_request.messages[0].content == "Hello world"

    @pytest.mark.asyncio
    async def test_only_prefix_no_suffix(self):
        """Test that only prefix is applied when suffix is None."""
        # Create a mock session with reasoning mode that has only prefix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with only prefix
        reasoning_mode = MagicMock()
        reasoning_mode.user_prompt_prefix = "Question: "
        reasoning_mode.user_prompt_suffix = None
        reasoning_mode.temperature = None  # Don't override temperature

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="What is 2+2?")],
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

        # Verify only prefix is applied
        assert updated_request.messages[0].content == "Question: What is 2+2?"

    @pytest.mark.asyncio
    async def test_only_suffix_no_prefix(self):
        """Test that only suffix is applied when prefix is None."""
        # Create a mock session with reasoning mode that has only suffix
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with only suffix
        reasoning_mode = MagicMock()
        reasoning_mode.user_prompt_prefix = None
        reasoning_mode.user_prompt_suffix = " (be concise)"
        reasoning_mode.temperature = None  # Don't override temperature

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Explain photosynthesis")],
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

        # Verify only suffix is applied
        assert (
            updated_request.messages[0].content == "Explain photosynthesis (be concise)"
        )
