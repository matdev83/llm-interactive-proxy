"""
Unit tests for non-forwardable message tagging domain models.

Tests coverage for:
- NonForwardableTagScope: enum values and string representation
- MessageIdentity: type alias for SHA-256 hex digest
- NonForwardableMessageTag: compact tag record structure

Requirements: 1.1, 1.7, 1.8, 14.1
"""

from src.core.domain.non_forwardable import (
    MessageIdentity,
    NonForwardableMessageTag,
    NonForwardableTagScope,
)


class TestNonForwardableTagScope:
    """Tests for NonForwardableTagScope enum."""

    def test_enum_values(self) -> None:
        """Enum has correct values."""
        assert NonForwardableTagScope.NEVER_FORWARD == "never_forward"
        assert NonForwardableTagScope.CLIENT_HISTORY_ONLY == "client_history_only"

    def test_enum_string_representation(self) -> None:
        """Enum values are strings."""
        assert isinstance(NonForwardableTagScope.NEVER_FORWARD, str)
        assert isinstance(NonForwardableTagScope.CLIENT_HISTORY_ONLY, str)
        # For str Enum, the value itself is the string
        assert NonForwardableTagScope.NEVER_FORWARD == "never_forward"
        assert NonForwardableTagScope.CLIENT_HISTORY_ONLY == "client_history_only"

    def test_enum_membership(self) -> None:
        """Can check membership in enum."""
        assert NonForwardableTagScope.NEVER_FORWARD in NonForwardableTagScope
        assert NonForwardableTagScope.CLIENT_HISTORY_ONLY in NonForwardableTagScope
        # Check that values exist
        assert (
            NonForwardableTagScope("never_forward")
            == NonForwardableTagScope.NEVER_FORWARD
        )
        assert (
            NonForwardableTagScope("client_history_only")
            == NonForwardableTagScope.CLIENT_HISTORY_ONLY
        )


class TestMessageIdentity:
    """Tests for MessageIdentity type alias."""

    def test_message_identity_is_string(self) -> None:
        """MessageIdentity is a type alias for str."""
        identity: MessageIdentity = "a" * 64  # SHA-256 hex is 64 chars
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_message_identity_format(self) -> None:
        """MessageIdentity should be lowercase hex string."""
        # Valid SHA-256 hex digest
        valid_identity: MessageIdentity = (
            "a1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456"
        )
        assert len(valid_identity) == 64
        assert all(c in "0123456789abcdef" for c in valid_identity)


class TestNonForwardableMessageTag:
    """Tests for NonForwardableMessageTag domain model."""

    def test_tag_creation(self) -> None:
        """Can create a tag with required fields."""
        identity: MessageIdentity = "a" * 64
        tag = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test_reason",
        )
        assert tag.identity == identity
        assert tag.scope == NonForwardableTagScope.NEVER_FORWARD
        assert tag.reason == "test_reason"

    def test_tag_fixed_size_identity(self) -> None:
        """Tag uses fixed-size identity representation."""
        identity: MessageIdentity = "a" * 64
        tag = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )
        # Identity is a hash string, not full message content
        assert isinstance(tag.identity, str)
        assert len(tag.identity) == 64

    def test_tag_compact_structure(self) -> None:
        """Tag record is compact (no message content retention)."""
        identity: MessageIdentity = "a" * 64
        tag = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
            reason="steering_injection",
        )
        # Tag should not contain message content
        assert not hasattr(tag, "content")
        assert not hasattr(tag, "message")
        # Only identity, scope, and reason
        assert hasattr(tag, "identity")
        assert hasattr(tag, "scope")
        assert hasattr(tag, "reason")

    def test_tag_equality(self) -> None:
        """Tags with same identity and scope are equal."""
        identity: MessageIdentity = "a" * 64
        tag1 = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="reason1",
        )
        tag2 = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="reason2",  # Different reason should not affect equality
        )
        assert tag1 == tag2

    def test_tag_inequality_different_identity(self) -> None:
        """Tags with different identities are not equal."""
        identity1: MessageIdentity = "a" * 64
        identity2: MessageIdentity = "b" * 64
        tag1 = NonForwardableMessageTag(
            identity=identity1,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )
        tag2 = NonForwardableMessageTag(
            identity=identity2,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )
        assert tag1 != tag2

    def test_tag_inequality_different_scope(self) -> None:
        """Tags with different scopes are not equal."""
        identity: MessageIdentity = "a" * 64
        tag1 = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )
        tag2 = NonForwardableMessageTag(
            identity=identity,
            scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
            reason="test",
        )
        assert tag1 != tag2
