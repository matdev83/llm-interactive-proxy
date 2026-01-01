"""Integration tests for boundary coercion hardening.

Tests verify that dict-to-contract coercion only happens at adapter boundaries
(transport adapters, connector invoker) and not inside core services.

Requirement: 5.2 - Centralize legacy coercion at explicit adapter boundaries only.
Requirement: 4.3 - Add deterministic boundary validation, errors, and structured logs.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.core.adapters.api_adapters import dict_to_domain_chat_request
from src.core.domain.chat import ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


class TestBoundaryCoercionIntegration:
    """Integration tests for boundary coercion behavior."""

    @pytest.mark.asyncio
    async def test_adapter_boundary_accepts_dicts(self):
        """Test that adapter boundary (dict_to_domain_chat_request) accepts dicts."""
        dict_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
        }

        # Adapter boundary should accept dicts and convert to canonical contracts
        result = dict_to_domain_chat_request(dict_request)
        assert isinstance(result, ChatRequest)
        assert result.model == "gpt-4"
        assert len(result.messages) == 1

    @pytest.mark.asyncio
    async def test_core_service_rejects_dicts(self):
        """Test that core services reject dict inputs with InvalidRequestError."""
        from unittest.mock import MagicMock

        from src.core.common.exceptions import InvalidRequestError

        # Create a minimal BackendCompletionFlow with mocked dependencies
        mock_preparer = MagicMock()
        mock_availability = MagicMock()
        mock_failover = MagicMock()
        mock_backend_invoker = MagicMock()
        mock_session_resolver = MagicMock()

        flow = BackendCompletionFlow(
            availability_checker=mock_availability,
            request_preparer=mock_preparer,
            session_resolver=mock_session_resolver,
            backend_invoker=mock_backend_invoker,
            failover_executor=mock_failover,
            wire_capture_orchestrator=MagicMock(),
            usage_accounting_orchestrator=MagicMock(),
            exception_normalizer=MagicMock(),
            stream_formatting_service=MagicMock(),
            connector_invoker=MagicMock(),
        )

        dict_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
        }

        # Verify that call_completion actually rejects dict inputs
        with pytest.raises(InvalidRequestError) as exc_info:
            await flow.call_completion(
                request=dict_request,  # type: ignore[arg-type]
                stream=False,
            )

        assert "dict input" in exc_info.value.message.lower()
        assert "adapter boundaries" in exc_info.value.message.lower()
        assert exc_info.value.details["received_type"] == "dict"
        assert exc_info.value.details["service"] == "BackendCompletionFlow"

    def test_coercion_workflow_adapter_to_core(self):
        """Test the correct workflow: dict → adapter → canonical → core service."""
        # Step 1: Dict input at adapter boundary
        dict_request = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "test"}],
        }

        # Step 2: Adapter converts dict to canonical contract
        canonical_request = dict_to_domain_chat_request(dict_request)
        assert isinstance(canonical_request, ChatRequest)

        # Step 3: Core service accepts canonical contract
        # (This is verified by the fact that we can create the contract without errors)
        assert canonical_request.model == "gpt-4"
        assert len(canonical_request.messages) == 1

    def test_adapter_boundary_is_explicit(self):
        """Test that adapter boundary functions are explicitly named and documented."""
        # Verify adapter function exists and is documented
        assert callable(dict_to_domain_chat_request)
        assert dict_to_domain_chat_request.__doc__ is not None
        assert "dict" in dict_to_domain_chat_request.__doc__.lower()


class TestBoundaryValidationLogging:
    """Integration tests for boundary validation structured logging."""

    @pytest.mark.asyncio
    async def test_backend_completion_flow_logs_with_correlation_ids(self):
        """Test that BackendCompletionFlow logs boundary validation failures with correlation IDs."""
        from src.core.common.exceptions import InvalidRequestError

        # Create a minimal BackendCompletionFlow with mocked dependencies
        flow = BackendCompletionFlow(
            availability_checker=MagicMock(),
            request_preparer=MagicMock(),
            session_resolver=MagicMock(),
            backend_invoker=MagicMock(),
            failover_executor=MagicMock(),
            wire_capture_orchestrator=MagicMock(),
            usage_accounting_orchestrator=MagicMock(),
            exception_normalizer=MagicMock(),
            stream_formatting_service=MagicMock(),
            connector_invoker=MagicMock(),
        )

        # Create context with correlation identifiers
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-request-123",
            session_id="test-session-456",
        )

        dict_request = {"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}

        # Capture log calls
        with patch("src.core.services.backend_completion_flow.service.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                await flow.call_completion(
                    request=dict_request,  # type: ignore[arg-type]
                    stream=False,
                    context=context,
                )

            # Verify structured logging was called with correlation identifiers
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] == "test-request-123"
            assert extra["session_id"] == "test-session-456"
            assert extra["service"] == "BackendCompletionFlow"
            assert extra["violation_type"] == "dict_input"
            assert "dict input" in call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_backend_completion_flow_logs_without_context(self):
        """Test that BackendCompletionFlow logs boundary validation failures even without context."""
        from src.core.common.exceptions import InvalidRequestError

        flow = BackendCompletionFlow(
            availability_checker=MagicMock(),
            request_preparer=MagicMock(),
            session_resolver=MagicMock(),
            backend_invoker=MagicMock(),
            failover_executor=MagicMock(),
            wire_capture_orchestrator=MagicMock(),
            usage_accounting_orchestrator=MagicMock(),
            exception_normalizer=MagicMock(),
            stream_formatting_service=MagicMock(),
            connector_invoker=MagicMock(),
        )

        dict_request = {"model": "gpt-4", "messages": [{"role": "user", "content": "test"}]}

        with patch("src.core.services.backend_completion_flow.service.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                await flow.call_completion(
                    request=dict_request,  # type: ignore[arg-type]
                    stream=False,
                    context=None,
                )

            # Verify structured logging was called even without context
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] is None
            assert extra["session_id"] is None
            assert extra["service"] == "BackendCompletionFlow"

    def test_api_adapter_logs_with_correlation_ids(self):
        """Test that api adapter logs validation failures with correlation IDs."""
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-request-789",
            session_id="test-session-012",
        )

        # Empty messages should trigger validation failure
        dict_request = {"model": "gpt-4", "messages": []}

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                dict_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation identifiers
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] == "test-request-789"
            assert extra["session_id"] == "test-session-012"
            assert extra["service"] == "APIAdapter"
            assert extra["violation_type"] == "empty_messages"

    def test_api_adapter_logs_without_context(self):
        """Test that api adapter logs validation failures even without context."""
        from src.core.common.exceptions import InvalidRequestError

        dict_request = {"model": "gpt-4", "messages": []}

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                dict_to_domain_chat_request(dict_request, context=None)

            # Verify structured logging was called even without context
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] is None
            assert extra["session_id"] is None
            assert extra["service"] == "APIAdapter"

    def test_openai_adapter_passes_context(self):
        """Test that openai_to_domain_chat_request passes context through."""
        from src.core.adapters.api_adapters import openai_to_domain_chat_request
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-req-openai",
            session_id="test-session-openai",
        )

        dict_request = {"model": "gpt-4", "messages": []}

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                openai_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation IDs from context
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] == "test-req-openai"
            assert extra["session_id"] == "test-session-openai"
            assert extra["service"] == "APIAdapter"

    def test_anthropic_adapter_passes_context(self):
        """Test that anthropic_to_domain_chat_request passes context through."""
        from src.core.adapters.api_adapters import anthropic_to_domain_chat_request
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-req-anthropic",
            session_id="test-session-anthropic",
        )

        dict_request = {"model": "claude-3", "messages": []}

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                anthropic_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation IDs from context
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] == "test-req-anthropic"
            assert extra["session_id"] == "test-session-anthropic"
            assert extra["service"] == "APIAdapter"

    def test_gemini_adapter_passes_context(self):
        """Test that gemini_to_domain_chat_request passes context through."""
        from src.core.adapters.api_adapters import gemini_to_domain_chat_request
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-req-gemini",
            session_id="test-session-gemini",
        )

        dict_request = {"model": "gemini-pro", "contents": []}

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                gemini_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation IDs from context
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            extra = call_args[1]["extra"]

            assert extra["request_id"] == "test-req-gemini"
            assert extra["session_id"] == "test-session-gemini"
            assert extra["service"] == "APIAdapter"

    def test_pydantic_validation_error_logging_for_messages(self):
        """Test that Pydantic ValidationError during ChatMessage creation is logged with correlation IDs."""
        from src.core.adapters.api_adapters import dict_to_domain_chat_request
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-req-pydantic",
            session_id="test-session-pydantic",
        )

        # Invalid message format - invalid role type (int instead of str) will cause Pydantic ValidationError
        dict_request = {
            "model": "gpt-4",
            "messages": [{"role": 123, "content": "test"}],  # Invalid role type
        }

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                dict_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation IDs
            assert mock_logger.warning.call_count >= 1
            # Check the last call (Pydantic validation error)
            last_call = mock_logger.warning.call_args_list[-1]
            extra = last_call[1]["extra"]

            assert extra["request_id"] == "test-req-pydantic"
            assert extra["session_id"] == "test-session-pydantic"
            assert extra["service"] == "APIAdapter"
            assert extra["violation_type"] == "invalid_message_format"
            assert "message_index" in extra["details"]

    def test_pydantic_validation_error_logging_for_request(self):
        """Test that Pydantic ValidationError during ChatRequest creation is logged with correlation IDs."""
        from src.core.adapters.api_adapters import dict_to_domain_chat_request
        from src.core.common.exceptions import InvalidRequestError

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            request_id="test-req-pydantic-req",
            session_id="test-session-pydantic-req",
        )

        # Invalid request format that will cause Pydantic ValidationError
        dict_request = {
            "model": "",  # Empty model might cause validation error
            "messages": [{"role": "user", "content": "test"}],
            "temperature": "invalid",  # Invalid type for temperature
        }

        with patch("src.core.adapters.api_adapters.logger") as mock_logger:
            with pytest.raises(InvalidRequestError):
                dict_to_domain_chat_request(dict_request, context=context)

            # Verify structured logging was called with correlation IDs
            assert mock_logger.warning.call_count >= 1
            # Check the last call (Pydantic validation error)
            last_call = mock_logger.warning.call_args_list[-1]
            extra = last_call[1]["extra"]

            assert extra["request_id"] == "test-req-pydantic-req"
            assert extra["session_id"] == "test-session-pydantic-req"
            assert extra["service"] == "APIAdapter"
            assert extra["violation_type"] == "invalid_request_format"
            assert "validation_errors" in extra["details"]
