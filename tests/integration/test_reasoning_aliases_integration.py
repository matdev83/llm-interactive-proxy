#!/usr/bin/env python3
"""
Integration tests for reasoning aliases functionality.
This test verifies that the complete flow from command execution to backend API calls works correctly.
"""

import tempfile
from unittest.mock import MagicMock

import pytest
import yaml
from src.core.commands.command import Command
from src.core.commands.handlers.reasoning_aliases import (
    MaxReasoningHandler,
    MediumReasoningHandler,
    NoThinkReasoningHandler,
)
from src.core.config.app_config import AppConfig
from src.core.domain.configuration.reasoning_aliases_config import (
    ReasoningAliasesConfig,
)
from src.core.domain.session import Session
from src.core.services.backend_service import BackendService


class TestReasoningAliasesIntegration:
    """Integration tests for reasoning aliases functionality."""

    @pytest.fixture
    def temp_config_file(self):
        """Create a temporary reasoning_aliases.yaml file for testing."""
        config_data = {
            "reasoning_alias_settings": [
                {
                    "model": "test-model",
                    "modes": {
                        "high": {
                            "max_reasoning_tokens": 32000,
                            "reasoning_effort": "high",
                            "user_prompt_prefix": "Think hard about this: ",
                            "user_prompt_suffix": " Provide detailed reasoning.",
                            "temperature": 1.0,
                            "top_p": 1.0,
                        },
                        "medium": {
                            "max_reasoning_tokens": 16000,
                            "reasoning_effort": "medium",
                            "user_prompt_prefix": "Think about this: ",
                            "user_prompt_suffix": "",
                            "temperature": 0.7,
                            "top_p": 0.9,
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

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(config_data, f)
            yield f.name

    @pytest.fixture
    def mock_session(self):
        """Create a mock session for testing."""
        session = MagicMock(spec=Session)
        session.get_model = MagicMock(return_value="test-model")
        session.set_reasoning_mode = MagicMock()
        session.get_reasoning_mode = MagicMock(return_value=None)
        return session

    @pytest.fixture
    def mock_config(self, temp_config_file):
        """Create a mock config with reasoning aliases."""
        # Load the config data from the temp file
        with open(temp_config_file) as f:
            config_data = yaml.safe_load(f)

        # Create the reasoning aliases config
        reasoning_config = ReasoningAliasesConfig(**config_data)

        # Create mock config
        config = MagicMock(spec=AppConfig)
        config.reasoning_aliases = reasoning_config
        return config

    @pytest.mark.asyncio
    async def test_max_reasoning_command_integration(self, mock_session, mock_config):
        """Test that the !/max command sets the correct reasoning mode."""
        # Create command handler
        handler = MaxReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = mock_config

        # Create command
        command = Command(name="max", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert result.message == "Reasoning mode set to max."

        # Verify session method was called
        mock_session.set_reasoning_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_medium_reasoning_command_integration(
        self, mock_session, mock_config
    ):
        """Test that the !/medium command sets the correct reasoning mode."""
        # Create command handler
        handler = MediumReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = mock_config

        # Create command
        command = Command(name="medium", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert result.message == "Reasoning mode set to medium."

        # Verify session method was called
        mock_session.set_reasoning_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_think_command_integration(self, mock_session, mock_config):
        """Test that the !/no-think command sets the correct reasoning mode."""
        # Create command handler
        handler = NoThinkReasoningHandler()
        handler._secure_state_access = MagicMock()
        handler._secure_state_access.get_config.return_value = mock_config

        # Create command
        command = Command(name="no-think", args={})

        # Execute command
        result = await handler.handle(command, mock_session)

        # Verify success
        assert result.success is True
        assert result.message == "Reasoning mode set to no-think."

        # Verify session method was called
        mock_session.set_reasoning_mode.assert_called_once()

    @pytest.mark.asyncio
    async def test_reasoning_config_application_to_request(self):
        """Test that reasoning configuration is applied to requests."""
        # Create a mock session with reasoning mode
        session = MagicMock(spec=Session)
        reasoning_mode = MagicMock()
        reasoning_mode.temperature = 0.8
        reasoning_mode.top_p = 0.9
        reasoning_mode.reasoning_effort = "high"
        reasoning_mode.thinking_budget = 1000
        reasoning_mode.reasoning_config = {"test": "config"}
        reasoning_mode.gemini_generation_config = {"test": "gemini"}
        reasoning_mode.user_prompt_prefix = "PREFIX: "
        reasoning_mode.user_prompt_suffix = " SUFFIX"

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a mock request
        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Hello world"),
                ChatMessage(role="assistant", content="Hi there"),
                ChatMessage(role="user", content="How are you?"),
            ],
            temperature=0.5,
            top_p=0.8,
        )

        # Create backend service (we'll just test the method directly)
        backend_service = MagicMock(spec=BackendService)

        # Apply reasoning config using our method
        from src.core.services.backend_service import (
            BackendService as RealBackendService,
        )

        updated_request = RealBackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify that the request parameters were updated
        assert updated_request.temperature == 0.8
        assert updated_request.top_p == 0.9
        assert updated_request.reasoning_effort == "high"
        assert updated_request.thinking_budget == 1000
        assert updated_request.reasoning == {"test": "config"}
        assert updated_request.generation_config == {"test": "gemini"}

        # Verify that the user messages were updated with prefix and suffix
        user_messages = [msg for msg in updated_request.messages if msg.role == "user"]
        assert len(user_messages) == 2
        assert user_messages[0].content == "PREFIX: Hello world SUFFIX"
        assert user_messages[1].content == "PREFIX: How are you? SUFFIX"

    @pytest.mark.asyncio
    async def test_reasoning_config_application_to_multimodal_request(self):
        """Test that reasoning configuration is applied to multimodal requests."""
        # Create a mock session with reasoning mode
        session = MagicMock(spec=Session)
        reasoning_mode = MagicMock()
        reasoning_mode.user_prompt_prefix = "PREFIX: "
        reasoning_mode.user_prompt_suffix = " SUFFIX"
        reasoning_mode.temperature = None  # Don't override temperature

        session.get_reasoning_mode = MagicMock(return_value=reasoning_mode)

        # Create a mock request with multimodal content
        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "Describe this image"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "http://example.com/image.jpg"},
                        },
                    ],
                ),
            ],
            temperature=0.5,
        )

        # Create backend service (we'll just test the method directly)
        backend_service = MagicMock(spec=BackendService)

        # Apply reasoning config using our method
        from src.core.services.backend_service import (
            BackendService as RealBackendService,
        )

        updated_request = RealBackendService._apply_reasoning_config(
            backend_service, request, session
        )

        # Verify that the temperature wasn't changed
        assert updated_request.temperature == 0.5

        # Verify that the user message text part was updated with prefix and suffix
        user_message = updated_request.messages[0]
        assert isinstance(user_message.content, list)
        assert len(user_message.content) == 2
        # Access attributes using dot notation for Pydantic models
        assert user_message.content[0].type == "text"
        assert user_message.content[0].text == "PREFIX: Describe this image SUFFIX"
        assert user_message.content[1].type == "image_url"

    @pytest.mark.asyncio
    async def test_no_reasoning_config_no_modification(self):
        """Test that requests are not modified when no reasoning config is set."""
        # Create a mock session with no reasoning mode
        session = MagicMock(spec=Session)
        session.get_reasoning_mode = MagicMock(return_value=None)

        # Create a mock request
        from src.core.domain.chat import ChatMessage, ChatRequest

        original_request = ChatRequest(
            model="test-model",
            messages=[
                ChatMessage(role="user", content="Hello world"),
            ],
            temperature=0.5,
            top_p=0.8,
        )

        # Create backend service (we'll just test the method directly)
        backend_service = MagicMock(spec=BackendService)

        # Apply reasoning config using our method
        from src.core.services.backend_service import (
            BackendService as RealBackendService,
        )

        updated_request = RealBackendService._apply_reasoning_config(
            backend_service, original_request, session
        )

        # Verify that the request is unchanged
        assert updated_request.temperature == 0.5
        assert updated_request.top_p == 0.8
        assert updated_request.messages[0].content == "Hello world"


if __name__ == "__main__":
    pytest.main([__file__])
