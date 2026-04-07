"""
Tests for the transport adapters.
"""

import asyncio
import contextlib
import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.responses import JSONResponse
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    InvalidRequestError,
    RateLimitExceededError,
    RoutingError,
)
from src.core.config.app_config import AppConfig
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.client_termination import (
    ClientEndOfSessionSignal,
    ClientTerminationReason,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.client_end_of_session_service_interface import (
    IClientEndOfSessionService,
)
from src.core.interfaces.session_cancellation_coordinator_interface import ICancellable
from src.core.services.session_cancellation_coordinator import (
    SessionCancellationCoordinator,
)
from src.core.transport.fastapi import response_adapters as response_adapters_module
from src.core.transport.fastapi.exception_adapters import (
    map_domain_exception_to_http_exception,
)
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)
from src.core.transport.fastapi.response_adapters import (
    domain_response_to_fastapi,
    to_fastapi_response,
    to_fastapi_streaming_response,
)
from src.core.transport.session_key_resolver import (
    resolve_session_key_from_request_context,
)
from starlette.datastructures import Headers, QueryParams
from starlette.responses import Response, StreamingResponse


class MockRequest:
    """Mock FastAPI request for testing."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
        client_host: str = "127.0.0.1",
    ):
        self.headers = Headers(headers or {})
        self.cookies = cookies or {}
        self.client = MagicMock(host=client_host)
        self.app = MagicMock()
        self.app.state = MagicMock()
        self.app.state.backend_type = "openai"
        self.state = MagicMock()
        self.query_params = QueryParams({})
        self.path_params: dict[str, str] = {}


class _TrackedCancellable(ICancellable):
    def __init__(self) -> None:
        self.cancel_calls = 0

    def cancel(self) -> None:
        self.cancel_calls += 1


class _CancellationBridgeService(IClientEndOfSessionService):
    def __init__(self, coordinator: SessionCancellationCoordinator) -> None:
        self._coordinator = coordinator
        self.reported_signals: list[ClientEndOfSessionSignal] = []

    async def report_client_termination(self, signal: ClientEndOfSessionSignal) -> None:
        self.reported_signals.append(signal)
        self._coordinator.cancel_session(signal.session_key, signal.reason)

    async def report_client_termination_if_applicable(
        self, session_key: SessionKey, observed_exception: BaseException | None
    ) -> None:
        return None


class TestRequestAdapters:
    """Tests for request adapters."""

    def test_fastapi_to_domain_request_context(self):
        """Test converting a FastAPI request to a domain request context."""
        # Create a mock request
        mock_request = MockRequest(
            headers={"x-session-id": "test-session", "Authorization": "Bearer xyz"},
            cookies={"session": "cookie-value"},
            client_host="192.168.1.1",
        )

        # Convert to domain context
        context = fastapi_to_domain_request_context(mock_request, attach_original=True)  # type: ignore

        # Verify the context
        assert isinstance(context, RequestContext)
        assert context.headers.get("x-session-id") == "test-session"
        assert context.headers.get("authorization") == "Bearer xyz"
        assert context.cookies.get("session") == "cookie-value"
        assert context.client_host == "192.168.1.1"
        assert context.original_request is mock_request


class TestResponseAdapters:
    """Tests for response adapters."""

    def test_to_fastapi_response_json(self):
        """Test converting a domain response envelope to a FastAPI JSON response."""
        # Create a domain response envelope
        domain_response = ResponseEnvelope(
            content={"message": "Hello, world!"},
            headers={"X-Custom-Header": "test"},
            status_code=201,
            media_type="application/json",
        )

        # Convert to FastAPI response
        fastapi_response = to_fastapi_response(domain_response)

        # Verify the response
        assert isinstance(fastapi_response, JSONResponse)
        assert fastapi_response.status_code == 201
        assert fastapi_response.headers.get("X-Custom-Header") == "test"
        body = json.loads(fastapi_response.body)
        assert body["message"] == "Hello, world!"
        assert "usage" in body  # Usage is added by the adapter

    def test_to_fastapi_response_json_not_gzipped(self):
        """Ensure JSON responses are returned without gzip encoding."""
        domain_response = ResponseEnvelope(
            content={"message": "Hello, gzip!"},
            headers={
                "X-Correlation-Id": "abc123",
                "Access-Control-Allow-Origin": "*",
            },
            status_code=200,
            media_type="application/json",
        )

        fastapi_response = to_fastapi_response(domain_response)

        assert isinstance(fastapi_response, JSONResponse)
        body = json.loads(fastapi_response.body)
        assert body["message"] == "Hello, gzip!"
        assert "usage" in body  # Usage is added by the adapter
        present_headers = {key.lower() for key in fastapi_response.headers}
        assert "content-encoding" not in present_headers
        assert (
            fastapi_response.headers.get("Access-Control-Allow-Origin") == "*"
        ), "CORS header should be preserved."

    def test_to_fastapi_response_text(self):
        """Test converting a domain response envelope to a FastAPI text response."""
        # Create a domain response envelope
        domain_response = ResponseEnvelope(
            content="Hello, world!",
            headers={"X-Custom-Header": "test"},
            status_code=200,
            media_type="text/plain",
        )

        # Convert to FastAPI response
        fastapi_response = to_fastapi_response(domain_response)

        # Verify the response
        assert isinstance(fastapi_response, Response)
        assert fastapi_response.status_code == 200
        assert fastapi_response.headers.get("X-Custom-Header") == "test"
        assert fastapi_response.body == b"Hello, world!"

    def test_to_fastapi_response_text_with_iterable_content(self):
        """Ensure non-JSON iterable content is safely serialized."""

        domain_response = ResponseEnvelope(
            content=["Hello", "world!"],
            headers={"X-Custom-Header": "iterable"},
            status_code=202,
            media_type="text/plain",
        )

        fastapi_response = to_fastapi_response(domain_response)

        assert isinstance(fastapi_response, Response)
        assert fastapi_response.status_code == 202
        assert fastapi_response.headers.get("X-Custom-Header") == "iterable"
        assert fastapi_response.body == b'["Hello", "world!"]'

    @pytest.mark.asyncio
    async def test_to_fastapi_streaming_response(self):
        """Test converting a domain streaming response envelope to a FastAPI streaming response."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        # Create an async generator for streaming content with ProcessedResponse chunks
        async def content_generator():
            yield ProcessedResponse(content="Hello, ", metadata={})
            yield ProcessedResponse(content="world!", metadata={})

        # Create a domain streaming response envelope
        domain_response = StreamingResponseEnvelope(
            content=content_generator(),
            headers={"X-Custom-Header": "test"},
            media_type="text/event-stream",
        )

        # Convert to FastAPI response
        fastapi_response = to_fastapi_streaming_response(domain_response)

        # Verify the response
        assert isinstance(fastapi_response, StreamingResponse)
        assert fastapi_response.headers.get("X-Custom-Header") == "test"
        assert fastapi_response.media_type == "text/event-stream"

        # Collect the streamed content
        chunks = []
        async for chunk in fastapi_response.body_iterator:
            chunks.append(chunk)

        # Verify the content - now properly formatted as SSE
        # The new implementation converts all content to SSE format
        assert len(chunks) >= 2, "Should have at least content chunks and [DONE]"
        assert chunks[-1] == b"data: [DONE]\n\n", "Last chunk should be [DONE] marker"

        # Verify that content chunks are SSE formatted
        for chunk in chunks[:-1]:  # All chunks except [DONE]
            assert chunk.startswith(
                b"data: "
            ), f"Chunk should be SSE formatted: {chunk}"

    def test_domain_response_to_fastapi(self):
        """Test the generic converter function."""
        # Test with a regular response
        regular_response = ResponseEnvelope(
            content={"message": "Regular response"},
            status_code=200,
        )
        fastapi_regular = domain_response_to_fastapi(regular_response)
        assert isinstance(fastapi_regular, JSONResponse)
        body = json.loads(fastapi_regular.body)
        assert body["message"] == "Regular response"
        assert "usage" in body  # Usage is added by the adapter

        # Test with a content converter
        def upper_case_content(content):
            return {
                k: v.upper() if isinstance(v, str) else v for k, v in content.items()
            }

        fastapi_converted = domain_response_to_fastapi(
            regular_response, upper_case_content
        )
        body = json.loads(fastapi_converted.body)
        assert body["message"] == "REGULAR RESPONSE"
        assert "usage" in body  # Usage is added by the adapter

    def test_to_fastapi_response_sets_b2bua_echo_header_when_enabled(self):
        """A-leg echo header is emitted for non-streaming responses when enabled."""
        app_config = AppConfig()
        b2bua_config = app_config.session.b2bua.model_copy(
            update={
                "enabled": True,
                "echo_enabled": True,
                "echo_header_name": "x-test-a-session",
            }
        )
        session_config = app_config.session.model_copy(update={"b2bua": b2bua_config})
        app_config = app_config.model_copy(update={"session": session_config})

        app_state = MagicMock()
        app_state.config = app_config
        a_session_id = "llm-b2bua-a-1234"
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=app_state,
            session_id=a_session_id,
            b2bua_identity=B2buaIdentity(a_session_id=a_session_id),
        )

        response = to_fastapi_response(
            ResponseEnvelope(content={"ok": True}, media_type="application/json"),
            context=context,
        )

        assert response.headers.get("x-test-a-session") == a_session_id

    def test_to_fastapi_response_omits_b2bua_echo_header_when_disabled(self):
        """A-leg echo header is omitted when echo feature is disabled."""
        app_config = AppConfig()
        b2bua_config = app_config.session.b2bua.model_copy(
            update={
                "enabled": True,
                "echo_enabled": False,
            }
        )
        session_config = app_config.session.model_copy(update={"b2bua": b2bua_config})
        app_config = app_config.model_copy(update={"session": session_config})

        app_state = MagicMock()
        app_state.config = app_config
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=app_state,
            session_id="llm-b2bua-a-1234",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-a-1234"),
        )

        response = to_fastapi_response(
            ResponseEnvelope(content={"ok": True}, media_type="application/json"),
            context=context,
        )

        assert response.headers.get("x-b2bua-session-id") is None

    def test_to_fastapi_response_tolerates_restricted_app_state_access(self):
        """Secure state proxies that block config access should not break responses."""

        class _RestrictedAppState:
            @property
            def app_config(self):
                raise RuntimeError("config access blocked")

            @property
            def config(self):
                raise RuntimeError("config access blocked")

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=_RestrictedAppState(),
            session_id="llm-b2bua-a-1234",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-a-1234"),
        )

        response = to_fastapi_response(
            ResponseEnvelope(content={"ok": True}, media_type="application/json"),
            context=context,
        )

        assert response.status_code == 200
        assert response.headers.get("x-b2bua-session-id") in (
            None,
            "llm-b2bua-a-1234",
        )

    @pytest.mark.asyncio
    async def test_to_fastapi_streaming_response_sets_b2bua_echo_header(self):
        """A-leg echo header is emitted for streaming responses when enabled."""
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        app_config = AppConfig()
        b2bua_config = app_config.session.b2bua.model_copy(
            update={
                "enabled": True,
                "echo_enabled": True,
                "echo_header_name": "x-stream-a-session",
            }
        )
        session_config = app_config.session.model_copy(update={"b2bua": b2bua_config})
        app_config = app_config.model_copy(update={"session": session_config})

        app_state = MagicMock()
        app_state.config = app_config
        a_session_id = "llm-b2bua-a-9999"
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=app_state,
            session_id=a_session_id,
            b2bua_identity=B2buaIdentity(a_session_id=a_session_id),
        )

        async def content_generator():
            yield ProcessedResponse(content="hello", metadata={})

        response = to_fastapi_streaming_response(
            StreamingResponseEnvelope(
                content=content_generator(),
                headers={},
                media_type="text/event-stream",
            ),
            context=context,
        )

        assert response.headers.get("x-stream-a-session") == a_session_id

    @pytest.mark.asyncio
    async def test_stream_disconnect_cancels_all_registered_cancellables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        coordinator = SessionCancellationCoordinator(ttl_seconds=60)
        bridge_service = _CancellationBridgeService(coordinator)

        original_resolver = response_adapters_module._resolve_service

        def _resolve_with_bridge(service_type: type):
            if service_type is IClientEndOfSessionService:
                return bridge_service
            return original_resolver(service_type)

        monkeypatch.setattr(
            response_adapters_module, "_resolve_service", _resolve_with_bridge
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            request_id="req-disconnect-cancel-all",
            session_id="llm-b2bua-a-cancel-all",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-a-cancel-all"),
        )

        session_key = resolve_session_key_from_request_context(context)
        assert session_key is not None

        first_bleg = _TrackedCancellable()
        second_bleg = _TrackedCancellable()
        coordinator.register_cancellable(session_key, first_bleg)
        coordinator.register_cancellable(session_key, second_bleg)

        async def content_generator():
            yield ProcessedResponse(content="first", metadata={})
            await asyncio.sleep(5)

        response = to_fastapi_streaming_response(
            StreamingResponseEnvelope(
                content=content_generator(),
                headers={},
                media_type="text/event-stream",
            ),
            context=context,
        )

        body_iter = cast(Any, response.body_iterator)
        _ = await body_iter.__anext__()
        with contextlib.suppress(GeneratorExit, RuntimeError):
            await body_iter.aclose()

        await asyncio.sleep(0.05)

        assert first_bleg.cancel_calls == 1
        assert second_bleg.cancel_calls == 1
        assert bridge_service.reported_signals
        assert (
            bridge_service.reported_signals[0].reason
            == ClientTerminationReason.CLIENT_DISCONNECTED
        )

    @pytest.mark.asyncio
    async def test_stream_disconnect_invokes_explicit_cancel_callback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.core.interfaces.response_processor_interface import ProcessedResponse

        cancel_callback = AsyncMock(return_value=None)
        original_resolver = response_adapters_module._resolve_service

        def _resolve_without_eos(service_type: type):
            if service_type is IClientEndOfSessionService:
                return None
            return original_resolver(service_type)

        monkeypatch.setattr(
            response_adapters_module, "_resolve_service", _resolve_without_eos
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            request_id="req-disconnect-cancel-callback",
            session_id="llm-b2bua-a-cancel-callback",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-a-cancel-callback"),
        )

        async def content_generator():
            yield ProcessedResponse(content="first", metadata={})
            await asyncio.sleep(5)

        response = to_fastapi_streaming_response(
            StreamingResponseEnvelope(
                content=content_generator(),
                headers={},
                media_type="text/event-stream",
                cancel_callback=cancel_callback,
            ),
            context=context,
        )

        body_iter = cast(Any, response.body_iterator)
        _ = await body_iter.__anext__()
        with contextlib.suppress(GeneratorExit, RuntimeError):
            await body_iter.aclose()

        await asyncio.sleep(0.05)
        cancel_callback.assert_awaited_once()


class TestExceptionAdapters:
    """Tests for exception adapters."""

    def test_map_domain_exception_to_http_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Test mapping domain exceptions to HTTP exceptions."""
        # Test authentication error
        auth_error = AuthenticationError("Invalid API key")
        http_exc = map_domain_exception_to_http_exception(auth_error)
        assert http_exc.status_code == 401
        assert "Invalid API key" in str(http_exc.detail)

        # Test configuration error
        config_error = ConfigurationError(
            "Invalid configuration", details={"param": "model"}
        )
        http_exc = map_domain_exception_to_http_exception(config_error)
        assert http_exc.status_code == 400
        assert isinstance(http_exc.detail, dict)
        assert http_exc.detail.get("details", {}).get("param") == "model"

        invalid_error = InvalidRequestError(
            "Bad payload", details={"field": "messages"}
        )
        http_exc = map_domain_exception_to_http_exception(invalid_error)
        assert http_exc.status_code == 400
        assert http_exc.detail.get("details", {}).get("field") == "messages"

        # Test backend error
        backend_error = BackendError("Backend unavailable")
        http_exc = map_domain_exception_to_http_exception(backend_error)
        assert http_exc.status_code == 502

        # Test rate limit error headers
        monkeypatch.setattr(
            "src.core.transport.fastapi.exception_adapters.time.time",
            lambda: 500.0,
        )
        rate_error = RateLimitExceededError("slow down", reset_at=560.2)
        http_exc = map_domain_exception_to_http_exception(rate_error)
        assert http_exc.status_code == 429
        assert http_exc.headers == {"Retry-After": "61"}

        # Test rate limit when reset_at equals current time (immediate retry)
        immediate_reset_error = RateLimitExceededError("retry now", reset_at=500.0)
        http_exc = map_domain_exception_to_http_exception(immediate_reset_error)
        assert http_exc.headers == {"Retry-After": "0"}

        # Expired reset timestamps should clamp to zero seconds
        monkeypatch.setattr(
            "src.core.transport.fastapi.exception_adapters.time.time",
            lambda: 1_600_000_500.0,
        )
        expired_rate_error = RateLimitExceededError(
            "slow down",
            reset_at=1_600_000_000.0,
        )
        http_exc = map_domain_exception_to_http_exception(expired_rate_error)
        assert http_exc.status_code == 429
        assert http_exc.headers == {"Retry-After": "0"}

        # Test RoutingError status codes by details.code
        for code, expected_status in [
            ("unknown_model", 404),
            ("unsupported_on_instance", 400),
            ("temporarily_unavailable", 503),
            ("policy_rejected", 403),
        ]:
            routing_error = RoutingError("routing failed", details={"code": code})
            http_exc = map_domain_exception_to_http_exception(routing_error)
            assert (
                http_exc.status_code == expected_status
            ), f"RoutingError with code={code} should map to {expected_status}"

    def test_map_domain_exception_to_http_exception_detail_shape(self) -> None:
        """Adapter detail must expose structured fields directly for clients."""
        auth_error = AuthenticationError("Invalid API key")
        auth_http_exc = map_domain_exception_to_http_exception(auth_error)

        assert auth_http_exc.status_code == 401
        assert isinstance(auth_http_exc.detail, dict)
        assert auth_http_exc.detail.get("message") == "Invalid API key"
        assert auth_http_exc.detail.get("type") == "AuthenticationError"
        # The adapter unwraps to_dict()["error"] so nested envelope should not be required.
        assert "error" not in auth_http_exc.detail

        rate_error = RateLimitExceededError(
            "Rate limit exceeded",
            details={"retry_after": 7},
        )
        rate_http_exc = map_domain_exception_to_http_exception(rate_error)

        assert rate_http_exc.status_code == 429
        assert isinstance(rate_http_exc.detail, dict)
        assert rate_http_exc.detail.get("message") == "Rate limit exceeded"
        assert rate_http_exc.detail.get("type") == "RateLimitExceededError"
        assert isinstance(rate_http_exc.detail.get("details"), dict)
        assert rate_http_exc.detail["details"].get("retry_after") == 7
