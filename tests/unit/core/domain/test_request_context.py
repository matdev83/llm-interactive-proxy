"""Tests for RequestContext typed fields.

This module tests the explicit typed fields added to RequestContext
for cross-layer data exchange (domain_request, raw_body, backend, effective_model, extensions).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from pydantic.types import JsonValue
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import (
    RequestContext,
    RequestCookies,
    RequestHeaders,
)


class TestRequestContextTypedFields:
    """Test RequestContext explicit typed fields."""

    def test_domain_request_field_accepts_canonical_chat_request(self) -> None:
        """Test that domain_request field accepts CanonicalChatRequest."""
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, domain_request=request
        )
        assert context.domain_request == request
        assert isinstance(context.domain_request, CanonicalChatRequest)

    def test_domain_request_field_accepts_none(self) -> None:
        """Test that domain_request field accepts None."""
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, domain_request=None
        )
        assert context.domain_request is None

    def test_domain_request_field_defaults_to_none(self) -> None:
        """Test that domain_request field defaults to None for backward compatibility."""
        context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
        assert context.domain_request is None

    def test_raw_body_field_accepts_bytes(self) -> None:
        """Test that raw_body field accepts bytes."""
        raw_bytes = b"test body content"
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, raw_body=raw_bytes
        )
        assert context.raw_body == raw_bytes
        assert isinstance(context.raw_body, bytes)

    def test_raw_body_field_accepts_none(self) -> None:
        """Test that raw_body field accepts None."""
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, raw_body=None
        )
        assert context.raw_body is None

    def test_raw_body_field_defaults_to_none(self) -> None:
        """Test that raw_body field defaults to None for backward compatibility."""
        context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
        assert context.raw_body is None

    def test_backend_field_accepts_str(self) -> None:
        """Test that backend field accepts str."""
        backend = "openai"
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, backend=backend
        )
        assert context.backend == backend
        assert isinstance(context.backend, str)

    def test_backend_field_accepts_none(self) -> None:
        """Test that backend field accepts None."""
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, backend=None
        )
        assert context.backend is None

    def test_backend_field_defaults_to_none(self) -> None:
        """Test that backend field defaults to None for backward compatibility."""
        context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
        assert context.backend is None

    def test_effective_model_field_accepts_str(self) -> None:
        """Test that effective_model field accepts str."""
        model = "gpt-4"
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, effective_model=model
        )
        assert context.effective_model == model
        assert isinstance(context.effective_model, str)

    def test_effective_model_field_accepts_none(self) -> None:
        """Test that effective_model field accepts None."""
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, effective_model=None
        )
        assert context.effective_model is None

    def test_effective_model_field_defaults_to_none(self) -> None:
        """Test that effective_model field defaults to None for backward compatibility."""
        context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
        assert context.effective_model is None

    def test_extensions_field_accepts_dict_of_json_values(self) -> None:
        """Test that extensions field accepts dict[str, JsonValue]."""
        extensions: dict[str, JsonValue] = {
            "key1": "string_value",
            "key2": 123,
            "key3": True,
            "key4": None,
            "key5": [1, 2, 3],
            "key6": {"nested": "value"},
        }
        context = RequestContext(
            headers={}, cookies={}, state={}, app_state=None, extensions=extensions
        )
        assert context.extensions == extensions
        assert isinstance(context.extensions, dict)

    def test_extensions_field_defaults_to_empty_dict(self) -> None:
        """Test that extensions field defaults to empty dict."""
        context = RequestContext(headers={}, cookies={}, state={}, app_state=None)
        assert context.extensions == {}
        assert isinstance(context.extensions, dict)

    def test_all_fields_together(self) -> None:
        """Test that all typed fields can be set together."""
        request = CanonicalChatRequest(
            model="test-model", messages=[ChatMessage(role="user", content="test")]
        )
        raw_bytes = b"test body"
        backend = "openai"
        model = "gpt-4"
        extensions: dict[str, JsonValue] = {"key": "value"}

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            domain_request=request,
            raw_body=raw_bytes,
            backend=backend,
            effective_model=model,
            extensions=extensions,
        )

        assert context.domain_request == request
        assert context.raw_body == raw_bytes
        assert context.backend == backend
        assert context.effective_model == model
        assert context.extensions == extensions

    def test_backward_compatibility_existing_fields(self) -> None:
        """Test that existing RequestContext fields still work."""
        headers = RequestHeaders({"x-test": "value"})
        cookies = RequestCookies({"session": "abc123"})
        state = {"key": "value"}
        app_state = MagicMock()

        context = RequestContext(
            headers=headers,
            cookies=cookies,
            state=state,
            app_state=app_state,
            client_host="127.0.0.1",
            session_id="test-session",
            request_id="test-request",
            agent="test-agent",
        )

        assert context.headers == headers
        assert context.cookies == cookies
        assert context.state == state
        # Note: app_state is an internal implementation detail and should not be directly accessed
        # The context is verified to work correctly through other assertions
        assert context.client_host == "127.0.0.1"
        assert context.session_id == "test-session"
        assert context.request_id == "test-request"
        assert context.agent == "test-agent"
        # New fields should have defaults
        assert context.domain_request is None
        assert context.raw_body is None
        assert context.backend is None
        assert context.effective_model is None
        assert context.extensions == {}

    def test_b2bua_identity_field_accepts_proxy_internal_identity(self) -> None:
        """RequestContext should carry proxy-internal B2BUA identity."""
        identity = B2buaIdentity(
            a_session_id="llm-b2bua-abc",
            b_session_id="llm-b2bua-b-abc-1",
            b_seq=1,
            auth_scope_id="token-123",
            client_session_id="client-xyz",
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            session_id="llm-b2bua-abc",
            b2bua_identity=identity,
        )

        assert context.b2bua_identity is not None
        assert context.b2bua_identity.a_session_id == "llm-b2bua-abc"
        assert context.b2bua_identity.b_session_id == "llm-b2bua-b-abc-1"
        assert context.session_id == "llm-b2bua-abc"

    def test_with_b2bua_attempt_identity_returns_copy_without_mutating_original(
        self,
    ) -> None:
        """Per-attempt B-leg identity should be represented via copied context."""
        base = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            session_id="llm-b2bua-abc",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-abc"),
        )

        attempt = base.with_b2bua_attempt_identity(
            b_session_id="llm-b2bua-b-abc-1",
            b_seq=1,
        )

        assert base.b2bua_identity is not None
        assert base.b2bua_identity.b_session_id is None

        assert attempt.b2bua_identity is not None
        assert attempt.b2bua_identity.a_session_id == "llm-b2bua-abc"
        assert attempt.b2bua_identity.b_session_id == "llm-b2bua-b-abc-1"
        assert attempt.b2bua_identity.b_seq == 1
        # A-leg identity remains stable on both contexts.
        assert base.session_id == "llm-b2bua-abc"
        assert attempt.session_id == "llm-b2bua-abc"
