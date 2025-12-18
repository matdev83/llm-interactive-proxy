"""Characterization tests for request context propagation.

This module validates that request context typed fields propagate correctly
through the request processing pipeline, preserving behavior while using
explicit typed contracts instead of dynamic attributes.
"""

from __future__ import annotations

from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.transport.fastapi.request_adapters import (
    fastapi_to_domain_request_context,
)


class TestRequestContextPropagation:
    """Test request context typed field propagation end-to-end."""

    def test_adapter_populates_domain_request_field(self) -> None:
        """Test that adapter populates domain_request field correctly."""
        from types import SimpleNamespace

        class MockRequest:
            def __init__(self) -> None:
                self.headers = {}
                self.cookies = {}
                self.client = SimpleNamespace(host="127.0.0.1")
                self.state = SimpleNamespace(request_state={})
                self.app = SimpleNamespace(state=SimpleNamespace())

        request = MockRequest()
        domain_request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )

        ctx = fastapi_to_domain_request_context(
            request, domain_request=domain_request  # type: ignore[arg-type]
        )

        assert ctx.domain_request == domain_request
        assert ctx.domain_request is not None
        assert ctx.domain_request.model == "test-model"

    def test_adapter_populates_raw_body_field(self) -> None:
        """Test that adapter populates raw_body field correctly."""
        from types import SimpleNamespace

        class MockRequest:
            def __init__(self) -> None:
                self.headers = {}
                self.cookies = {}
                self.client = SimpleNamespace(host="127.0.0.1")
                self.state = SimpleNamespace(request_state={})
                self.app = SimpleNamespace(state=SimpleNamespace())

        request = MockRequest()
        raw_body = b'{"model": "test", "messages": []}'

        ctx = fastapi_to_domain_request_context(
            request, raw_body=raw_body  # type: ignore[arg-type]
        )

        assert ctx.raw_body == raw_body
        assert ctx.raw_body is not None
        assert isinstance(ctx.raw_body, bytes)

    def test_context_fields_are_accessible_after_creation(self) -> None:
        """Test that typed fields are accessible after context creation."""
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        raw_body = b"test body"

        ctx = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            domain_request=request,
            raw_body=raw_body,
            backend="openai",
            effective_model="gpt-4",
        )

        # Verify all fields are accessible
        assert ctx.domain_request == request
        assert ctx.raw_body == raw_body
        assert ctx.backend == "openai"
        assert ctx.effective_model == "gpt-4"
        assert ctx.extensions == {}

    def test_context_fields_default_to_none_or_empty(self) -> None:
        """Test that typed fields default correctly for backward compatibility."""
        ctx = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        # Verify defaults
        assert ctx.domain_request is None
        assert ctx.raw_body is None
        assert ctx.backend is None
        assert ctx.effective_model is None
        assert ctx.extensions == {}

    def test_direct_field_assignment_works(self) -> None:
        """Test that direct field assignment works without type ignores."""
        ctx = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
        )

        # Direct assignment should work without type ignore
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        ctx.domain_request = request
        ctx.raw_body = b"test"
        ctx.backend = "openai"
        ctx.effective_model = "gpt-4"

        assert ctx.domain_request == request
        assert ctx.raw_body == b"test"
        assert ctx.backend == "openai"
        assert ctx.effective_model == "gpt-4"

    def test_extensions_field_accepts_json_values(self) -> None:
        """Test that extensions field accepts JSON-serializable values."""
        from pydantic.types import JsonValue

        extensions: dict[str, JsonValue] = {
            "string": "value",
            "number": 123,
            "boolean": True,
            "null": None,
            "array": [1, 2, 3],
            "object": {"nested": "value"},
        }

        ctx = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            extensions=extensions,
        )

        assert ctx.extensions == extensions
        assert ctx.extensions["string"] == "value"
        assert ctx.extensions["number"] == 123
        assert ctx.extensions["boolean"] is True
        assert ctx.extensions["null"] is None
        assert isinstance(ctx.extensions["array"], list)
        assert isinstance(ctx.extensions["object"], dict)
