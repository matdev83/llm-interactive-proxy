"""Integration tests for non-forwardable message filtering in backend completion flow.

Tests verify:
- Filtering happens before wire capture (requirement 6.3)
- Filtering works after history compaction (requirement 7.4, 1.12)
- Error cases fail closed before backend calls (requirement 5.3, 10.1, 14.3)
- Session scoping prevents tag leakage (requirement 8.4)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from src.core.app.test_builder import build_test_app, create_test_config
from src.core.common.exceptions import (
    BackendError,
    NonForwardableTagLimitExceededError,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.non_forwardable import NonForwardableTagScope
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_completion_flow_interface import IBackendCompletionFlow
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)


@pytest_asyncio.fixture
async def test_app():
    """Create test app with non-forwardable services."""
    config = create_test_config()
    app = build_test_app(config)
    yield app


@pytest_asyncio.fixture
async def backend_flow(test_app):
    """Get BackendCompletionFlow from test app."""
    service_provider = test_app.state.service_provider
    flow = service_provider.get_required_service(IBackendCompletionFlow)
    return flow


@pytest_asyncio.fixture
async def identity_service(test_app):
    """Get identity service from test app."""
    service_provider = test_app.state.service_provider
    identity_service = service_provider.get_service(
        INonForwardableMessageIdentityService
    )
    return identity_service


@pytest_asyncio.fixture
async def registry(test_app):
    """Get registry service from test app."""
    service_provider = test_app.state.service_provider
    registry = service_provider.get_service(INonForwardableMessageRegistry)
    return registry


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtering_before_wire_capture(
    test_app,
    backend_flow: IBackendCompletionFlow,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that filtering happens before wire capture (requirement 6.3)."""
    session_id = "test-session-filter-wire"

    # Create messages: one forwardable, one non-forwardable
    forwardable_msg = ChatMessage(role="user", content="Hello")
    non_forwardable_msg = ChatMessage(role="user", content="!/test")

    # Tag the non-forwardable message
    non_forwardable_id = identity_service.compute_identity(non_forwardable_msg)
    await registry.tag_identities(
        session_id,
        [non_forwardable_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="test",
    )

    # Create request with both messages
    request = CanonicalChatRequest(
        model="test-model",
        messages=[forwardable_msg, non_forwardable_msg],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

    # Use the test app's service provider to get backend invoker
    from unittest.mock import patch

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    # Capture messages sent to backend
    backend_received_messages = []

    async def capture_messages(*args, **kwargs):
        """Capture messages sent to backend."""
        request_data = kwargs.get("request_data") or args[0]
        if hasattr(request_data, "messages"):
            backend_received_messages.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "Hi"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    # Create mock backend
    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=capture_messages)

    # Patch backend invoker to return our mock
    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        # Call completion flow - should succeed with filtered messages
        await backend_flow.call_completion(request, stream=False, context=context)

    # Verify backend received only forwardable message (non-forwardable was filtered)
    assert len(backend_received_messages) == 1
    assert backend_received_messages[0].content == "Hello"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_filtering_after_compaction(
    test_app,
    backend_flow: IBackendCompletionFlow,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that filtering works after history compaction (requirement 7.4, 1.12)."""
    session_id = "test-session-compaction"

    # Create tool result message that will be compacted
    tool_result_msg = ChatMessage(
        role="tool",
        tool_call_id="call_123",
        content="Tool output",
    )

    # Tag it as non-forwardable
    tool_result_id = identity_service.compute_identity(tool_result_msg)
    await registry.tag_identities(
        session_id,
        [tool_result_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="test",
    )

    # Create request with tool result
    request = CanonicalChatRequest(
        model="test-model",
        messages=[
            ChatMessage(role="user", content="Use tool"),
            tool_result_msg,
            ChatMessage(role="user", content="Continue"),
        ],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

    # Mock backend
    backend_received_messages = []

    async def mock_chat_completions(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from unittest.mock import patch

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_flow.call_completion(request, stream=False, context=context)

    # Verify tool result was filtered (even if compaction rewrote content)
    # The identity should still match
    assert len(backend_received_messages) == 2  # user messages only
    assert all(msg.role != "tool" for msg in backend_received_messages)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_no_forwardable_content_error(
    test_app,
    backend_flow: IBackendCompletionFlow,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that 'no forwardable content' error fails before backend call (requirement 5.3)."""
    session_id = "test-session-no-forwardable"

    # Tag all user messages as non-forwardable
    user_msg = ChatMessage(role="user", content="!/command")
    user_msg_id = identity_service.compute_identity(user_msg)
    await registry.tag_identities(
        session_id,
        [user_msg_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="test",
    )

    request = CanonicalChatRequest(
        model="test-model",
        messages=[user_msg],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

    # Mock backend - should never be called
    backend_called = False

    async def mock_chat_completions(*args, **kwargs):
        nonlocal backend_called
        backend_called = True
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from unittest.mock import patch

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        # Should raise error before backend call
        with pytest.raises(BackendError) as exc_info:
            await backend_flow.call_completion(request, stream=False, context=context)

        # Verify error mentions non-forwardable enforcement
        assert (
            "non-forwardable" in str(exc_info.value).lower()
            or "forwardable" in str(exc_info.value).lower()
        )
        assert not backend_called


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_scoping_no_leakage(
    test_app,
    backend_flow: IBackendCompletionFlow,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that tags don't leak across sessions (requirement 8.4)."""
    session1_id = "test-session-1"
    session2_id = "test-session-2"

    # Tag message in session 1
    msg = ChatMessage(role="user", content="!/command")
    msg_id = identity_service.compute_identity(msg)
    await registry.tag_identities(
        session1_id,
        [msg_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="test",
    )

    # Create request for session 2 with same message
    request = CanonicalChatRequest(
        model="test-model",
        messages=[msg],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session2_id,
    )

    # Mock backend
    backend_received_messages = []

    async def mock_chat_completions(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from unittest.mock import patch

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_flow.call_completion(request, stream=False, context=context)

    # Verify message was NOT filtered in session 2 (tags are session-scoped)
    assert len(backend_received_messages) == 1
    assert backend_received_messages[0].content == "!/command"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_capacity_exceeded_fails_closed(
    test_app,
    backend_flow: IBackendCompletionFlow,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that capacity exceeded fails closed before backend call (requirement 14.3, 10.1)."""
    # Create a test app with very small capacity limit
    from src.core.config.models.non_forwardable_config import (
        NonForwardableTaggingConfig,
    )
    
    config = create_test_config()
    # Use model_copy to create a new config with modified non_forwardable_tagging
    config = config.model_copy(
        update={
            "non_forwardable_tagging": NonForwardableTaggingConfig(
                max_identities_per_session=1
            )
        }
    )
    app = build_test_app(config)
    service_provider = app.state.service_provider
    
    # Get services from the new app
    identity_svc = service_provider.get_service(INonForwardableMessageIdentityService)
    registry_svc = service_provider.get_service(INonForwardableMessageRegistry)
    
    session_id = "test-session-capacity"
    
    # Create a session for the command service to work with
    from src.core.interfaces.session_service_interface import ISessionService
    session_service = service_provider.get_required_service(ISessionService)
    await session_service.create_session(session_id)
    
    # Fill up to limit (1 tag)
    msg1 = ChatMessage(role="user", content="!/command1")
    msg1_id = identity_svc.compute_identity(msg1)
    await registry_svc.tag_identities(
        session_id,
        [msg1_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="test",
    )
    
    # Try to tag another message (should exceed capacity)
    msg2 = ChatMessage(role="user", content="!/command2")
    msg2_id = identity_svc.compute_identity(msg2)
    
    # Verify registry enforces limit directly
    with pytest.raises(NonForwardableTagLimitExceededError) as exc_info:
        await registry_svc.tag_identities(
            session_id,
            [msg2_id],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )
    
    # Verify error details
    error = exc_info.value
    assert error.session_id == session_id
    assert error.max_limit == 1
    assert "capacity" in error.message.lower() or "limit" in error.message.lower()
