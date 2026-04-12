"""Unit tests for ConnectorInvoker context projection."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.request_context import RequestContext
from src.core.services.connector_invoker import ConnectorInvoker

pytest_plugins = ("tests.unit.core.services.connector_invoker_test_support",)


class TestContextProjection:
    """Tests for RequestContext -> ConnectorRequestContext projection."""

    def test_project_context_with_all_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_request_context: RequestContext,
    ) -> None:
        """Test context projection with all fields populated."""
        projected = connector_invoker._project_context(sample_request_context)

        assert projected is not None
        assert projected.request_id == "req-123"
        assert projected.session_id == "session-456"
        assert projected.client_host == "192.168.1.1"
        assert projected.extensions == {"key1": "value1", "key2": 42}

    def test_project_context_with_none_values(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test context projection with None values."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            request_id=None,
            session_id=None,
            client_host=None,
        )
        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.request_id is None
        assert projected.session_id is None
        assert projected.client_host is None
        assert projected.extensions == {}

    def test_project_context_returns_none_when_context_is_none(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test that None context returns None projection."""
        projected = connector_invoker._project_context(None)
        assert projected is None

    def test_project_context_copies_extensions(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Test that extensions dict is copied (not shared reference)."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            extensions={"key": "value"},
        )
        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.extensions == {"key": "value"}
        # Modify original - should not affect projected
        context.extensions["new_key"] = "new_value"
        assert projected.extensions == {"key": "value"}

    def test_project_context_uses_b_leg_session_and_redacts_client_identity(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """Connector projection should be safe for outbound boundaries."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            session_id="llm-b2bua-abc",
            b2bua_identity=B2buaIdentity(
                a_session_id="llm-b2bua-abc",
                b_session_id="llm-b2bua-b-abc-2",
                b_seq=2,
                auth_scope_id="token-1",
                client_session_id="client-user-session",
            ),
            extensions={
                "safe_key": "safe-value",
                "client_session_id": "must-not-leak",
                "a_session_id": "must-not-leak",
                "auth_scope_id": "must-not-leak",
                "b2bua": {
                    "client_session_id": "must-not-leak",
                    "a_session_id": "must-not-leak",
                    "auth_scope_id": "must-not-leak",
                },
            },
        )

        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.session_id == "llm-b2bua-b-abc-2"
        assert projected.extensions["safe_key"] == "safe-value"
        assert "client_session_id" not in projected.extensions
        assert "a_session_id" not in projected.extensions
        assert "auth_scope_id" not in projected.extensions
        assert projected.extensions.get("b2bua") == {"b_seq": 2}

    def test_project_context_omits_a_leg_when_b_leg_missing(
        self,
        connector_invoker: ConnectorInvoker,
    ) -> None:
        """B2BUA mode must not fall back to A-leg at connector boundary."""
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=MagicMock(),
            session_id="llm-b2bua-a-1234",
            b2bua_identity=B2buaIdentity(a_session_id="llm-b2bua-a-1234"),
        )

        projected = connector_invoker._project_context(context)

        assert projected is not None
        assert projected.session_id is None
