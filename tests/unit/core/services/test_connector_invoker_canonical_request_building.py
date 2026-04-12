"""Unit tests for ConnectorInvoker canonical request building."""

from __future__ import annotations

from typing import Any

from src.core.domain.chat import CanonicalChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.session_key import SessionKey
from src.core.interfaces.configuration_interface import IAppIdentityConfig
from src.core.interfaces.session_cancellation_coordinator_interface import (
    ISessionCancellationCoordinator,
)
from src.core.services.connector_invoker import ConnectorInvoker

pytest_plugins = ("tests.unit.core.services.connector_invoker_test_support",)


class TestCanonicalRequestBuilding:
    """Tests for building ConnectorChatCompletionsRequest."""

    def test_build_canonical_request_with_all_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
        sample_request_context: RequestContext,
        sample_identity: IAppIdentityConfig,
        sample_session_key: SessionKey,
        sample_cancellation_coordinator: ISessionCancellationCoordinator,
        sample_options: dict[str, Any],
    ) -> None:
        """Test building canonical request with all fields."""
        domain_request = sample_canonical_request
        processed_messages = list(sample_canonical_request.messages)
        effective_model = "gpt-4"
        projected_context = connector_invoker._project_context(sample_request_context)

        connector_request = connector_invoker._build_canonical_request(
            domain_request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=sample_identity,
            cancellation_token=sample_session_key,
            cancellation_coordinator=sample_cancellation_coordinator,
            context=projected_context,
            options=sample_options,
        )

        assert connector_request.request == domain_request
        assert connector_request.processed_messages == processed_messages
        assert connector_request.effective_model == effective_model
        assert connector_request.identity == sample_identity
        assert connector_request.cancellation_token == sample_session_key
        assert (
            connector_request.cancellation_coordinator
            == sample_cancellation_coordinator
        )
        assert connector_request.context == projected_context
        assert connector_request.options == sample_options

    def test_build_canonical_request_with_minimal_fields(
        self,
        connector_invoker: ConnectorInvoker,
        sample_canonical_request: CanonicalChatRequest,
    ) -> None:
        """Test building canonical request with minimal fields."""
        domain_request = sample_canonical_request
        processed_messages = list(sample_canonical_request.messages)
        effective_model = "gpt-4"

        connector_request = connector_invoker._build_canonical_request(
            domain_request=domain_request,
            processed_messages=processed_messages,
            effective_model=effective_model,
            identity=None,
            cancellation_token=None,
            cancellation_coordinator=None,
            context=None,
            options={},
        )

        assert connector_request.request == domain_request
        assert connector_request.processed_messages == processed_messages
        assert connector_request.effective_model == effective_model
        assert connector_request.identity is None
        assert connector_request.cancellation_token is None
        assert connector_request.cancellation_coordinator is None
        assert connector_request.context is None
        assert connector_request.options == {}
