#!/usr/bin/env python3
"""
Tests for reasoning parameter application in backend requests.
"""

from unittest.mock import MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.session import Session


class TestReasoningParameterApplication:
    """Test reasoning parameter application to backend requests."""

    @pytest.mark.asyncio
    async def test_temperature_application(self):
        """Test that temperature is applied from reasoning config."""
        # Create a mock session with reasoning mode that has temperature
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with temperature
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = 0.9
        reasoning_mode.top_p = None
        reasoning_mode.reasoning_effort = None

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request with different temperature
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
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

        # Verify temperature was updated
        assert updated_request.temperature == 0.9

    @pytest.mark.asyncio
    async def test_top_p_application(self):
        """Test that top_p is applied from reasoning config."""
        # Create a mock session with reasoning mode that has top_p
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with top_p
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = None
        reasoning_mode.top_p = 0.8
        reasoning_mode.reasoning_effort = None

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request with different top_p
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            top_p=0.5,
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify top_p was updated
        assert updated_request.top_p == 0.8

    @pytest.mark.asyncio
    async def test_reasoning_effort_application(self):
        """Test that reasoning_effort is applied from reasoning config."""
        # Create a mock session with reasoning mode that has reasoning_effort
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with reasoning_effort
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = None
        reasoning_mode.top_p = None
        reasoning_mode.reasoning_effort = "high"

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            reasoning_effort="medium",
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify reasoning_effort was updated
        assert updated_request.reasoning_effort == "high"

    @pytest.mark.asyncio
    async def test_thinking_budget_application(self):
        """Test that thinking_budget is applied from reasoning config."""
        # Create a mock session with reasoning mode that has thinking_budget
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with thinking_budget
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = None
        reasoning_mode.top_p = None
        reasoning_mode.reasoning_effort = None
        reasoning_mode.thinking_budget = 8192

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            thinking_budget=1024,
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify thinking_budget was updated
        assert updated_request.thinking_budget == 8192

    @pytest.mark.asyncio
    async def test_reasoning_config_application(self):
        """Test that reasoning_config is applied from reasoning config."""
        # Create a mock session with reasoning mode that has reasoning_config
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with reasoning_config
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = None
        reasoning_mode.top_p = None
        reasoning_mode.reasoning_effort = None
        reasoning_mode.thinking_budget = None
        reasoning_mode.reasoning_config = {"max_tokens": 1000, "temperature": 0.9}

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            reasoning={"max_tokens": 500},
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify reasoning_config was updated
        assert updated_request.reasoning == {"max_tokens": 1000, "temperature": 0.9}

    @pytest.mark.asyncio
    async def test_gemini_generation_config_application(self):
        """Test that gemini_generation_config is applied from reasoning config."""
        # Create a mock session with reasoning mode that has gemini_generation_config
        session = MagicMock(spec=Session)

        # Create a mock reasoning mode with gemini_generation_config
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = None
        reasoning_mode.top_p = None
        reasoning_mode.reasoning_effort = None
        reasoning_mode.thinking_budget = None
        reasoning_mode.reasoning_config = None
        reasoning_mode.gemini_generation_config = {"candidate_count": 2, "top_k": 40}

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Hello")],
            generation_config={"candidate_count": 1},
        )

        # Import the backend service method
        from src.core.services.backend_service import BackendService

        # Test the _apply_reasoning_config method
        backend_service = MagicMock()

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify gemini_generation_config was updated
        assert updated_request.generation_config == {"candidate_count": 2, "top_k": 40}
