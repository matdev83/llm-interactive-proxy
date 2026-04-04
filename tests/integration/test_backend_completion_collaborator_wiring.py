"""Integration tests for backend completion collaborator wiring with typed parameters."""

from __future__ import annotations

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_completion_collaborators import (
    IBackendRequestPreparer,
    ICompletionSessionResolver,
    IFailureRecoveryExecutor,
    IUsageAccountingOrchestrator,
    IWireCaptureOrchestrator,
)
from src.core.interfaces.backend_completion_flow_interface import IBackendCompletionFlow
from src.core.interfaces.backend_work_guard_interface import IBackendWorkGuard
from src.core.interfaces.domain_entities_interface import ISession


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_resolver_returns_typed_session(
    app_config_legacy_log_disabled,
):
    """Test that ICompletionSessionResolver returns ISession | None."""
    from src.core.app.application_builder import ApplicationBuilder

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_legacy_log_disabled)
    service_provider = app.state.service_provider

    session_resolver = service_provider.get_required_service(ICompletionSessionResolver)

    # Create a test request
    request = CanonicalChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id="test-session",
    )

    # Resolve session
    session, session_id = await session_resolver.resolve_session(context, request)

    # Verify return types
    assert session is None or isinstance(session, ISession)
    assert session_id is None or isinstance(session_id, str)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_backend_request_preparer_accepts_typed_session(
    app_config_with_openai_backend,
):
    """Test that IBackendRequestPreparer accepts ISession | None."""
    from src.core.app.application_builder import ApplicationBuilder
    from src.core.domain.backend_target import BackendTarget

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_with_openai_backend)
    service_provider = app.state.service_provider

    request_preparer = service_provider.get_required_service(IBackendRequestPreparer)

    # Create a test request - use explicit backend format to bypass model-only resolution
    request = CanonicalChatRequest(
        model="openai:gpt-4",
        messages=[ChatMessage(role="user", content="test")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
    )

    # Prepare request (gets target)
    target = await request_preparer.prepare_request(request, context)
    assert isinstance(target, BackendTarget)

    # Test with None session
    prepared_request = await request_preparer.prepare_backend_request(
        request, "test-backend", None, {}
    )
    assert isinstance(prepared_request, CanonicalChatRequest)

    # Test prepare_backend_kwargs with None session
    kwargs = request_preparer.prepare_backend_kwargs(
        "test-session", None, context, "test-backend"
    )
    assert isinstance(kwargs, dict)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_wire_capture_orchestrator_accepts_typed_session(
    app_config_legacy_log_disabled,
):
    """Test that IWireCaptureOrchestrator accepts ISession | None."""
    from src.core.app.application_builder import ApplicationBuilder

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_legacy_log_disabled)
    service_provider = app.state.service_provider

    wire_capture_orchestrator = service_provider.get_required_service(
        IWireCaptureOrchestrator
    )

    # Test with None session
    identity = await wire_capture_orchestrator.prepare_wire_capture_context(
        "test-backend", None
    )
    # Identity can be None or an identity object
    assert identity is None or isinstance(identity, object)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_usage_accounting_orchestrator_accepts_typed_session(
    app_config_legacy_log_disabled,
):
    """Test that IUsageAccountingOrchestrator accepts ISession | None."""
    from src.core.app.application_builder import ApplicationBuilder
    from src.core.domain.chat import ChatRequest

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_legacy_log_disabled)
    service_provider = app.state.service_provider

    usage_accounting = service_provider.get_required_service(
        IUsageAccountingOrchestrator
    )

    # Create a test request
    request = ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="test")],
    )

    # Test with None session
    outbound_tokens, ctp_id, ptb_id = await usage_accounting.calculate_and_record_usage(
        request, request, "test-backend", "test-model", None, "test-session"
    )

    assert isinstance(outbound_tokens, int)
    assert ctp_id is None or isinstance(ctp_id, str)
    assert ptb_id is None or isinstance(ptb_id, str)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_collaborator_wiring_end_to_end(
    app_config_with_openai_backend,
):
    """Test that all collaborators work together with typed parameters."""
    from src.core.app.application_builder import ApplicationBuilder
    from src.core.domain.backend_target import BackendTarget

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_with_openai_backend)
    service_provider = app.state.service_provider

    session_resolver = service_provider.get_required_service(ICompletionSessionResolver)
    request_preparer = service_provider.get_required_service(IBackendRequestPreparer)
    wire_capture_orchestrator = service_provider.get_required_service(
        IWireCaptureOrchestrator
    )

    # Create a test request - use explicit backend format to bypass model-only resolution
    request = CanonicalChatRequest(
        model="openai:gpt-4",
        messages=[ChatMessage(role="user", content="test")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
    )

    # Resolve session (returns ISession | None)
    session, session_id = await session_resolver.resolve_session(context, request)
    assert session is None or isinstance(session, ISession)

    # Prepare request
    target = await request_preparer.prepare_request(request, context)
    assert isinstance(target, BackendTarget)

    # Prepare backend request with typed session
    prepared = await request_preparer.prepare_backend_request(
        request, target.backend, session, target.uri_params
    )
    assert isinstance(prepared, CanonicalChatRequest)

    # Prepare wire capture context with typed session
    identity = await wire_capture_orchestrator.prepare_wire_capture_context(
        target.backend, session
    )
    # Identity can be None or an identity object
    assert identity is None or isinstance(identity, object)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_backend_work_guard_wiring_resolves_key_services(
    app_config_with_openai_backend,
) -> None:
    """Ensure new guard dependency wiring resolves from DI container."""
    from src.core.app.application_builder import ApplicationBuilder

    builder = ApplicationBuilder().add_default_stages()
    app = await builder.build(app_config_with_openai_backend)
    service_provider = app.state.service_provider

    backend_work_guard = service_provider.get_required_service(IBackendWorkGuard)
    failure_recovery_executor = service_provider.get_required_service(
        IFailureRecoveryExecutor
    )
    backend_completion_flow = service_provider.get_required_service(
        IBackendCompletionFlow
    )

    assert backend_work_guard is not None
    assert failure_recovery_executor is not None
    assert backend_completion_flow is not None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_response_envelope_metadata_json_serializable(
    app_config_legacy_log_disabled,
):
    """Test that ResponseEnvelope metadata is JSON-serializable."""
    import json

    from pydantic.types import JsonValue
    from src.core.domain.responses import ResponseEnvelope

    # Create envelope with JSON-serializable metadata
    metadata: dict[str, JsonValue] = {
        "test_string": "value",
        "test_int": 42,
        "test_bool": True,
        "test_list": [1, 2, 3],
        "test_dict": {"nested": "value"},
    }

    envelope = ResponseEnvelope(
        content={"message": "test"},
        metadata=metadata,
    )

    # Verify metadata can be JSON-serialized
    json_str = json.dumps(envelope.metadata)
    assert json_str is not None

    # Verify round-trip
    deserialized = json.loads(json_str)
    assert deserialized == metadata


@pytest.mark.asyncio
@pytest.mark.integration
async def test_streaming_response_envelope_metadata_json_serializable(
    app_config_legacy_log_disabled,
):
    """Test that StreamingResponseEnvelope metadata is JSON-serializable."""
    import json
    from collections.abc import AsyncIterator

    from pydantic.types import JsonValue
    from src.core.domain.responses import StreamingResponseEnvelope
    from src.core.interfaces.response_processor_interface import ProcessedResponse

    async def empty_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="test")

    # Create envelope with JSON-serializable metadata
    metadata: dict[str, JsonValue] = {
        "test_string": "value",
        "test_int": 42,
        "test_bool": True,
    }

    envelope = StreamingResponseEnvelope(
        content=empty_stream(),
        metadata=metadata,
    )

    # Verify metadata can be JSON-serialized
    json_str = json.dumps(envelope.metadata)
    assert json_str is not None

    # Verify round-trip
    deserialized = json.loads(json_str)
    assert deserialized == metadata
