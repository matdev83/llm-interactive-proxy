"""
Unit tests for non-forwardable message registry service.

Tests coverage for:
- Registry immutability (append-only, never removed)
- Deduplication (re-tagging doesn't increase state)
- Per-session limit enforcement
- Session isolation
- Tag lookup behavior

Requirements: 1.3, 10.1, 14.2, 14.3
"""

from __future__ import annotations

import pytest
from src.core.common.exceptions import NonForwardableTagLimitExceededError
from src.core.config.app_config import AppConfig
from src.core.config.models.non_forwardable_config import NonForwardableTaggingConfig
from src.core.domain.non_forwardable import (
    NonForwardableTagScope,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageRegistry,
)
from src.core.services.non_forwardable_message_registry import (
    NonForwardableMessageRegistry,
)


@pytest.fixture
def app_config_default() -> AppConfig:
    """Create AppConfig with default tag limit (10000)."""
    return AppConfig()


@pytest.fixture
def app_config_small_limit() -> AppConfig:
    """Create AppConfig with small tag limit for testing."""
    config = AppConfig()
    # Use model_copy to create a new config with modified non_forwardable_tagging
    return config.model_copy(
        update={
            "non_forwardable_tagging": NonForwardableTaggingConfig(
                max_identities_per_session=5
            )
        }
    )


@pytest.fixture
def registry_default(app_config_default: AppConfig) -> NonForwardableMessageRegistry:
    """Create registry with default config."""
    return NonForwardableMessageRegistry(app_config_default)


@pytest.fixture
def registry_small_limit(
    app_config_small_limit: AppConfig,
) -> NonForwardableMessageRegistry:
    """Create registry with small limit for testing."""
    return NonForwardableMessageRegistry(app_config_small_limit)


@pytest.mark.asyncio
class TestRegistryImmutability:
    """Tests for registry immutability (append-only behavior)."""

    async def test_tags_cannot_be_removed(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Tags cannot be removed once added (append-only)."""
        session_id = "test_session"
        identity = "test_identity_1"

        # Tag an identity
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Verify it's tagged
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

        # Re-tagging same identity+scope should be idempotent (no state increase)
        # But the tag should still exist
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test_again",
        )

        # Tag should still exist
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_re_tagging_is_idempotent(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Re-tagging same identity+scope is idempotent (no state increase)."""
        session_id = "test_session"
        identity = "test_identity_1"

        # Tag an identity
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Get initial count (by checking internal state via is_tagged)
        initial_tagged = await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert initial_tagged is True

        # Re-tag same identity+scope
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test_again",
        )

        # Should still be tagged (idempotent)
        still_tagged = await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert still_tagged is True

    async def test_tags_persist_across_multiple_calls(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Tags persist across multiple tag_identities calls."""
        session_id = "test_session"
        identity1 = "test_identity_1"
        identity2 = "test_identity_2"
        identity3 = "test_identity_3"

        # Tag first identity
        await registry_default.tag_identities(
            session_id,
            [identity1],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="first",
        )

        # Tag second identity
        await registry_default.tag_identities(
            session_id,
            [identity2],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="second",
        )

        # Tag third identity
        await registry_default.tag_identities(
            session_id,
            [identity3],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="third",
        )

        # All should be tagged
        assert await registry_default.is_tagged(
            session_id, identity1, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert await registry_default.is_tagged(
            session_id, identity2, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert await registry_default.is_tagged(
            session_id, identity3, scope=NonForwardableTagScope.NEVER_FORWARD
        )


@pytest.mark.asyncio
class TestDeduplication:
    """Tests for tag deduplication behavior."""

    async def test_same_identity_scope_multiple_times_no_increase(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Tagging same identity+scope multiple times doesn't increase stored count."""
        session_id = "test_session"
        identity = "test_identity_1"

        # Tag multiple times
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="first",
        )
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="second",
        )
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="third",
        )

        # Should still be tagged (deduplication via set operations)
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_different_scopes_create_separate_tags(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Different scopes for same identity create separate tags."""
        session_id = "test_session"
        identity = "test_identity_1"

        # Tag with NEVER_FORWARD scope
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="never_forward",
        )

        # Tag with CLIENT_HISTORY_ONLY scope
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY,
            reason="client_history_only",
        )

        # Both scopes should be tagged
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY
        )

    async def test_batch_tagging_with_duplicates_only_stores_unique(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Batch tagging with duplicates only stores unique tags."""
        session_id = "test_session"
        identity = "test_identity_1"

        # Tag same identity multiple times in one call (should deduplicate)
        await registry_default.tag_identities(
            session_id,
            [identity, identity, identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="batch",
        )

        # Should be tagged (only once stored due to set deduplication)
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )


@pytest.mark.asyncio
class TestLimitEnforcement:
    """Tests for per-session limit enforcement."""

    async def test_tagging_within_limit_succeeds(
        self, registry_small_limit: NonForwardableMessageRegistry
    ) -> None:
        """Tagging within limit succeeds."""
        session_id = "test_session"
        identities = ["id1", "id2", "id3"]

        # Should succeed (limit is 5, adding 3)
        await registry_small_limit.tag_identities(
            session_id,
            identities,
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # All should be tagged
        for identity in identities:
            assert await registry_small_limit.is_tagged(
                session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
            )

    async def test_tagging_exceeds_limit_raises_error(
        self, registry_small_limit: NonForwardableMessageRegistry
    ) -> None:
        """Tagging that would exceed limit raises NonForwardableTagLimitExceededError."""
        session_id = "test_session"

        # Fill up to limit (5)
        await registry_small_limit.tag_identities(
            session_id,
            ["id1", "id2", "id3", "id4", "id5"],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="fill",
        )

        # Attempting to add one more should fail
        with pytest.raises(NonForwardableTagLimitExceededError) as exc_info:
            await registry_small_limit.tag_identities(
                session_id,
                ["id6"],
                scope=NonForwardableTagScope.NEVER_FORWARD,
                reason="overflow",
            )

        # Verify error details
        error = exc_info.value
        assert error.session_id == session_id
        assert error.max_limit == 5
        assert "capacity exceeded" in error.message.lower()

    async def test_error_includes_session_id_and_max_limit(
        self, registry_small_limit: NonForwardableMessageRegistry
    ) -> None:
        """Error includes session_id and max_limit in details."""
        session_id = "test_session_123"

        # Fill up to limit
        await registry_small_limit.tag_identities(
            session_id,
            ["id1", "id2", "id3", "id4", "id5"],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="fill",
        )

        # Attempt overflow
        with pytest.raises(NonForwardableTagLimitExceededError) as exc_info:
            await registry_small_limit.tag_identities(
                session_id,
                ["id6"],
                scope=NonForwardableTagScope.NEVER_FORWARD,
                reason="overflow",
            )

        error = exc_info.value
        assert error.session_id == session_id
        assert error.max_limit == 5
        assert session_id in str(error)
        assert "5" in str(error)  # max_limit should be in error message

    async def test_limit_check_happens_before_adding_atomic(
        self, registry_small_limit: NonForwardableMessageRegistry
    ) -> None:
        """Limit check happens before any tags are added (atomic)."""
        session_id = "test_session"

        # Fill up to limit (5)
        await registry_small_limit.tag_identities(
            session_id,
            ["id1", "id2", "id3", "id4", "id5"],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="fill",
        )

        # Attempting to add multiple identities that would exceed limit
        # Should fail without adding any of them
        with pytest.raises(NonForwardableTagLimitExceededError):
            await registry_small_limit.tag_identities(
                session_id,
                ["id6", "id7", "id8"],
                scope=NonForwardableTagScope.NEVER_FORWARD,
                reason="overflow",
            )

        # Verify none of the overflow identities were added
        assert not await registry_small_limit.is_tagged(
            session_id, "id6", scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert not await registry_small_limit.is_tagged(
            session_id, "id7", scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert not await registry_small_limit.is_tagged(
            session_id, "id8", scope=NonForwardableTagScope.NEVER_FORWARD
        )

        # Verify original 5 are still there
        for i in range(1, 6):
            assert await registry_small_limit.is_tagged(
                session_id, f"id{i}", scope=NonForwardableTagScope.NEVER_FORWARD
            )


@pytest.mark.asyncio
class TestSessionIsolation:
    """Tests for session isolation."""

    async def test_tags_in_one_session_dont_affect_another(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Tags in one session don't affect another session."""
        session1 = "session_1"
        session2 = "session_2"
        identity = "shared_identity"

        # Tag in session1
        await registry_default.tag_identities(
            session1,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Should be tagged in session1
        assert await registry_default.is_tagged(
            session1, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

        # Should NOT be tagged in session2
        assert not await registry_default.is_tagged(
            session2, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_same_identity_scope_can_exist_in_multiple_sessions(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Same identity+scope can exist in multiple sessions independently."""
        session1 = "session_1"
        session2 = "session_2"
        identity = "shared_identity"

        # Tag in both sessions
        await registry_default.tag_identities(
            session1,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test1",
        )
        await registry_default.tag_identities(
            session2,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test2",
        )

        # Both should be tagged in their respective sessions
        assert await registry_default.is_tagged(
            session1, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )
        assert await registry_default.is_tagged(
            session2, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_limit_is_per_session_not_global(
        self, registry_small_limit: NonForwardableMessageRegistry
    ) -> None:
        """Limit is per-session, not global."""
        session1 = "session_1"
        session2 = "session_2"

        # Fill session1 to limit (5)
        await registry_small_limit.tag_identities(
            session1,
            ["id1", "id2", "id3", "id4", "id5"],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="fill1",
        )

        # Fill session2 to limit (5) - should succeed (separate limit)
        await registry_small_limit.tag_identities(
            session2,
            ["id6", "id7", "id8", "id9", "id10"],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="fill2",
        )

        # Both sessions should have their tags
        for i in range(1, 6):
            assert await registry_small_limit.is_tagged(
                session1, f"id{i}", scope=NonForwardableTagScope.NEVER_FORWARD
            )
        for i in range(6, 11):
            assert await registry_small_limit.is_tagged(
                session2, f"id{i}", scope=NonForwardableTagScope.NEVER_FORWARD
            )


@pytest.mark.asyncio
class TestLookup:
    """Tests for tag lookup behavior."""

    async def test_is_tagged_returns_true_for_tagged_identity_scope(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """is_tagged() returns True for tagged identity+scope."""
        session_id = "test_session"
        identity = "test_identity"

        # Tag the identity
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Should return True
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_is_tagged_returns_false_for_untagged_identity(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """is_tagged() returns False for untagged identity+scope."""
        session_id = "test_session"
        identity = "untagged_identity"

        # Should return False (never tagged)
        assert not await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

    async def test_is_tagged_returns_false_for_wrong_scope(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """is_tagged() returns False for wrong scope even if identity is tagged with different scope."""
        session_id = "test_session"
        identity = "test_identity"

        # Tag with NEVER_FORWARD scope
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Should return True for correct scope
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

        # Should return False for different scope
        assert not await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.CLIENT_HISTORY_ONLY
        )

    async def test_is_tagged_returns_false_for_nonexistent_session(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """is_tagged() returns False for nonexistent session."""
        session_id = "nonexistent_session"
        identity = "any_identity"

        # Should return False (session doesn't exist)
        assert not await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )


@pytest.mark.asyncio
class TestInterfaceCompliance:
    """Tests for interface compliance."""

    async def test_registry_implements_interface(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Registry implements INonForwardableMessageRegistry interface."""
        assert isinstance(registry_default, INonForwardableMessageRegistry)

    async def test_empty_session_id_raises_error(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Empty session_id raises ValueError."""
        with pytest.raises(ValueError, match="session_id must be non-empty"):
            await registry_default.tag_identities(
                "", ["id1"], scope=NonForwardableTagScope.NEVER_FORWARD, reason="test"
            )

        with pytest.raises(ValueError, match="session_id must be non-empty"):
            await registry_default.is_tagged(
                "", "id1", scope=NonForwardableTagScope.NEVER_FORWARD
            )

    async def test_empty_identities_list_is_idempotent(
        self, registry_default: NonForwardableMessageRegistry
    ) -> None:
        """Empty identities list is handled gracefully (idempotent operation)."""
        session_id = "test_session"

        # Tagging with empty list should not raise error
        await registry_default.tag_identities(
            session_id, [], scope=NonForwardableTagScope.NEVER_FORWARD, reason="test"
        )

        # Should not affect existing tags
        identity = "test_identity"
        await registry_default.tag_identities(
            session_id,
            [identity],
            scope=NonForwardableTagScope.NEVER_FORWARD,
            reason="test",
        )

        # Tag should still be present
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )

        # Tagging with empty list again should still be idempotent
        await registry_default.tag_identities(
            session_id, [], scope=NonForwardableTagScope.NEVER_FORWARD, reason="test"
        )

        # Tag should still be present
        assert await registry_default.is_tagged(
            session_id, identity, scope=NonForwardableTagScope.NEVER_FORWARD
        )
