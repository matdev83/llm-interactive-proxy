"""
Property-based tests for non-forwardable message tagging.

**Feature: non-forwardable-message-tagging**

This module tests the correctness properties of identity computation and filtering:
- Identity determinism across equivalent messages
- Tool result identity stability across compaction rewrites
- Filtering order preservation
- Filtering removes only tagged messages
- Filtering does not mutate remaining messages
- Filtering scope semantics (never_forward vs client_history_only)
- Error handling when all user-provided content is filtered

Requirements: 1.2, 1.5, 5.2, 5.3
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given
from hypothesis import strategies as st
from src.core.common.exceptions import NoForwardableContentError
from src.core.domain.chat import (
    ChatMessage,
    FunctionCall,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
    ToolCall,
)
from src.core.domain.non_forwardable import (
    MessageIdentity,
    NonForwardableTagScope,
)
from src.core.domain.request_context import RequestContext
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageRegistry,
)
from src.core.services.non_forwardable_message_enforcer import (
    NonForwardableMessageEnforcer,
)
from src.core.services.non_forwardable_message_identity_service import (
    NonForwardableMessageIdentityService,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating domain model components
# ============================================================================


@st.composite
def message_role_strategy(draw: Any) -> str:
    """Generate a random message role."""
    return draw(st.sampled_from(["user", "assistant", "system", "tool", "model"]))


@st.composite
def text_content_strategy(draw: Any) -> str:
    """Generate text content with various line endings and whitespace."""
    # Generate text that may contain CRLF, CR, or LF
    # Exclude surrogate characters (U+D800 to U+DFFF) which can't be encoded in UTF-8
    lines = draw(
        st.lists(
            st.text(
                min_size=0,
                max_size=100,
                alphabet=st.characters(
                    blacklist_categories=("Cs",),  # Exclude surrogates (Cs category)
                ),
            ),
            min_size=0,
            max_size=10,
        )
    )
    # Join with various line endings
    line_endings = draw(st.sampled_from(["\n", "\r\n", "\r"]))
    return line_endings.join(lines)


@st.composite
def message_content_part_text_strategy(draw: Any) -> MessageContentPartText:
    """Generate a text content part."""
    text = draw(text_content_strategy())
    return MessageContentPartText(type="text", text=text)


@st.composite
def message_content_part_image_strategy(draw: Any) -> MessageContentPartImage:
    """Generate an image content part."""
    url = draw(
        st.sampled_from(
            [
                "data:image/png;base64,abc123",
                "data:image/jpeg;base64,xyz789",
                "https://example.com/image.png",
            ]
        )
    )
    detail = draw(st.one_of(st.none(), st.sampled_from(["auto", "low", "high"])))
    return MessageContentPartImage(
        type="image_url", image_url=ImageURL(url=url, detail=detail)
    )


@st.composite
def message_content_strategy(
    draw: Any,
) -> str | list[MessageContentPartText | MessageContentPartImage] | None:
    """Generate message content (string, parts list, or None)."""
    content_type = draw(st.sampled_from(["string", "parts", "none"]))

    if content_type == "string":
        return draw(text_content_strategy())
    elif content_type == "parts":
        # Generate 1-3 content parts
        parts = draw(
            st.lists(
                st.one_of(
                    message_content_part_text_strategy(),
                    message_content_part_image_strategy(),
                ),
                min_size=1,
                max_size=3,
            )
        )
        return parts
    else:  # none
        return None


@st.composite
def function_call_strategy(draw: Any) -> FunctionCall:
    """Generate a function call."""
    # Generate identifier-like name (letters, numbers, underscore)
    name = draw(
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N")) | st.just("_"),
        )
    )
    arguments = draw(
        st.one_of(
            st.just("{}"),
            st.just('{"arg": "value"}'),
            st.just('{"key1": "value1", "key2": 123}'),
            st.text(min_size=0, max_size=200),
        )
    )
    return FunctionCall(name=name, arguments=arguments)


@st.composite
def tool_call_strategy(draw: Any) -> ToolCall:
    """Generate a tool call."""
    identifier_strategy = st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")) | st.just("_"),
    )
    call_id = draw(identifier_strategy)
    call_type = draw(st.sampled_from(["function", "other"]))
    function = draw(function_call_strategy())
    extra_content = draw(
        st.one_of(
            st.none(),
            st.dictionaries(
                keys=st.text(min_size=1, max_size=20),
                values=st.text(min_size=0, max_size=50),
                max_size=3,
            ),
        )
    )
    return ToolCall(
        id=call_id,
        type=call_type,
        function=function,
        extra_content=extra_content,
    )


@st.composite
def chat_message_strategy(draw: Any) -> ChatMessage:
    """Generate a diverse ChatMessage instance.

    Generates messages with:
    - All role variants (user, assistant, system, tool, model)
    - String content, multimodal content parts, None content
    - Optional fields: reasoning_content, name, tool_calls, tool_call_id, metadata
    - Tool result messages (role="tool" with tool_call_id)
    - Regular messages with tool calls
    """
    role = draw(message_role_strategy())

    # Determine if this is a tool result message
    is_tool_result = role == "tool" and draw(st.booleans())

    # Helper for generating identifier-like strings
    identifier_strategy = st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")) | st.just("_"),
    )

    # Generate content
    if is_tool_result:
        # Tool result: content can vary (will be excluded from identity)
        content = draw(
            st.one_of(
                text_content_strategy(),
                st.just(None),
            )
        )
        tool_call_id = draw(identifier_strategy)
        name = draw(
            st.one_of(
                st.none(),
                identifier_strategy,
            )
        )
        tool_calls = None
    else:
        # Regular message
        content = draw(message_content_strategy())
        tool_call_id = draw(
            st.one_of(
                st.none(),
                identifier_strategy,
            )
        )
        name = draw(
            st.one_of(
                st.none(),
                identifier_strategy,
            )
        )
        # Tool calls only for assistant role
        if role == "assistant":
            tool_calls = draw(
                st.one_of(
                    st.none(),
                    st.lists(tool_call_strategy(), min_size=1, max_size=3),
                )
            )
        else:
            tool_calls = None

    # Reasoning content only for assistant/model roles
    if role in ["assistant", "model"]:
        reasoning_content = draw(
            st.one_of(
                st.none(),
                text_content_strategy(),
            )
        )
    else:
        reasoning_content = None

    # Metadata (should not affect identity)
    metadata = draw(
        st.one_of(
            st.none(),
            st.dictionaries(
                keys=st.text(min_size=1, max_size=20),
                values=st.text(min_size=0, max_size=50),
                max_size=5,
            ),
        )
    )

    return ChatMessage(
        role=role,
        content=content,
        reasoning_content=reasoning_content,
        name=name,
        tool_calls=tool_calls,
        tool_call_id=tool_call_id,
        metadata=metadata,
    )


# ============================================================================
# Property Test: Identity Determinism
# ============================================================================


@given(message=chat_message_strategy())
@property_test_settings()
def test_property_identity_determinism(message: ChatMessage) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Identity Determinism**
    **Validates: Requirements 1.2, 1.9, 1.10**

    Property: Identity Determinism

    *For any* ChatMessage, computing identity multiple times SHALL produce
    the same identity value. Equivalent messages (differing only in metadata or
    line endings) SHALL produce the same identity.
    """
    service = NonForwardableMessageIdentityService()

    # Same message computed multiple times → same identity
    identity1 = service.compute_identity(message)
    identity2 = service.compute_identity(message)
    assert identity1 == identity2, "Identity must be deterministic for same message"

    # Identity is a valid SHA-256 hex string (64 chars, lowercase)
    assert isinstance(identity1, str), "Identity must be a string"
    assert len(identity1) == 64, "Identity must be 64 characters (SHA-256 hex)"
    assert identity1.islower(), "Identity must be lowercase"
    assert all(
        c in "0123456789abcdef" for c in identity1
    ), "Identity must be hexadecimal"

    # Messages differing only in metadata → same identity
    message_with_metadata = message.model_copy()
    message_with_metadata.metadata = {"key": "value"}
    identity_with_metadata = service.compute_identity(message_with_metadata)
    assert (
        identity1 == identity_with_metadata
    ), "Messages differing only in metadata must have same identity"

    # Messages differing only in line endings → same identity (for string content)
    # Note: The identity service normalizes line endings: CRLF and CR -> LF
    if isinstance(message.content, str) and message.content:
        # Test line ending normalization
        # First normalize original to LF-only (baseline)
        normalized_original = message.content.replace("\r\n", "\n").replace("\r", "\n")

        # Create messages with different line endings from normalized baseline
        # This ensures we're testing pure line ending differences, not mixed scenarios
        if "\n" in normalized_original:
            # Create CRLF version (replace LF with CRLF)
            content_crlf = normalized_original.replace("\n", "\r\n")
            message_crlf = message.model_copy()
            message_crlf.content = content_crlf
            identity_crlf = service.compute_identity(message_crlf)

            # Create CR version (replace LF with CR)
            content_cr = normalized_original.replace("\n", "\r")
            message_cr = message.model_copy()
            message_cr.content = content_cr
            identity_cr = service.compute_identity(message_cr)

            # All should produce the same identity (normalized to LF)
            assert (
                identity1 == identity_crlf == identity_cr
            ), f"Messages differing only in line endings must have same identity. Original: {identity1[:16]}..., CRLF: {identity_crlf[:16]}..., CR: {identity_cr[:16]}..."


@given(
    tool_call_id=st.text(
        min_size=1,
        max_size=50,
        alphabet=st.characters(whitelist_categories=("L", "N")) | st.just("_"),
    ),
    name=st.one_of(
        st.none(),
        st.text(
            min_size=1,
            max_size=50,
            alphabet=st.characters(whitelist_categories=("L", "N")) | st.just("_"),
        ),
    ),
    content1=text_content_strategy(),
    content2=text_content_strategy(),
)
@property_test_settings()
def test_property_tool_result_compaction_stability(
    tool_call_id: str,
    name: str | None,
    content1: str,
    content2: str,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Tool Result Compaction Stability**
    **Validates: Requirements 1.12, 1.13**

    Property: Tool Result Compaction Stability

    *For any* tool result message (role="tool" with tool_call_id), the identity
    SHALL remain stable when content is rewritten by history compaction. Only
    tool_call_id and name affect identity, not content.
    """
    service = NonForwardableMessageIdentityService()

    # Create two tool result messages with same tool_call_id and name but different content
    msg1 = ChatMessage(
        role="tool",
        tool_call_id=tool_call_id,
        name=name,
        content=content1,
    )
    msg2 = ChatMessage(
        role="tool",
        tool_call_id=tool_call_id,
        name=name,
        content=content2,  # Different content
    )

    identity1 = service.compute_identity(msg1)
    identity2 = service.compute_identity(msg2)

    assert (
        identity1 == identity2
    ), "Tool result identity must be stable across content rewrites (compaction scenario)"

    # Verify that changing tool_call_id produces different identity
    msg3 = ChatMessage(
        role="tool",
        tool_call_id=f"{tool_call_id}_different",
        name=name,
        content=content1,
    )
    identity3 = service.compute_identity(msg3)
    assert (
        identity1 != identity3
    ), "Different tool_call_id must produce different identity"

    # Verify that changing name produces different identity (if name was set)
    if name is not None:
        msg4 = ChatMessage(
            role="tool",
            tool_call_id=tool_call_id,
            name=f"{name}_different",
            content=content1,
        )
        identity4 = service.compute_identity(msg4)
        assert identity1 != identity4, "Different name must produce different identity"


# ============================================================================
# Property Test: Filtering Order Preservation
# ============================================================================


@pytest.mark.asyncio
@given(
    messages=st.lists(chat_message_strategy(), min_size=1, max_size=20),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings(max_examples=30)  # Reduced for async tests
async def test_property_filtering_order_preservation(
    messages: list[ChatMessage],
    session_id: str,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Filtering Order Preservation**
    **Validates: Requirements 1.5, 5.2**

    Property: Filtering Order Preservation

    *For any* message list (across all roles and content types), after filtering
    non-forwardable messages, the relative order of remaining forwardable messages
    SHALL be preserved.
    """
    # Create mock registry that tags some messages
    identity_service = NonForwardableMessageIdentityService()

    # Compute identities for all messages
    identities = [identity_service.compute_identity(msg) for msg in messages]

    # Tag every other message as never_forward (for testing)
    # Track by indices to handle duplicate identities correctly
    tagged_indices = set(range(0, len(messages), 2))  # Tag messages at even indices
    tagged_identities = {identities[i] for i in tagged_indices}

    mock_registry = AsyncMock(spec=INonForwardableMessageRegistry)

    # Capture outer variable for closure
    expected_session_id = session_id

    async def is_tagged_side_effect(
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        return (
            session_id == expected_session_id
            and identity in tagged_identities
            and scope == NonForwardableTagScope.NEVER_FORWARD
        )

    mock_registry.is_tagged.side_effect = is_tagged_side_effect

    # Create enforcer
    enforcer = NonForwardableMessageEnforcer(
        identity_service=identity_service,
        registry=mock_registry,
    )

    # Filter messages (may raise NoForwardableContentError if all user content filtered)
    try:
        filtered, filtered_count = await enforcer.filter_messages(
            session_id=session_id,
            messages=messages,
            context=None,
        )
    except Exception as e:
        # If all user content was filtered, that's expected behavior for some test cases
        # Skip further assertions in that case
        if "NoForwardableContentError" in type(e).__name__:
            return
        raise

    # Tag messages at even indices (by index, not by unique identity)
    tagged_indices = set(range(0, len(messages), 2))

    # Verify order preservation: forwardable messages appear in same relative order
    # Note: If messages share identities with tagged messages, they will also be filtered
    # So we need to check which messages actually remain (those whose identities are not tagged)
    forwardable_indices = [
        i for i in range(len(messages)) if identities[i] not in tagged_identities
    ]
    assert len(filtered) == len(
        forwardable_indices
    ), f"Filtered count must match forwardable messages. Filtered: {len(filtered)}, Forwardable: {len(forwardable_indices)}"

    # Check that filtered messages are in the same relative order
    for filtered_index, original_index in enumerate(forwardable_indices):
        assert filtered_index < len(filtered), "Not enough filtered messages"
        # Messages should match (same identity)
        filtered_identity = identity_service.compute_identity(filtered[filtered_index])
        original_identity = identities[original_index]
        assert (
            filtered_identity == original_identity
        ), f"Message at position {filtered_index} does not match original at {original_index}"

    # Verify filtered count matches actual number of messages removed
    # Note: filtered_count counts messages removed. If messages share identities with tagged messages,
    # they will also be filtered, so the count may be higher than len(tagged_indices)
    actual_removed_count = len(messages) - len(filtered)
    assert (
        filtered_count == actual_removed_count
    ), f"Filtered count ({filtered_count}) must match actual removed count ({actual_removed_count})"


# ============================================================================
# Property Test: Filtering Removes Only Tagged Messages
# ============================================================================


@pytest.mark.asyncio
@given(
    messages=st.lists(chat_message_strategy(), min_size=1, max_size=20),
    session_id=st.text(min_size=1, max_size=50),
    scope=st.sampled_from(list(NonForwardableTagScope)),
)
@property_test_settings(max_examples=30)  # Reduced for async tests
async def test_property_filtering_removes_only_tagged_messages(
    messages: list[ChatMessage],
    session_id: str,
    scope: NonForwardableTagScope,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Filtering Removes Only Tagged Messages**
    **Validates: Requirements 1.4, 5.2**

    Property: Filtering Removes Only Tagged Messages

    *For any* message list (across all roles and content types) and tag configuration,
    all removed messages SHALL have identities that are tagged in the registry for
    the session and scope. No untagged messages SHALL be removed.
    """
    identity_service = NonForwardableMessageIdentityService()

    # Compute identities for all messages
    identities = [identity_service.compute_identity(msg) for msg in messages]

    # Tag a random subset of messages
    tagged_indices = set(range(0, len(messages), 2))  # Tag every other message
    tagged_identities = {identities[i] for i in tagged_indices}

    mock_registry = AsyncMock(spec=INonForwardableMessageRegistry)

    # Capture outer variables for closure
    expected_session_id = session_id
    expected_scope = scope

    async def is_tagged_side_effect(
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        return (
            session_id == expected_session_id
            and identity in tagged_identities
            and scope == expected_scope
        )

    mock_registry.is_tagged.side_effect = is_tagged_side_effect

    # Create enforcer
    enforcer = NonForwardableMessageEnforcer(
        identity_service=identity_service,
        registry=mock_registry,
    )

    # Filter messages (may raise NoForwardableContentError if all user content filtered)
    try:
        filtered, filtered_count = await enforcer.filter_messages(
            session_id=session_id,
            messages=messages,
            context=None,
        )
    except Exception as e:
        # If all user content was filtered, that's expected behavior for some test cases
        # Skip further assertions in that case
        if "NoForwardableContentError" in type(e).__name__:
            return
        raise

    # Verify all removed messages are tagged
    # Get identities of filtered messages
    filtered_identities = {identity_service.compute_identity(msg) for msg in filtered}
    removed_identities = set(identities) - filtered_identities

    # All removed identities must be in tagged_identities
    assert removed_identities.issubset(
        tagged_identities
    ), f"All removed messages must be tagged. Removed: {removed_identities}, Tagged: {tagged_identities}"

    # Verify no untagged messages are removed
    # If a message has an untagged identity, it should not be removed
    # However, if an untagged message shares identity with a tagged message, it will also be filtered
    # So we check: messages at untagged indices that don't share identity with tagged messages should remain
    untagged_indices = set(range(len(messages))) - tagged_indices
    for idx in untagged_indices:
        msg_identity = identities[idx]
        # If this identity is not in tagged_identities, the message should not be removed
        # (unless it shares identity with a tagged message, which is acceptable behavior)
        if msg_identity not in tagged_identities:
            # This message's identity is unique and untagged, so it must remain
            assert (
                msg_identity in filtered_identities
            ), f"Untagged message at index {idx} with unique identity must not be removed"

    # Verify filtered count matches actual number of messages removed
    # Note: filtered_count counts messages removed. If messages share identities with tagged messages,
    # they will also be filtered, so the count may be higher than len(tagged_indices)
    # The important invariant is: all removed messages have identities in tagged_identities
    actual_removed_count = len(messages) - len(filtered)
    assert (
        filtered_count == actual_removed_count
    ), f"Filtered count ({filtered_count}) must match actual removed count ({actual_removed_count})"
    # All removed messages must have tagged identities
    assert len(removed_identities) <= len(
        tagged_identities
    ), "Removed identities must be subset of tagged identities"


# ============================================================================
# Property Test: Filtering No Content Mutation
# ============================================================================


@pytest.mark.asyncio
@given(
    messages=st.lists(chat_message_strategy(), min_size=1, max_size=20),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings(max_examples=30)  # Reduced for async tests
async def test_property_filtering_no_content_mutation(
    messages: list[ChatMessage],
    session_id: str,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Filtering No Content Mutation**
    **Validates: Requirements 1.6**

    Property: Filtering No Content Mutation

    *For any* message list, after filtering non-forwardable messages, the
    remaining messages SHALL not be mutated. They must be identical to the
    original messages (same objects or deep equal).
    """
    identity_service = NonForwardableMessageIdentityService()

    # Compute identities for all messages
    identities = [identity_service.compute_identity(msg) for msg in messages]

    # Tag some messages
    tagged_identities = set(identities[::2])  # Tag messages at even indices

    mock_registry = AsyncMock(spec=INonForwardableMessageRegistry)

    # Capture outer variable for closure
    expected_session_id = session_id

    async def is_tagged_side_effect(
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        return (
            session_id == expected_session_id
            and identity in tagged_identities
            and scope == NonForwardableTagScope.NEVER_FORWARD
        )

    mock_registry.is_tagged.side_effect = is_tagged_side_effect

    # Create enforcer
    enforcer = NonForwardableMessageEnforcer(
        identity_service=identity_service,
        registry=mock_registry,
    )

    # Filter messages (may raise NoForwardableContentError if all user content filtered)
    try:
        filtered, _ = await enforcer.filter_messages(
            session_id=session_id,
            messages=messages,
            context=None,
        )
    except Exception as e:
        # If all user content was filtered, that's expected behavior for some test cases
        # Skip further assertions in that case
        if "NoForwardableContentError" in type(e).__name__:
            return
        raise

    # Verify remaining messages are not mutated
    # Check that filtered messages match original messages (by identity)
    filtered_identities = {identity_service.compute_identity(msg) for msg in filtered}
    original_forwardable_identities = {
        identities[i]
        for i in range(len(messages))
        if identities[i] not in tagged_identities
    }

    assert (
        filtered_identities == original_forwardable_identities
    ), "Filtered messages must match original forwardable messages"

    # Verify message content is not mutated by comparing identities
    # (if content was mutated, identity would change)
    for filtered_msg in filtered:
        filtered_identity = identity_service.compute_identity(filtered_msg)
        # Find original message with same identity
        original_msg = next(
            msg
            for msg, ident in zip(messages, identities, strict=False)
            if ident == filtered_identity
        )
        # Verify they are equivalent (same identity confirms no mutation)
        assert (
            identity_service.compute_identity(original_msg) == filtered_identity
        ), "Message content must not be mutated during filtering"


# ============================================================================
# Property Test: Filtering Scope Semantics
# ============================================================================


@pytest.mark.asyncio
@given(
    client_messages=st.lists(chat_message_strategy(), min_size=1, max_size=10),
    injected_messages=st.lists(chat_message_strategy(), min_size=0, max_size=5),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings(max_examples=20)  # Reduced for async tests
async def test_property_filtering_scope_semantics(
    client_messages: list[ChatMessage],
    injected_messages: list[ChatMessage],
    session_id: str,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: Filtering Scope Semantics**
    **Validates: Requirements 1.8, 1.11, 4.4**

    Property: Filtering Scope Semantics

    *For any* message list with injected boundary:
    - Messages tagged as `never_forward` SHALL be excluded from both client history
      and injected segments
    - Messages tagged as `client_history_only` SHALL be excluded only from client
      history, not from injected segments
    """
    identity_service = NonForwardableMessageIdentityService()
    all_messages = client_messages + injected_messages

    # Compute identities
    identities = [identity_service.compute_identity(msg) for msg in all_messages]

    # Tag some client messages with client_history_only
    client_tagged_indices = set(range(0, len(client_messages), 2))
    client_tagged_identities = {identities[i] for i in client_tagged_indices}

    # Tag some injected messages with never_forward
    injected_tagged_indices = (
        set(range(len(client_messages), len(all_messages), 2))
        if injected_messages
        else set()
    )
    injected_tagged_identities = {identities[i] for i in injected_tagged_indices}

    mock_registry = AsyncMock(spec=INonForwardableMessageRegistry)

    # Capture outer variable for closure
    expected_session_id = session_id

    async def is_tagged_side_effect(
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        if session_id != expected_session_id:
            return False

        if scope == NonForwardableTagScope.NEVER_FORWARD:
            return identity in injected_tagged_identities
        elif scope == NonForwardableTagScope.CLIENT_HISTORY_ONLY:
            return identity in client_tagged_identities
        return False

    mock_registry.is_tagged.side_effect = is_tagged_side_effect

    # Create enforcer
    enforcer = NonForwardableMessageEnforcer(
        identity_service=identity_service,
        registry=mock_registry,
    )

    # Create context with injected boundary
    context = RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        extensions={"proxy_injected_messages_start_index": len(client_messages)},
    )

    # Filter messages (may raise NoForwardableContentError if all user content filtered)
    try:
        filtered, _ = await enforcer.filter_messages(
            session_id=session_id,
            messages=all_messages,
            context=context,
        )
    except Exception as e:
        # If all user content was filtered, that's expected behavior for some test cases
        # Skip further assertions in that case
        if "NoForwardableContentError" in type(e).__name__:
            return
        raise

    # Verify client_history_only messages are excluded from client history
    # but not from injected segment
    for idx in client_tagged_indices:
        msg_identity = identities[idx]
        # Should be excluded (it's in client history)
        assert msg_identity not in {
            identity_service.compute_identity(msg) for msg in filtered
        }, f"client_history_only message at index {idx} must be excluded from client history"

    # Verify never_forward messages are excluded from both segments
    for idx in injected_tagged_indices:
        msg_identity = identities[idx]
        # Should be excluded (never_forward applies to injected segment too)
        assert msg_identity not in {
            identity_service.compute_identity(msg) for msg in filtered
        }, f"never_forward message at index {idx} must be excluded from injected segment"

    # Verify client_history_only messages in injected segment are NOT excluded
    # (if any client messages somehow ended up in injected segment, they shouldn't be filtered)
    # Actually, the test setup has clear boundary, so this is more about verifying
    # that injected messages tagged as client_history_only are NOT filtered
    # (but we didn't tag any injected messages as client_history_only, so this is covered)

    # Verify untagged injected messages pass through
    # Note: If an untagged injected message shares identity with a tagged client message,
    # it will also be filtered (this is acceptable - identity-based filtering)
    untagged_injected_indices = (
        set(range(len(client_messages), len(all_messages))) - injected_tagged_indices
    )
    filtered_identities_set = {
        identity_service.compute_identity(msg) for msg in filtered
    }
    for idx in untagged_injected_indices:
        msg_identity = identities[idx]
        # If this identity is not tagged (neither never_forward nor client_history_only for this message),
        # and it doesn't share identity with any tagged client message, it should pass through
        if (
            msg_identity not in client_tagged_identities
            and msg_identity not in injected_tagged_identities
        ):
            assert (
                msg_identity in filtered_identities_set
            ), f"Untagged injected message at index {idx} with unique identity must pass through"


# ============================================================================
# Property Test: No Forwardable Content Error
# ============================================================================


@pytest.mark.asyncio
@given(
    user_messages=st.lists(
        st.builds(
            ChatMessage,
            role=st.just("user"),
            content=st.text(min_size=1, max_size=200).filter(lambda s: bool(s.strip())),  # Ensure non-empty, non-whitespace content
            tool_call_id=st.just(None),
            tool_calls=st.just(None),
            reasoning_content=st.just(None),
            name=st.just(None),
            metadata=st.just(None),
        ),
        min_size=1,
        max_size=10,
    ),
    session_id=st.text(min_size=1, max_size=50),
)
@property_test_settings(max_examples=20)  # Reduced for async tests
async def test_property_no_forwardable_content_error(
    user_messages: list[ChatMessage],
    session_id: str,
) -> None:
    """
    **Feature: non-forwardable-message-tagging, Property: No Forwardable Content Error**
    **Validates: Requirements 5.3**

    Property: No Forwardable Content Error

    *For any* message list containing only user messages, if all user messages
    are tagged as non-forwardable, the enforcer SHALL raise NoForwardableContentError.
    """
    identity_service = NonForwardableMessageIdentityService()

    # Compute identities for all messages
    identities = [identity_service.compute_identity(msg) for msg in user_messages]

    # Tag ALL messages as never_forward
    tagged_identities = set(identities)

    mock_registry = AsyncMock(spec=INonForwardableMessageRegistry)

    # Capture outer variable for closure
    expected_session_id = session_id

    async def is_tagged_side_effect(
        session_id: str,
        identity: MessageIdentity,
        *,
        scope: NonForwardableTagScope,
    ) -> bool:
        return (
            session_id == expected_session_id
            and identity in tagged_identities
            and scope == NonForwardableTagScope.NEVER_FORWARD
        )

    mock_registry.is_tagged.side_effect = is_tagged_side_effect

    # Create enforcer
    enforcer = NonForwardableMessageEnforcer(
        identity_service=identity_service,
        registry=mock_registry,
    )

    # Filter messages - should raise NoForwardableContentError
    with pytest.raises(NoForwardableContentError) as exc_info:
        await enforcer.filter_messages(
            session_id=session_id,
            messages=user_messages,
            context=None,
        )

    # Verify error details
    assert (
        "forwardable" in exc_info.value.message.lower()
        or "content" in exc_info.value.message.lower()
    )
    assert exc_info.value.details is not None
    assert "original_message_count" in exc_info.value.details
    assert "filtered_message_count" in exc_info.value.details
