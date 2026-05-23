"""Integration tests for client termination detection across transports.

These tests verify that client termination is properly detected and reported
for HTTP (streaming and non-streaming) and Codebuff WebSocket transports.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Request
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.session_key import SessionKey
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.session_metrics_initializer_interface import (
    ISessionMetricsInitializer,
)
from tests.utils.responses_controller_test_deps import (
    build_responses_controller_backend_kwargs,
)


class MockClientEndOfSessionService(IClientEndOfSessionService):
    """Mock implementation of IClientEndOfSessionService for testing."""

    def __init__(self) -> None:
        self.reported_signals: list[ClientEndOfSessionSignal] = []
        self.report_calls: list[tuple[SessionKey, BaseException | None]] = []

    async def report_client_termination(self, signal: ClientEndOfSessionSignal) -> None:
        """Record the termination signal."""
        self.reported_signals.append(signal)

    async def report_client_termination_if_applicable(
        self, session_key: SessionKey, observed_exception: BaseException | None
    ) -> None:
        """Record the termination report call."""
        self.report_calls.append((session_key, observed_exception))


class MockSessionMetricsInitializer(ISessionMetricsInitializer):
    """Mock implementation of ISessionMetricsInitializer for testing."""

    def __init__(self) -> None:
        self.initialized_sessions: list[SessionKey] = []

    async def ensure_session_metrics(
        self, session_key: SessionKey, *, observed_at: datetime
    ) -> None:
        """Record the session metrics initialization."""
        self.initialized_sessions.append(session_key)


@pytest.fixture
def mock_client_eos_service() -> MockClientEndOfSessionService:
    """Create a mock client EoS service."""
    return MockClientEndOfSessionService()


@pytest.fixture
def mock_metrics_initializer() -> MockSessionMetricsInitializer:
    """Create a mock metrics initializer."""
    return MockSessionMetricsInitializer()


class TestHTTPStreamingDisconnect:
    """Tests for HTTP streaming disconnect detection."""

    @pytest.mark.asyncio
    async def test_streaming_disconnect_reports_termination(
        self, mock_client_eos_service: MockClientEndOfSessionService
    ) -> None:
        """Test that streaming disconnect triggers termination reporting."""
        from src.core.app.controllers.responses_controller import ResponsesController
        from src.core.interfaces.request_processor_interface import IRequestProcessor
        from src.core.interfaces.translation_service_interface import (
            ITranslationService,
        )

        # Create mock dependencies
        mock_processor = MagicMock(spec=IRequestProcessor)
        mock_translation = MagicMock(spec=ITranslationService)

        controller = ResponsesController(
            request_processor=mock_processor,
            translation_service=mock_translation,
            client_eos_service=mock_client_eos_service,
            **build_responses_controller_backend_kwargs(),
        )

        # Create mock request with request_id
        mock_request = MagicMock(spec=Request)
        mock_request.is_disconnected = AsyncMock(return_value=False)
        mock_request.state = MagicMock(spec=[])

        # Create RequestContext with request_id
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="test-request-123",
        )

        # Create streaming response envelope
        from src.core.domain.responses import StreamingResponseEnvelope

        async def mock_stream() -> AsyncIterator[str]:
            yield "chunk1"
            yield "chunk2"
            # Simulate disconnect
            mock_request.is_disconnected = AsyncMock(return_value=True)
            yield "chunk3"

        response_envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            cancel_callback=None,
        )

        # Stream response and simulate disconnect
        stream_gen = controller._stream_response_envelope(
            request=mock_request,
            domain_request=MagicMock(),
            response=response_envelope,
            request_id="test-request-123",
            context=context,
        )

        # Consume stream until disconnect
        # The disconnect is detected when processing chunk3 (after is_disconnected returns True)
        chunks = []
        try:
            async for chunk in stream_gen:
                chunks.append(chunk)
                # Continue consuming to trigger disconnect check on chunk3
                if len(chunks) >= 3:
                    break
        except Exception:
            pass

        # Verify termination was reported
        assert len(mock_client_eos_service.reported_signals) == 1
        signal = mock_client_eos_service.reported_signals[0]
        assert signal.reason == ClientTerminationReason.CLIENT_DISCONNECTED
        assert signal.session_key.protocol == "http"
        assert signal.session_key.primary_id == "test-request-123"

    @pytest.mark.asyncio
    async def test_generator_exit_reports_termination(
        self, mock_client_eos_service: MockClientEndOfSessionService
    ) -> None:
        """Test that GeneratorExit triggers termination reporting."""
        from src.core.app.controllers.responses_controller import ResponsesController
        from src.core.interfaces.request_processor_interface import IRequestProcessor
        from src.core.interfaces.translation_service_interface import (
            ITranslationService,
        )

        # Create mock dependencies
        mock_processor = MagicMock(spec=IRequestProcessor)
        mock_translation = MagicMock(spec=ITranslationService)

        controller = ResponsesController(
            request_processor=mock_processor,
            translation_service=mock_translation,
            client_eos_service=mock_client_eos_service,
            **build_responses_controller_backend_kwargs(),
        )

        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.is_disconnected = AsyncMock(return_value=False)
        mock_request.state = MagicMock(spec=[])

        # Create RequestContext with request_id
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="test-request-456",
        )

        # Create streaming response envelope that raises GeneratorExit
        from src.core.domain.responses import StreamingResponseEnvelope

        async def mock_stream() -> AsyncIterator[str]:
            yield "chunk1"
            raise GeneratorExit("Client disconnected")

        response_envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            cancel_callback=None,
        )

        # Stream response - GeneratorExit should be caught and reported
        stream_gen = controller._stream_response_envelope(
            request=mock_request,
            domain_request=MagicMock(),
            response=response_envelope,
            request_id="test-request-456",
            context=context,
        )

        # Consume stream - GeneratorExit will be raised
        try:
            async for _ in stream_gen:
                pass
        except GeneratorExit:
            pass

        # Verify termination was reported
        assert len(mock_client_eos_service.reported_signals) >= 1
        signal = mock_client_eos_service.reported_signals[0]
        assert signal.reason == ClientTerminationReason.CLIENT_DISCONNECTED
        assert signal.session_key.primary_id == "test-request-456"


class TestHTTPNonStreamingCancellation:
    """Tests for HTTP non-streaming cancellation detection."""

    @pytest.mark.asyncio
    async def test_cancelled_error_reports_termination(
        self, mock_client_eos_service: MockClientEndOfSessionService
    ) -> None:
        """Test that CancelledError triggers termination reporting."""
        from src.core.app.middleware.exception_middleware import (
            DomainExceptionMiddleware,
        )

        # Create mock app and service provider
        from src.core.interfaces.di_interface import IServiceProvider

        mock_app = MagicMock()
        # Create a proper mock that passes isinstance check
        mock_service_provider = MagicMock(spec=IServiceProvider)
        mock_service_provider.get_service = MagicMock(
            return_value=mock_client_eos_service
        )
        mock_app.state.service_provider = mock_service_provider

        middleware = DomainExceptionMiddleware(mock_app)

        # Create mock request with request_id
        mock_request = MagicMock(spec=Request)
        mock_request.app = mock_app
        mock_request.headers = {}
        mock_request.cookies = {}
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"
        # Set request_id in request.state (middleware extracts this)
        # Use a real object for state to ensure getattr works
        from types import SimpleNamespace

        mock_request.state = SimpleNamespace()
        mock_request.state.request_id = "test-request-789"

        # Create call_next that raises CancelledError
        async def call_next(request: Request) -> None:
            raise asyncio.CancelledError("Request cancelled")

        # Dispatch should catch CancelledError and report termination
        with contextlib.suppress(asyncio.CancelledError):
            await middleware.dispatch(mock_request, call_next)

        # Verify termination was reported
        assert len(mock_client_eos_service.reported_signals) == 1
        signal = mock_client_eos_service.reported_signals[0]
        assert signal.reason == ClientTerminationReason.CLIENT_CANCELLED


class TestCodebuffDisconnect:
    """Tests for Codebuff WebSocket disconnect detection."""

    @pytest.mark.asyncio
    async def test_codebuff_disconnect_reports_termination(
        self,
        mock_client_eos_service: MockClientEndOfSessionService,
        mock_metrics_initializer: MockSessionMetricsInitializer,
    ) -> None:
        """Test that Codebuff WebSocket disconnect triggers termination reporting."""
        from src.codebuff.connection_manager import ConnectionManager
        from src.codebuff.message_router import MessageRouter
        from src.codebuff.server import CodebuffWebSocketServer

        # Create server with mocks
        connection_manager = ConnectionManager()
        message_router = MessageRouter()

        # Create mock config with max_message_size_bytes
        mock_config = MagicMock()
        mock_config.max_message_size_bytes = 1024 * 1024  # 1MB

        server = CodebuffWebSocketServer(
            connection_manager=connection_manager,
            message_router=message_router,
            prompt_handler=MagicMock(),
            init_handler=MagicMock(),
            subscription_handler=MagicMock(),
            config=mock_config,
            metrics_initializer=mock_metrics_initializer,
            client_eos_service=mock_client_eos_service,
        )

        # Create mock WebSocket
        mock_websocket = MagicMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.close = AsyncMock()

        # Mock identify message
        identify_message = '{"type": "identify", "clientSessionId": "test-session-123"}'
        mock_websocket.receive_text = AsyncMock(return_value=identify_message)

        # Mock message processing to raise WebSocketDisconnect
        from fastapi import WebSocketDisconnect

        async def process_messages_side_effect(ws: Any) -> None:
            raise WebSocketDisconnect()

        server._process_messages = AsyncMock(side_effect=process_messages_side_effect)

        # Mock wait_for_identify to return session_id
        async def wait_for_identify_side_effect(ws: Any) -> str | None:
            return "test-session-123"

        server._wait_for_identify = AsyncMock(side_effect=wait_for_identify_side_effect)

        # Handle connection - should initialize metrics and report termination on disconnect
        with contextlib.suppress(WebSocketDisconnect):
            await server.handle_connection(mock_websocket)

        # Verify session metrics were initialized
        assert len(mock_metrics_initializer.initialized_sessions) == 1
        metrics_session_key = mock_metrics_initializer.initialized_sessions[0]
        assert metrics_session_key.protocol == "codebuff"
        assert metrics_session_key.primary_id == "codebuff:test-session-123"

        # Verify termination was reported
        assert len(mock_client_eos_service.reported_signals) == 1
        signal = mock_client_eos_service.reported_signals[0]
        assert signal.reason == ClientTerminationReason.CLIENT_DISCONNECTED
        assert signal.session_key.protocol == "codebuff"
        assert signal.session_key.primary_id == "codebuff:test-session-123"


class TestMissingSessionContext:
    """Tests for missing session context handling."""

    @pytest.mark.asyncio
    async def test_no_termination_reporting_without_request_id(
        self, mock_client_eos_service: MockClientEndOfSessionService
    ) -> None:
        """Test that termination is not reported when request_id is missing."""
        from src.core.app.controllers.responses_controller import ResponsesController
        from src.core.interfaces.request_processor_interface import IRequestProcessor
        from src.core.interfaces.translation_service_interface import (
            ITranslationService,
        )

        # Create mock dependencies
        mock_processor = MagicMock(spec=IRequestProcessor)
        mock_translation = MagicMock(spec=ITranslationService)

        controller = ResponsesController(
            request_processor=mock_processor,
            translation_service=mock_translation,
            client_eos_service=mock_client_eos_service,
            **build_responses_controller_backend_kwargs(),
        )

        # Create RequestContext WITHOUT request_id
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id=None,  # Missing request_id
        )

        # Create mock request
        mock_request = MagicMock(spec=Request)
        mock_request.is_disconnected = AsyncMock(return_value=True)

        # Create streaming response envelope
        from src.core.domain.responses import StreamingResponseEnvelope

        async def mock_stream() -> AsyncIterator[str]:
            yield "chunk1"

        response_envelope = StreamingResponseEnvelope(
            content=mock_stream(),
            cancel_callback=None,
        )

        # Stream response - disconnect detected but no request_id
        stream_gen = controller._stream_response_envelope(
            request=mock_request,
            domain_request=MagicMock(),
            response=response_envelope,
            request_id="",  # Empty request_id
            context=context,
        )

        # Consume stream
        try:
            async for _ in stream_gen:
                break
        except Exception:
            pass

        # Verify termination was NOT reported (Requirement 1.6)
        assert len(mock_client_eos_service.reported_signals) == 0
