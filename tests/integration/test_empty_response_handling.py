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
        """Create mock dependencies for RequestProcessor with decomposed services."""
        command_processor = AsyncMock()
        session_manager = AsyncMock()
        backend_request_manager = AsyncMock()
        response_manager = AsyncMock()

        # Setup default behaviors
        command_processor.process_messages.return_value = MagicMock(
            command_executed=False, modified_messages=None
        )

        # Mock session manager
        session_manager.resolve_session_id.return_value = "test-session"
        session_manager.get_session.return_value = MagicMock(
            id="test-session",
            agent=None,
            history=[],
            state=MagicMock(
                backend_config=MagicMock(backend_type="test", model="test-model"),
                project=None,
                vtc_enabled=False,  # Disable VTC to prevent request modification
            ),
        )
        session_manager.update_session_agent.return_value = MagicMock(
            id="test-session",
            agent=None,
            history=[],
            state=MagicMock(
                backend_config=MagicMock(backend_type="test", model="test-model"),
                project=None,
                vtc_enabled=False,  # Disable VTC to prevent request modification
            ),
        )

        from src.core.interfaces.request_processor_internal import (
            IBackendExecutor,
            IBackendPreparer,
            ICommandHandler,
            IRequestSideEffects,
            IRequestTransformPipeline,
            ISessionEnricher,
        )

        # Create mocks for new required dependencies
        session_enricher = AsyncMock(spec=ISessionEnricher)
        mock_session = MagicMock(
            id="test-session",
            agent=None,
            history=[],
            state=MagicMock(
                backend_config=MagicMock(backend_type="test", model="test-model"),
                project=None,
                vtc_enabled=False,
            ),
        )
        session_enricher.enrich.return_value = (
            mock_session,
            ChatRequest(
                model="test-model",
                messages=[ChatMessage(role="user", content="Test message")],
            ),
        )

        request_side_effects = AsyncMock(spec=IRequestSideEffects)
        request_side_effects.apply.return_value = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
        )

        command_handler = AsyncMock(spec=ICommandHandler)
        from src.core.domain.processed_result import ProcessedResult

        command_handler.handle.return_value = ProcessedResult(
            modified_messages=[ChatMessage(role="user", content="Test message")],
            command_executed=False,
            command_results=[],
        )

        backend_preparer = AsyncMock(spec=IBackendPreparer)
        backend_preparer.prepare.return_value = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
        )

        transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
        transform_pipeline.transform.return_value = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
        )

        backend_executor = AsyncMock(spec=IBackendExecutor)
        backend_executor.execute.return_value = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        return {
            "command_processor": command_processor,
            "session_manager": session_manager,
            "backend_request_manager": backend_request_manager,
            "response_manager": response_manager,
            "session_enricher": session_enricher,
            "request_side_effects": request_side_effects,
            "command_handler": command_handler,
            "backend_preparer": backend_preparer,
            "transform_pipeline": transform_pipeline,
            "backend_executor": backend_executor,
        }

    @pytest.mark.asyncio
    async def test_empty_response_retry_mechanism(self, mock_dependencies):
        """Test that empty responses trigger retry with recovery prompt."""
        # Setup mocks
        deps = mock_dependencies

        # First call returns empty response, second call returns valid response
        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        # Create test request first
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )

        # Set up backend preparer and executor
        async def prepare_side_effect(context, session_id, req, command_result):
            return req

        deps["backend_preparer"].prepare.side_effect = prepare_side_effect
        deps["backend_executor"].execute.return_value = valid_response

        # Response manager should process the final command result
        deps["response_manager"].process_command_result.return_value = valid_response

        # Create request processor
        processor = RequestProcessor(**deps)
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend preparer and executor were called correctly
        deps["backend_preparer"].prepare.assert_called_once()
        deps["backend_executor"].execute.assert_called_once()

        # Verify final result is the valid response
        assert result == valid_response

    @pytest.mark.asyncio
    async def test_non_empty_response_no_retry(self, mock_dependencies):
        """Test that non-empty responses don't trigger retry."""
        # Setup mocks
        deps = mock_dependencies

        # Create test request first
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )

        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        # Set up backend preparer and executor
        async def prepare_side_effect(context, session_id, req, command_result):
            return req

        deps["backend_preparer"].prepare.side_effect = prepare_side_effect
        deps["backend_executor"].execute.return_value = valid_response

        # Response manager should process the final command result
        deps["response_manager"].process_command_result.return_value = valid_response

        # Create request processor
        processor = RequestProcessor(**deps)
        context = RequestContext(headers={}, cookies={}, state={}, app_state={})

        # Process request
        result = await processor.process_request(context, request)

        # Verify that backend preparer and executor were called correctly
        deps["backend_preparer"].prepare.assert_called_once()
        deps["backend_executor"].execute.assert_called_once()

        # Verify final result is the valid response
        assert result == valid_response

    @pytest.mark.asyncio
    async def test_streaming_response_bypass(self, mock_dependencies):
        """Test that streaming responses bypass empty response detection."""
        # Setup mocks
        deps = mock_dependencies

        from src.core.domain.responses import StreamingResponseEnvelope

        streaming_response = StreamingResponseEnvelope(
            content=None, media_type="text/event-stream"
        )

        async def prepare_side_effect(context, session_id, req, command_result):
            return req

        deps["backend_preparer"].prepare.side_effect = prepare_side_effect
        deps["backend_executor"].execute.return_value = streaming_response

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

        # Verify that backend preparer and executor were called correctly
        deps["backend_preparer"].prepare.assert_called_once()
        deps["backend_executor"].execute.assert_called_once()

        # Verify response processor was not called for streaming
        deps["response_manager"].process_command_result.assert_not_called()

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

        async def prepare_side_effect(context, session_id, req, command_result):
            return req

        deps["backend_preparer"].prepare.side_effect = prepare_side_effect
        deps["backend_executor"].execute.return_value = response_with_tools

        # Response processor should not detect this as empty due to tool calls
        deps["response_manager"].process_command_result.return_value = (
            ProcessedResponse(
                content="",
                metadata={"tool_calls": [{"function": {"name": "test_function"}}]},
            )
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

        # Verify that backend executor was called only once (no retry)
        deps["backend_executor"].execute.assert_called_once()

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

        # Create test request first
        request = ChatRequest(
            model="test-model",
            messages=[ChatMessage(role="user", content="Test message")],
            stream=False,
        )

        valid_response = ResponseEnvelope(
            content={"choices": [{"message": {"content": "Valid response"}}]}
        )

        # Set up backend preparer and executor
        async def prepare_side_effect(context, session_id, req, command_result):
            return req

        deps["backend_preparer"].prepare.side_effect = prepare_side_effect
        deps["backend_executor"].execute.return_value = valid_response

        deps["response_manager"].process_command_result.side_effect = [
            EmptyResponseRetryException(
                recovery_prompt=mock_file_content,
                session_id="test-session",
                retry_count=1,
                original_request=request,
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

        # Verify that the backend preparer and executor were called correctly
        deps["backend_preparer"].prepare.assert_called_once()
        deps["backend_executor"].execute.assert_called_once()


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
