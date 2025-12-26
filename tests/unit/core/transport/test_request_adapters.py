from __future__ import annotations

from types import SimpleNamespace

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)


class _DummyRequest:
    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = headers
        self.cookies = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace(request_state={})
        self.app = SimpleNamespace(state=SimpleNamespace())
        self.method = "POST"
        self.url = "http://localhost/test"


def test_request_context_agent_from_x_agent_header() -> None:
    req = _DummyRequest({"X-Agent": "cline", "User-Agent": "ua-default"})
    ctx = fastapi_to_domain_request_context(req, attach_original=True)  # type: ignore[arg-type]
    assert ctx.client_host == "127.0.0.1"
    assert ctx.agent == "cline"


def test_request_context_agent_from_x_client_agent_header() -> None:
    req = _DummyRequest({"X-Client-Agent": "my-agent", "User-Agent": "ua-default"})
    ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
    assert ctx.agent == "my-agent"


def test_request_context_agent_falls_back_to_user_agent_truncated() -> None:
    long_ua = "x" * 200
    req = _DummyRequest({"User-Agent": long_ua})
    ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
    assert ctx.agent is not None
    assert len(ctx.agent) == 80
    assert ctx.agent == long_ua[:80]


class TestRequestAdapterTypedFields:
    """Test adapter population of typed RequestContext fields."""

    def test_adapter_accepts_domain_request_parameter(self) -> None:
        """Test that adapter can accept optional domain_request parameter."""
        req = _DummyRequest({})
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        ctx = fastapi_to_domain_request_context(
            req, domain_request=request  # type: ignore[arg-type]
        )
        assert ctx.domain_request == request
        assert isinstance(ctx.domain_request, CanonicalChatRequest)

    def test_adapter_accepts_raw_body_parameter(self) -> None:
        """Test that adapter can accept optional raw_body parameter."""
        req = _DummyRequest({})
        raw_bytes = b"test body content"
        ctx = fastapi_to_domain_request_context(
            req, raw_body=raw_bytes  # type: ignore[arg-type]
        )
        assert ctx.raw_body == raw_bytes
        assert isinstance(ctx.raw_body, bytes)

    def test_adapter_populates_both_domain_request_and_raw_body(self) -> None:
        """Test that adapter can populate both domain_request and raw_body."""
        req = _DummyRequest({})
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        raw_bytes = b"test body"
        ctx = fastapi_to_domain_request_context(
            req, domain_request=request, raw_body=raw_bytes  # type: ignore[arg-type]
        )
        assert ctx.domain_request == request
        assert ctx.raw_body == raw_bytes

    def test_adapter_backward_compatibility_without_optional_params(self) -> None:
        """Test that existing calls without optional params still work."""
        req = _DummyRequest({"X-Agent": "test-agent"})
        ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
        # Existing fields should work
        assert ctx.agent == "test-agent"
        # New fields should have defaults
        assert ctx.domain_request is None
        assert ctx.raw_body is None


class _NonStringHeadersRequest:
    """Request with headers containing non-string values (causes TypeError)."""

    def __init__(self) -> None:
        self.cookies = {}
        self.client = SimpleNamespace(host="127.0.0.1")
        self.state = SimpleNamespace(request_state={})
        self.app = SimpleNamespace(state=SimpleNamespace())
        # Headers with non-string value (user-agent is None)
        self.headers = {"User-Agent": None}  # type: ignore[dict-item]


def test_request_context_handles_non_string_headers() -> None:
    """Test that adapter gracefully handles non-string header values."""
    req = _NonStringHeadersRequest()
    ctx = fastapi_to_domain_request_context(req)  # type: ignore[arg-type]
    # Should return None for agent on TypeError
    assert ctx.agent is None
    # Other fields should still be populated
    assert ctx.client_host == "127.0.0.1"
