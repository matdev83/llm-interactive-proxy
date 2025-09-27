#!/usr/bin/env python3
"""
End-to-end integration test for reasoning aliases functionality.
This test verifies the complete flow from command execution to backend API calls.
"""

from unittest.mock import MagicMock

import pytest

# Suppress Windows ProactorEventLoop ResourceWarnings for this module
pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
from src.core.commands.command import Command
from src.core.commands.handlers.reasoning_aliases import (
    LowReasoningHandler,
    MaxReasoningHandler,
    MediumReasoningHandler,
    NoThinkReasoningHandler,
)
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.session import Session


class TestReasoningAliasesEndToEnd:
    """End-to-end tests for reasoning aliases functionality."""

    @pytest.fixture
    def sample_config(self):
        """Create a sample reasoning aliases configuration."""
        config_data = {
            "reasoning_alias_settings": [
                {
                    "model": "test-model",
                    "modes": {
                        "high": {
                            "max_reasoning_tokens": 32000,
                            "reasoning_effort": "high",
                            "user_prompt_prefix": "Think carefully: ",
                            "user_prompt_suffix": " Show your reasoning.",
                            "temperature": 1.0,
                            "top_p": 1.0,
                        },
                        "medium": {
                            "max_reasoning_tokens": 16000,
                            "reasoning_effort": "medium",
                            "user_prompt_prefix": "Consider this: ",
                            "user_prompt_suffix": "",
                            "temperature": 0.7,
                            "top_p": 0.9,
                        },
                        "low": {
                            "max_reasoning_tokens": 4000,
                            "reasoning_effort": "low",
                            "user_prompt_prefix": "",
                            "user_prompt_suffix": " (brief answer)",
                            "temperature": 0.3,
                            "top_p": 0.5,
                        },
                        "none": {
                            "max_reasoning_tokens": 100,
                            "reasoning_effort": "",
                            "user_prompt_prefix": "",
                            "user_prompt_suffix": "",
                            "temperature": 0.0,
                            "top_p": 0.1,
                        },
                    },
                }
            ]
        }
        return ReasoningAliasesConfig(**config_data)

    @pytest.fixture
    def mock_session(self):
        """Create a mock session."""
        session = MagicMock(spec=Session)
        session.get_model = MagicMock(return_value="test-model")
        session.set_reasoning_mode = MagicMock()
        return session

    @pytest.fixture
    def mock_config_with_reasoning(self, sample_config):
        """Create a mock config with reasoning aliases."""
        config = MagicMock(spec=AppConfig)
        config.reasoning_aliases = sample_config
        return config

    @pytest.mark.asyncio
    async def test_max_command_end_to_end(
        self, mock_session, mock_config_with_reasoning
    ):
        """Test the complete flow for !/max command."""
        # Create command handler
        handler = MaxReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        # Create command
        command = Command(name="max", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert "Reasoning mode set to max" in result.message

        # Verify session method was called with correct mode
        mock_session.set_reasoning_mode.assert_called_once()
        called_mode = mock_session.set_reasoning_mode.call_args[0][0]

        # Verify the mode parameters
        assert called_mode.max_reasoning_tokens == 32000
        assert called_mode.reasoning_effort == "high"
        assert called_mode.temperature == 1.0
        assert called_mode.top_p == 1.0
        assert called_mode.user_prompt_prefix == "Think carefully: "
        assert called_mode.user_prompt_suffix == " Show your reasoning."

    @pytest.mark.asyncio
    async def test_medium_command_end_to_end(
        self, mock_session, mock_config_with_reasoning
    ):
        """Test the complete flow for !/medium command."""
        # Create command handler
        handler = MediumReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        # Create command
        command = Command(name="medium", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert "Reasoning mode set to medium" in result.message

        # Verify session method was called with correct mode
        mock_session.set_reasoning_mode.assert_called_once()
        called_mode = mock_session.set_reasoning_mode.call_args[0][0]

        # Verify the mode parameters
        assert called_mode.max_reasoning_tokens == 16000
        assert called_mode.reasoning_effort == "medium"
        assert called_mode.temperature == 0.7
        assert called_mode.top_p == 0.9
        assert called_mode.user_prompt_prefix == "Consider this: "
        assert called_mode.user_prompt_suffix == ""

    @pytest.mark.asyncio
    async def test_low_command_end_to_end(
        self, mock_session, mock_config_with_reasoning
    ):
        """Test the complete flow for !/low command."""
        # Create command handler
        handler = LowReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        # Create command
        command = Command(name="low", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert "Reasoning mode set to low" in result.message

        # Verify session method was called with correct mode
        mock_session.set_reasoning_mode.assert_called_once()
        called_mode = mock_session.set_reasoning_mode.call_args[0][0]

        # Verify the mode parameters
        assert called_mode.max_reasoning_tokens == 4000
        assert called_mode.reasoning_effort == "low"
        assert called_mode.temperature == 0.3
        assert called_mode.top_p == 0.5
        assert called_mode.user_prompt_prefix == ""
        assert called_mode.user_prompt_suffix == " (brief answer)"

    @pytest.mark.asyncio
    async def test_no_think_command_end_to_end(
        self, mock_session, mock_config_with_reasoning
    ):
        """Test the complete flow for !/no-think command."""
        # Create command handler
        handler = NoThinkReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        # Create command
        command = Command(name="no-think", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert "Reasoning mode set to no-think" in result.message

        # Verify session method was called with correct mode
        mock_session.set_reasoning_mode.assert_called_once()
        called_mode = mock_session.set_reasoning_mode.call_args[0][0]

        # Verify the mode parameters
        assert called_mode.max_reasoning_tokens == 100
        assert called_mode.reasoning_effort == ""
        assert called_mode.temperature == 0.0
        assert called_mode.top_p == 0.1
        assert called_mode.user_prompt_prefix == ""
        assert called_mode.user_prompt_suffix == ""

    @pytest.mark.asyncio
    async def test_complete_flow_with_backend_integration(
        self, mock_config_with_reasoning
    ):
        """Test the complete flow from command to backend request modification."""
        # Step 1: Execute a reasoning command
        session = MagicMock(spec=Session)
        session.get_model = MagicMock(return_value="test-model")
        session.set_reasoning_mode = MagicMock()

        handler = MaxReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        command = Command(name="max", args={})
        result = await handler.handle(command, session)

        # Verify command was successful
        assert result.success is True

        # Get the mode that was set
        called_mode = session.set_reasoning_mode.call_args[0][0]

        # Step 2: Simulate backend request processing
        # Create a request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Solve this math problem")],
            temperature=0.5,
            top_p=0.8,
        )

        # Apply reasoning config (this is what happens in the backend service)
        from src.core.services.backend_service import BackendService

        backend_service = MagicMock()

        # Mock the session to return our mode
        session.get_reasoning_mode = MagicMock(return_value=called_mode)

        # Apply reasoning config
        updated_request = BackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify all parameters were applied correctly
        assert updated_request.temperature == 1.0  # From reasoning mode
        assert updated_request.top_p == 1.0  # From reasoning mode
        assert updated_request.reasoning_effort == "high"  # From reasoning mode

        # Verify prompt modification
        assert (
            updated_request.messages[0].content
            == "Think carefully: Solve this math problem Show your reasoning."
        )

    @pytest.mark.asyncio
    async def test_model_not_found_error_handling(
        self, mock_session, mock_config_with_reasoning
    ):
        """Test error handling when model is not found in config."""
        # Create a session with a model not in the config
        mock_session.get_model = MagicMock(return_value="unknown-model")

        # Create command handler
        handler = MaxReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = (
            mock_config_with_reasoning
        )

        # Create command
        command = Command(name="max", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify failure
        assert result.success is False
        assert "No reasoning settings found for model unknown-model" in result.message

    @pytest.mark.asyncio
    async def test_no_config_error_handling(self, mock_session):
        """Test error handling when no reasoning config is available."""
        # Create command handler
        handler = MaxReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = None

        # Create command
        command = Command(name="max", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify failure
        assert result.success is False
        assert "Reasoning aliases are not configured" in result.message
