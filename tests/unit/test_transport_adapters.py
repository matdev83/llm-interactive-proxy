"""
Tests for the transport adapters.
"""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.responses import JSONResponse
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    ConfigurationError,
    RateLimitExceededError,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
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
        self.path_params = {}


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
        assert json.loads(fastapi_response.body) == {"message": "Hello, world!"}

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

        # Create an async generator for streaming content
        async def content_generator():
            yield b"Hello, "
            yield b"world!"

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

        # Verify the content
        assert chunks == [b"Hello, ", b"world!"]

    def test_domain_response_to_fastapi(self):
        """Test the generic converter function."""
        # Test with a regular response
        regular_response = ResponseEnvelope(
            content={"message": "Regular response"},
            status_code=200,
        )
        fastapi_regular = domain_response_to_fastapi(regular_response)
        assert isinstance(fastapi_regular, JSONResponse)
        assert json.loads(fastapi_regular.body) == {"message": "Regular response"}

        # Test with a content converter
        def upper_case_content(content):
            return {
                k: v.upper() if isinstance(v, str) else v for k, v in content.items()
            }

        fastapi_converted = domain_response_to_fastapi(
            regular_response, upper_case_content
        )
        assert json.loads(fastapi_converted.body) == {"message": "REGULAR RESPONSE"}


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

        expired_rate_error = RateLimitExceededError("slow down", reset_at=450.0)
        http_exc = map_domain_exception_to_http_exception(expired_rate_error)
        assert http_exc.headers == {"Retry-After": "0"}
