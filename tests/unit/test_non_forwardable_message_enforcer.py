"""
Unit tests for non-forwardable message enforcer service.

Tests coverage for:
- Order preservation and no content mutation
- Never-forward and client-history-only semantics
- Injected-message boundary behavior
- Invalid boundary provenance and internal lookup errors fail closed
- No forwardable content error handling

Requirements: 1.4, 1.5, 1.6, 1.8, 4.4, 7.3, 10.1
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import (
    NoForwardableContentError,
    NonForwardableEnforcementError,
)
from src.core.domain.chat import ChatMessage
from src.core.domain.non_forwardable import (
    MessageIdentity,
    NonForwardableTagScope,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageEnforcer,
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)
from src.core.services.non_forwardable_message_enforcer import (
    NonForwardableMessageEnforcer,
)


@pytest.fixture
def mock_identity_service() -> MagicMock:
    """Create mock identity service."""
    mock = MagicMock(spec=INonForwardableMessageIdentityService)
    # Default behavior: return identity based on message content
    def compute_identity(message: ChatMessage) -> MessageIdentity:
        # Simple identity: hash of role + content
        content = message.content or ""
        return f"identity_{message.role}_{hash(str(content)) % 10000}"
    # Set as side_effect so it can be overridden with return_value in tests
    mock.compute_identity.side_effect = compute_identity
    return mock


@pytest.fixture
def mock_registry() -> AsyncMock:
    """Create mock registry service."""
    mock = AsyncMock(spec=INonForwardableMessageRegistry)
    # Default: no messages tagged
    mock.is_tagged = AsyncMock(return_value=False)
    return mock


@pytest.fixture
def enforcer(
    mock_identity_service: MagicMock, mock_registry: AsyncMock
) -> NonForwardableMessageEnforcer:
    """Create enforcer with mocked dependencies."""
    return NonForwardableMessageEnforcer(
        identity_service=mock_identity_service,
        registry=mock_registry,
    )


@pytest.fixture
def user_message() -> ChatMessage:
    """Create a test user message."""
    return ChatMessage(role="user", content="Hello, world!")


@pytest.fixture
def assistant_message() -> ChatMessage:
    """Create a test assistant message."""
    return ChatMessage(role="assistant", content="Hi there!")


@pytest.fixture
def system_message() -> ChatMessage:
    """Create a test system message."""
    return ChatMessage(role="system", content="You are a helpful assistant.")


@pytest.mark.asyncio
class TestOrderPreservation:
    """Tests for order preservation during filtering."""

    async def test_preserves_order_when_no_filtering(
        self, enforcer: NonForwardableMessageEnforcer
    ) -> None:
        """Filtered messages maintain relative order when no messages are filtered."""
        messages = [
            ChatMessage(role="user", content="First"),
            ChatMessage(role="assistant", content="Second"),
            ChatMessage(role="user", content="Third"),
        ]

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages
        )

        assert count == 0
        assert len(filtered) == 3
        assert filtered[0].content == "First"
        assert filtered[1].content == "Second"
        assert filtered[2].content == "Third"

    async def test_preserves_order_when_filtering(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Filtered messages maintain relative order when some messages are filtered."""
        messages = [
            ChatMessage(role="user", content="First"),
            ChatMessage(role="assistant", content="Second"),
            ChatMessage(role="user", content="Third"),
        ]

        # Set up identity service to return predictable identities
        identities = ["id_0", "id_1", "id_2"]

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            for idx, msg in enumerate(messages):
                if msg.content == message.content:
                    return identities[idx]
            return identities[0]

        mock_identity_service.compute_identity = compute_identity

        # Mock: second message is tagged as never_forward
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return identity == "id_1" and scope == NonForwardableTagScope.NEVER_FORWARD

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages
        )

        assert count == 1
        assert len(filtered) == 2
        assert filtered[0].content == "First"
        assert filtered[1].content == "Third"


@pytest.mark.asyncio
class TestNoContentMutation:
    """Tests for ensuring messages are not mutated."""

    async def test_does_not_mutate_remaining_messages(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Remaining messages are not mutated."""
        original_content = "Original content"
        messages = [ChatMessage(role="user", content=original_content)]

        # Set up identity service
        identity = "test_identity"
        mock_identity_service.compute_identity.return_value = identity

        # No messages tagged
        mock_registry.is_tagged.return_value = False

        filtered, _ = await enforcer.filter_messages(
            session_id="test_session", messages=messages
        )

        assert len(filtered) == 1
        assert filtered[0].content == original_content
        # Verify original message was not mutated
        assert messages[0].content == original_content


@pytest.mark.asyncio
class TestNeverForwardScope:
    """Tests for never-forward scope behavior."""

    async def test_excludes_never_forward_from_client_history(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
        user_message: ChatMessage,
    ) -> None:
        """Never-forward messages are excluded from client history."""
        messages = [user_message]
        identity = "user_msg_identity"
        # Override the side_effect with return_value
        mock_identity_service.compute_identity = MagicMock(return_value=identity)

        # Tag as never_forward
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == "user_msg_identity"
                and scope == NonForwardableTagScope.NEVER_FORWARD
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        # When all user content is filtered, should raise NoForwardableContentError
        with pytest.raises(NoForwardableContentError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )

    async def test_excludes_never_forward_from_injected_segment(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Never-forward messages are excluded from injected segment."""
        client_msg = ChatMessage(role="user", content="Client message")
        injected_msg = ChatMessage(role="system", content="Injected message")
        messages = [client_msg, injected_msg]

        client_identity = "client_identity"
        injected_identity = "injected_identity"

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            if message.content == "Client message":
                return client_identity
            return injected_identity

        mock_identity_service.compute_identity = compute_identity

        # Tag injected message as never_forward
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == injected_identity
                and scope == NonForwardableTagScope.NEVER_FORWARD
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 1},
        )

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        assert count == 1
        assert len(filtered) == 1
        assert filtered[0].content == "Client message"


@pytest.mark.asyncio
class TestClientHistoryOnlyScope:
    """Tests for client-history-only scope behavior."""

    async def test_excludes_client_history_only_from_client_history(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Client-history-only messages are excluded from client history."""
        client_msg = ChatMessage(role="user", content="Client message")
        messages = [client_msg]

        identity = "client_identity"
        # Override the side_effect with return_value
        mock_identity_service.compute_identity = MagicMock(return_value=identity)

        # Tag as client_history_only
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == "client_identity"
                and scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        # When all user content is filtered, should raise NoForwardableContentError
        with pytest.raises(NoForwardableContentError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )

    async def test_includes_client_history_only_in_injected_segment(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Client-history-only messages are included in injected segment."""
        client_msg = ChatMessage(role="user", content="Client message")
        injected_msg = ChatMessage(role="system", content="Injected message")
        messages = [client_msg, injected_msg]

        client_identity = "client_identity"
        injected_identity = "injected_identity"

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            if message.content == "Client message":
                return client_identity
            return injected_identity

        mock_identity_service.compute_identity = compute_identity

        # Tag injected message as client_history_only
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == injected_identity
                and scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 1},
        )

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        # Injected message should be included (not filtered)
        assert count == 0
        assert len(filtered) == 2
        assert filtered[0].content == "Client message"
        assert filtered[1].content == "Injected message"


@pytest.mark.asyncio
class TestProvenanceBoundary:
    """Tests for injected-message provenance boundary."""

    async def test_splits_messages_correctly_with_boundary(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Messages are split correctly at provenance boundary."""
        msg1 = ChatMessage(role="user", content="Client 1")
        msg2 = ChatMessage(role="user", content="Client 2")
        msg3 = ChatMessage(role="system", content="Injected 1")
        messages = [msg1, msg2, msg3]

        identities = ["id1", "id2", "id3"]

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            for idx, msg in enumerate(messages):
                if msg.content == message.content:
                    return identities[idx]
            return identities[0]

        mock_identity_service.compute_identity = compute_identity

        # No messages tagged
        mock_registry.is_tagged.return_value = False

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 2},
        )

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        # All messages should pass through
        assert count == 0
        assert len(filtered) == 3

    async def test_boundary_at_end_of_messages_is_valid(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Boundary value equal to len(messages) is valid (all messages are client history)."""
        msg1 = ChatMessage(role="user", content="Client 1")
        msg2 = ChatMessage(role="user", content="Client 2")
        messages = [msg1, msg2]

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            return f"id_{message.content}"

        mock_identity_service.compute_identity = compute_identity
        mock_registry.is_tagged.return_value = False

        # Boundary at end means all messages are client history, none are injected
        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": len(messages)},
        )

        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        # Should succeed - all messages are client history
        assert count == 0
        assert len(filtered) == 2

    async def test_filters_client_history_against_both_scopes(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Client history is filtered against both scopes."""
        client_msg = ChatMessage(role="user", content="Client message")
        injected_msg = ChatMessage(role="system", content="Injected message")
        messages = [client_msg, injected_msg]

        client_identity = "client_identity"
        injected_identity = "injected_identity"

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            if message.content == "Client message":
                return client_identity
            return injected_identity

        mock_identity_service.compute_identity = compute_identity

        # Tag client message as client_history_only
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == client_identity
                and scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 1},
        )

        # When client history is filtered but injected messages remain,
        # we should not raise NoForwardableContentError
        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        # Client message should be filtered, injected should remain
        assert count == 1
        assert len(filtered) == 1
        assert filtered[0].content == "Injected message"


@pytest.mark.asyncio
class TestInvalidBoundary:
    """Tests for invalid boundary handling."""

    async def test_raises_error_for_negative_boundary(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
    ) -> None:
        """Raises NonForwardableEnforcementError for negative boundary."""
        messages = [ChatMessage(role="user", content="Test")]

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": -1},
        )

        with pytest.raises(NonForwardableEnforcementError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages, context=context
            )

    async def test_raises_error_for_boundary_exceeding_length(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
    ) -> None:
        """Raises NonForwardableEnforcementError for boundary exceeding message length."""
        messages = [ChatMessage(role="user", content="Test")]

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 10},
        )

        with pytest.raises(NonForwardableEnforcementError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages, context=context
            )

    async def test_raises_error_for_non_integer_boundary(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
    ) -> None:
        """Raises NonForwardableEnforcementError for non-integer boundary."""
        messages = [ChatMessage(role="user", content="Test")]

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": "invalid"},
        )

        with pytest.raises(NonForwardableEnforcementError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages, context=context
            )


@pytest.mark.asyncio
class TestNoForwardableContent:
    """Tests for no forwardable content error handling."""

    async def test_raises_error_when_all_user_content_filtered(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Raises NoForwardableContentError when all user-provided content is filtered."""
        user_msg = ChatMessage(role="user", content="User message")
        messages = [user_msg]

        identity = "user_identity"
        # Override the side_effect with return_value
        mock_identity_service.compute_identity = MagicMock(return_value=identity)

        # Tag as never_forward
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == "user_identity"
                and scope == NonForwardableTagScope.NEVER_FORWARD
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        with pytest.raises(NoForwardableContentError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )

    async def test_allows_system_messages_when_user_content_filtered(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """System messages alone are not considered forwardable user content."""
        system_msg = ChatMessage(role="system", content="System message")
        messages = [system_msg]

        identity = "system_identity"
        mock_identity_service.compute_identity.return_value = identity

        # No messages tagged
        mock_registry.is_tagged.return_value = False

        # Should not raise error - system messages can pass through
        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages
        )

        assert count == 0
        assert len(filtered) == 1

    async def test_allows_injected_messages_when_client_history_filtered(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """When client history is filtered but injected messages remain, request succeeds (requirement 4.4)."""
        client_msg = ChatMessage(role="user", content="Client message")
        injected_msg = ChatMessage(role="system", content="Injected message")
        messages = [client_msg, injected_msg]

        client_identity = "client_identity"
        injected_identity = "injected_identity"

        def compute_identity(message: ChatMessage) -> MessageIdentity:
            if message.content == "Client message":
                return client_identity
            return injected_identity

        mock_identity_service.compute_identity = compute_identity

        # Tag client message as client_history_only (will be filtered)
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == client_identity
                and scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 1},
        )

        # Should succeed - injected message remains even though client history is filtered
        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=messages, context=context
        )

        assert count == 1  # Client message filtered
        assert len(filtered) == 1  # Injected message remains
        assert filtered[0].content == "Injected message"

    async def test_raises_error_when_client_history_filtered_and_no_injected_messages(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """When client history is filtered and no injected messages remain, raise error (requirement 5.3)."""
        client_msg = ChatMessage(role="user", content="Client message")
        messages = [client_msg]

        client_identity = "client_identity"
        # Clear side_effect from fixture so return_value works
        mock_identity_service.compute_identity.side_effect = None
        mock_identity_service.compute_identity.return_value = client_identity

        # Tag client message as client_history_only (will be filtered)
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == client_identity
                and scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            extensions={"proxy_injected_messages_start_index": 1},  # No injected messages
        )

        # Should raise error - all user-provided content filtered and no injected messages
        with pytest.raises(NoForwardableContentError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages, context=context
            )


@pytest.mark.asyncio
class TestIdentityLookupErrors:
    """Tests for identity lookup error handling."""

    async def test_raises_error_on_registry_lookup_failure(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Raises NonForwardableEnforcementError on registry lookup failure."""
        messages = [ChatMessage(role="user", content="Test")]

        identity = "test_identity"
        mock_identity_service.compute_identity.return_value = identity

        # Registry raises exception
        mock_registry.is_tagged.side_effect = Exception("Registry error")

        with pytest.raises(NonForwardableEnforcementError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )

    async def test_raises_error_on_identity_computation_failure(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Raises NonForwardableEnforcementError on identity computation failure."""
        messages = [ChatMessage(role="user", content="Test")]

        # Identity service raises exception
        mock_identity_service.compute_identity.side_effect = Exception("Identity error")

        with pytest.raises(NonForwardableEnforcementError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )


@pytest.mark.asyncio
class TestEdgeCases:
    """Tests for edge cases."""

    async def test_empty_message_list(
        self, enforcer: NonForwardableMessageEnforcer
    ) -> None:
        """Empty message list is handled correctly."""
        filtered, count = await enforcer.filter_messages(
            session_id="test_session", messages=[]
        )

        assert count == 0
        assert len(filtered) == 0

    async def test_empty_session_id_raises_error(
        self, enforcer: NonForwardableMessageEnforcer
    ) -> None:
        """Empty session_id raises NonForwardableEnforcementError."""
        messages = [ChatMessage(role="user", content="Test")]

        with pytest.raises(NonForwardableEnforcementError) as exc_info:
            await enforcer.filter_messages(session_id="", messages=messages)

        assert "session_id must be non-empty" in str(exc_info.value)

    async def test_multiple_scopes_on_same_message(
        self,
        enforcer: NonForwardableMessageEnforcer,
        mock_registry: AsyncMock,
        mock_identity_service: MagicMock,
    ) -> None:
        """Message tagged with never_forward scope is filtered correctly."""
        messages = [ChatMessage(role="user", content="Test")]

        identity = "test_identity"
        # Override the side_effect with return_value
        mock_identity_service.compute_identity = MagicMock(return_value=identity)

        # Tagged with never_forward (should be filtered)
        async def is_tagged_side_effect(
            session_id: str, identity: MessageIdentity, *, scope: NonForwardableTagScope
        ) -> bool:
            return (
                identity == "test_identity"
                and scope == NonForwardableTagScope.NEVER_FORWARD
            )

        mock_registry.is_tagged.side_effect = is_tagged_side_effect

        # When all user content is filtered, should raise NoForwardableContentError
        with pytest.raises(NoForwardableContentError):
            await enforcer.filter_messages(
                session_id="test_session", messages=messages
            )
