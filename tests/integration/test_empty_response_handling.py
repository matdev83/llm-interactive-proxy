"""
Integration tests for empty response handling feature.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.config.app_config import AppConfig, EmptyResponseConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.empty_response_middleware import EmptyResponseRetryException
from src.core.services.request_processor_service import RequestProcessor


class TestEmptyResponseHandlingIntegration:
    """Integration tests for empty response handling."""

    @pytest.fixture
    def app_config_with_empty_response(self):
        """Create app config with empty response handling enabled."""
        config = AppConfig()
        config.empty_response = EmptyResponseConfig(enabled=True, max_retries=1)
        return config

    @pytest.fixture
    def app_config_disabled_empty_response(self):
        """Create app config with empty response handling disabled."""
        config = AppConfig()
        config.empty_response = EmptyResponseConfig(enabled=False, max_retries=1)
        return config

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for RequestProcessor."""
        command_processor = AsyncMock()
        backend_processor = AsyncMock()
        session_service = AsyncMock()
        response_processor = AsyncMock()
        session_resolver = AsyncMock()

        # Setup default behaviors
        command_processor.process_messages.return_value = MagicMock(
            command_executed=False, modified_messages=None
        )

        session_service.get_session.return_value = MagicMock(
            history=[],
            state=MagicMock(
                backend_config=MagicMock(backend_type="test", model="test-model"),
                project=None,
            ),
        )
        session_service.update_session.return_value = None

        session_resolver.resolve_session_id.return_value = "test-session"

        return {
            "command_processor": command_processor,
            "backend_processor": backend_processor,
            "session_service": session_service,
            "response_processor": response_processor,
            "session_resolver": session_resolver,
        }

    @pytest.mark.asyncio
    async def test_empty_response_retry_mechanism(self, mock_dependencies):
        """Test that empty responses trigger retry with recovery prompt."""
        # Setup mocks
        deps = mock_dependencies

        # First call returns empty response, second call returns valid response
        empty_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": ""}}]}
        )
        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        deps["backend_processor"].process_backend_request.side_effect = [
            empty_response,
            valid_response,
        ]

        # Response processor should detect empty response and raise retry exception
        deps["response_processor"].process_response.side_effect = [
            EmptyResponseRetryException(
                recovery_prompt="Please provide a valid response",
                session_id="test-session",
                retry_count=1,
            ),
            ProcessedResponse(content="Valid response"),
        ]

        # Create request processor
        processor = RequestProcessor(**deps)

        # Create test request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend processor was called twice (original + retry)
        assert deps["backend_processor"].process_backend_request.call_count == 2

        # Verify that the retry request includes the recovery prompt
        retry_call = deps["backend_processor"].process_backend_request.call_args_list[1]
        retry_request = retry_call[1]["request"]  # keyword argument

        # Check that recovery prompt was added to messages
        assert len(retry_request.messages) == 2  # original + recovery prompt
        assert "valid response" in retry_request.messages[1].content.lower()

        # Verify final result is the valid response
        assert result == valid_response

    @pytest.mark.asyncio
    async def test_non_empty_response_no_retry(self, mock_dependencies):
        """Test that non-empty responses don't trigger retry."""
        # Setup mocks
        deps = mock_dependencies

        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )
        deps["backend_processor"].process_backend_request.return_value = valid_response
        deps["response_processor"].process_response.return_value = ProcessedResponse(
            content="Valid response"
        )

        # Create request processor
        processor = RequestProcessor(**deps)

        # Create test request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend processor was called only once
        assert deps["backend_processor"].process_backend_request.call_count == 1

        # Verify final result is the valid response
        assert result == valid_response

    @pytest.mark.asyncio
    async def test_streaming_response_bypass(self, mock_dependencies):
        """Test that streaming responses bypass empty response detection."""
        # Setup mocks
        deps = mock_dependencies

        streaming_response = ResponseEnvelope(content="streaming data")
        deps["backend_processor"].process_backend_request.return_value = (
            streaming_response
        )

        # Create request processor
        processor = RequestProcessor(**deps)

        # Create test streaming request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=True,  # Streaming request
        )
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend processor was called only once
        assert deps["backend_processor"].process_backend_request.call_count == 1

        # Verify response processor was not called for streaming
        deps["response_processor"].process_response.assert_not_called()

        # Verify final result is the streaming response
        assert result == streaming_response

    @pytest.mark.asyncio
    async def test_response_with_tool_calls_no_retry(self, mock_dependencies):
        """Test that responses with tool calls don't trigger retry even if content is empty."""
        # Setup mocks
        deps = mock_dependencies

        # Response with empty content but tool calls
        response_with_tools = ResponseEnvelope(
            content={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [{"function": {"name": "test_function"}}],
                        }
                    }
                ]
            }
        )
        deps["backend_processor"].process_backend_request.return_value = (
            response_with_tools
        )

        # Response processor should not detect this as empty due to tool calls
        deps["response_processor"].process_response.return_value = ProcessedResponse(
            content="",
            metadata={"tool_calls": [{"function": {"name": "test_function"}}]},
        )

        # Create request processor
        processor = RequestProcessor(**deps)

        # Create test request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend processor was called only once (no retry)
        assert deps["backend_processor"].process_backend_request.call_count == 1

        # Verify final result
        assert result == response_with_tools

    @pytest.mark.asyncio
    @patch("builtins.open")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_recovery_prompt_loaded_from_file(
        self, mock_exists, mock_open, mock_dependencies
    ):
        """Test that recovery prompt is loaded from the config file."""
        # Setup file mock
        mock_file_content = "Custom recovery prompt from file"
        mock_open.return_value.__enter__.return_value.read.return_value = (
            mock_file_content
        )

        # Setup mocks
        deps = mock_dependencies

        empty_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": ""}}]}
        )
        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        deps["backend_processor"].process_backend_request.side_effect = [
            empty_response,
            valid_response,
        ]

        deps["response_processor"].process_response.side_effect = [
            EmptyResponseRetryException(
                recovery_prompt=mock_file_content,
                session_id="test-session",
                retry_count=1,
            ),
            ProcessedResponse(content="Valid response"),
        ]

        # Create request processor
        processor = RequestProcessor(**deps)

        # Create test request
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        await processor.process_request(context, request)

        # Verify that the custom recovery prompt was used
        retry_call = deps["backend_processor"].process_backend_request.call_args_list[1]
        retry_request = retry_call[1]["request"]

        assert mock_file_content in retry_request.messages[1].content


@pytest.mark.asyncio
async def test_environment_variable_configuration():
    """Test that empty response configuration can be set via environment variables."""
    import os

    # Set environment variables
    os.environ["EMPTY_RESPONSE_HANDLING_ENABLED"] = "false"
    os.environ["EMPTY_RESPONSE_MAX_RETRIES"] = "3"

    try:
        # Create config from environment
        config = AppConfig.from_env()

        # Verify configuration
        assert config.empty_response.enabled is False
        assert config.empty_response.max_retries == 3

    finally:
        # Clean up environment variables
        os.environ.pop("EMPTY_RESPONSE_HANDLING_ENABLED", None)
        os.environ.pop("EMPTY_RESPONSE_MAX_RETRIES", None)
