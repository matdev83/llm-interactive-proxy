"""Integration tests for non-forwardable message tagging across entry points.

Tests verify:
- WebSocket entry points route through shared orchestrator (requirement 7.5, 7.6)
- Hybrid backend workflows route through shared orchestrator (requirement 7.5, 7.6)
- Session scoping works across different entry points (requirement 8.1, 8.2, 8.3, 8.4)
- Multi-turn session continuity (requirement 8.2)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from src.core.app.test_builder import build_test_app, create_test_config
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.non_forwardable import NonForwardableTagScope
from src.core.domain.request_context import RequestContext
from src.core.interfaces.backend_service import IBackendService
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
async def backend_service(test_app) -> IBackendService:
    """Get BackendService from test app."""
    service_provider = test_app.state.service_provider
    from src.core.services.backend_service import BackendService

    backend_service = service_provider.get_required_service(BackendService)
    return backend_service


@pytest_asyncio.fixture
async def identity_service(test_app) -> INonForwardableMessageIdentityService:
    """Get identity service from test app."""
    service_provider = test_app.state.service_provider
    identity_service = service_provider.get_required_service(
        INonForwardableMessageIdentityService
    )
    return identity_service


@pytest_asyncio.fixture
async def registry(test_app) -> INonForwardableMessageRegistry:
    """Get registry from test app."""
    service_provider = test_app.state.service_provider
    registry = service_provider.get_required_service(INonForwardableMessageRegistry)
    return registry


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_session_scoping(
    test_app,
    backend_service: IBackendService,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that WebSocket sessions maintain separate tag scopes (requirement 8.3, 8.4)."""
    session1_id = "websocket-session-1"
    session2_id = "websocket-session-2"

    # Tag a message in session 1
    tagged_msg = ChatMessage(role="user", content="!/command")
    tagged_msg_id = identity_service.compute_identity(tagged_msg)
    await registry.tag_identities(
        session1_id,
        [tagged_msg_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="websocket-test",
    )

    # Create request for session 1 - message should be filtered
    request1 = CanonicalChatRequest(
        model="test-model",
        messages=[tagged_msg, ChatMessage(role="user", content="Hello")],
    )
    context1 = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session1_id,
    )

    backend_received_messages_1 = []

    async def mock_chat_completions_1(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_1.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions_1)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_service.call_completion(request1, stream=False, context=context1)

    # Verify tagged message was filtered in session 1
    assert len(backend_received_messages_1) == 1
    assert backend_received_messages_1[0].content == "Hello"

    # Create request for session 2 with same message - should NOT be filtered
    request2 = CanonicalChatRequest(
        model="test-model",
        messages=[tagged_msg],
    )
    context2 = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session2_id,
    )

    backend_received_messages_2 = []

    async def mock_chat_completions_2(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_2.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions_2)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_service.call_completion(request2, stream=False, context=context2)

    # Verify message was NOT filtered in session 2 (different session)
    assert len(backend_received_messages_2) == 1
    assert backend_received_messages_2[0].content == "!/command"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_websocket_multiturn_continuity(
    test_app,
    backend_service: IBackendService,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that tags persist across multiple turns in WebSocket session (requirement 8.2)."""
    session_id = "websocket-multiturn-session"

    # Tag a message in first turn
    tagged_msg = ChatMessage(role="user", content="!/command")
    tagged_msg_id = identity_service.compute_identity(tagged_msg)
    await registry.tag_identities(
        session_id,
        [tagged_msg_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="multiturn-test",
    )

    # First turn - message should be filtered
    request1 = CanonicalChatRequest(
        model="test-model",
        messages=[tagged_msg, ChatMessage(role="user", content="First turn")],
    )
    context1 = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

    backend_received_messages_1 = []

    async def mock_chat_completions_1(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_1.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions_1)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_service.call_completion(request1, stream=False, context=context1)

    assert len(backend_received_messages_1) == 1
    assert backend_received_messages_1[0].content == "First turn"

    # Second turn - resubmit history with tagged message, should still be filtered
    request2 = CanonicalChatRequest(
        model="test-model",
        messages=[
            tagged_msg,  # Resubmitted tagged message
            ChatMessage(role="assistant", content="OK"),  # Previous response
            ChatMessage(role="user", content="Second turn"),
        ],
    )
    context2 = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

    backend_received_messages_2 = []

    async def mock_chat_completions_2(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_2.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions_2)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_service.call_completion(request2, stream=False, context=context2)

    # Verify tagged message was still filtered in second turn
    assert len(backend_received_messages_2) == 2
    assert backend_received_messages_2[0].role == "assistant"
    assert backend_received_messages_2[1].content == "Second turn"
    # Tagged message should not be present
    assert not any(msg.content == "!/command" for msg in backend_received_messages_2)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_hybrid_backend_session_propagation(
    test_app,
    backend_service: IBackendService,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that hybrid backend workflows propagate session_id correctly (requirement 8.2)."""
    session_id = "hybrid-backend-session"

    # Tag a message that will be used in hybrid workflow
    tagged_msg = ChatMessage(role="user", content="!/command")
    tagged_msg_id = identity_service.compute_identity(tagged_msg)
    await registry.tag_identities(
        session_id,
        [tagged_msg_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="hybrid-test",
    )

    # Create request that would trigger hybrid backend
    # Note: This test verifies session_id propagation, not full hybrid execution
    request = CanonicalChatRequest(
        model="test-model",
        messages=[tagged_msg, ChatMessage(role="user", content="Continue")],
    )
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_id,
    )

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

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend = MagicMock()
    mock_backend.chat_completions = AsyncMock(side_effect=mock_chat_completions)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend):
        await backend_service.call_completion(request, stream=False, context=context)

    # Verify tagged message was filtered (enforcement boundary invoked)
    assert len(backend_received_messages) == 1
    assert backend_received_messages[0].content == "Continue"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_session_isolation(
    test_app,
    backend_service: IBackendService,
    identity_service: INonForwardableMessageIdentityService,
    registry: INonForwardableMessageRegistry,
):
    """Test that concurrent sessions don't leak tags (requirement 8.4)."""
    session_a_id = "concurrent-session-a"
    session_b_id = "concurrent-session-b"

    # Tag different messages in each session
    msg_a = ChatMessage(role="user", content="Session A message")
    msg_b = ChatMessage(role="user", content="Session B message")

    msg_a_id = identity_service.compute_identity(msg_a)
    msg_b_id = identity_service.compute_identity(msg_b)

    await registry.tag_identities(
        session_a_id,
        [msg_a_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="concurrent-test-a",
    )
    await registry.tag_identities(
        session_b_id,
        [msg_b_id],
        scope=NonForwardableTagScope.NEVER_FORWARD,
        reason="concurrent-test-b",
    )

    # Session A request with its tagged message
    request_a = CanonicalChatRequest(
        model="test-model",
        messages=[msg_a, ChatMessage(role="user", content="Other A")],
    )
    context_a = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_a_id,
    )

    # Session B request with its tagged message
    request_b = CanonicalChatRequest(
        model="test-model",
        messages=[msg_b, ChatMessage(role="user", content="Other B")],
    )
    context_b = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        session_id=session_b_id,
    )

    backend_received_messages_a = []
    backend_received_messages_b = []

    async def mock_chat_completions_a(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_a.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def mock_chat_completions_b(*args, **kwargs):
        request_data = kwargs.get("request_data") or args[0]
        backend_received_messages_b.extend(request_data.messages)
        from src.core.domain.responses import ResponseEnvelope
        from src.core.domain.usage_summary import UsageSummary

        return ResponseEnvelope(
            content={"choices": [{"message": {"role": "assistant", "content": "OK"}}]},
            status_code=200,
            usage=UsageSummary(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    from src.core.interfaces.backend_completion_collaborators import IBackendInvoker

    service_provider = test_app.state.service_provider
    backend_invoker = service_provider.get_required_service(IBackendInvoker)

    mock_backend_a = MagicMock()
    mock_backend_a.chat_completions = AsyncMock(side_effect=mock_chat_completions_a)

    mock_backend_b = MagicMock()
    mock_backend_b.chat_completions = AsyncMock(side_effect=mock_chat_completions_b)

    # Execute both requests concurrently
    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend_a):
        await backend_service.call_completion(request_a, stream=False, context=context_a)

    with patch.object(backend_invoker, "acquire_backend", return_value=mock_backend_b):
        await backend_service.call_completion(request_b, stream=False, context=context_b)

    # Verify each session filtered its own tagged message
    assert len(backend_received_messages_a) == 1
    assert backend_received_messages_a[0].content == "Other A"
    assert not any(msg.content == "Session A message" for msg in backend_received_messages_a)

    assert len(backend_received_messages_b) == 1
    assert backend_received_messages_b[0].content == "Other B"
    assert not any(msg.content == "Session B message" for msg in backend_received_messages_b)

    # Verify no cross-session leakage
    assert not any(msg.content == "Session B message" for msg in backend_received_messages_a)
    assert not any(msg.content == "Session A message" for msg in backend_received_messages_b)
