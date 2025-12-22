"""Tests for SessionKey dataclass."""

from __future__ import annotations

import pytest
from src.core.domain.session_key import SessionKey


class TestSessionKey:
    """Tests for SessionKey dataclass."""

    def test_create_with_all_fields(self) -> None:
        """Test creating SessionKey with all fields."""
        key = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )

        assert key.protocol == "http"
        assert key.primary_id == "trace-123"
        assert key.group_id == "conversation-456"

    def test_create_with_minimal_fields(self) -> None:
        """Test creating SessionKey with only required fields."""
        key = SessionKey(
            protocol="codebuff",
            primary_id="codebuff:ws-789",
        )

        assert key.protocol == "codebuff"
        assert key.primary_id == "codebuff:ws-789"
        assert key.group_id is None

    def test_validation_empty_primary_id_raises_error(self) -> None:
        """Test that empty primary_id raises ValueError."""
        with pytest.raises(ValueError, match="primary_id cannot be empty"):
            SessionKey(
                protocol="http",
                primary_id="",
            )

    def test_validation_whitespace_only_primary_id_raises_error(self) -> None:
        """Test that whitespace-only primary_id raises ValueError."""
        with pytest.raises(ValueError, match="primary_id cannot be empty"):
            SessionKey(
                protocol="http",
                primary_id="   ",
            )

    def test_equality_same_values(self) -> None:
        """Test that two SessionKey instances with same values are equal."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )
        key2 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )

        assert key1 == key2
        assert hash(key1) == hash(key2)

    def test_equality_different_group_id(self) -> None:
        """Test that SessionKey instances with different group_id are not equal."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )
        key2 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-789",
        )

        assert key1 != key2

    def test_equality_different_primary_id(self) -> None:
        """Test that SessionKey instances with different primary_id are not equal."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
        )
        key2 = SessionKey(
            protocol="http",
            primary_id="trace-456",
        )

        assert key1 != key2

    def test_hashability_can_use_as_dict_key(self) -> None:
        """Test that SessionKey can be used as dictionary key."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )
        key2 = SessionKey(
            protocol="codebuff",
            primary_id="codebuff:ws-789",
        )

        mapping = {key1: "value1", key2: "value2"}

        assert mapping[key1] == "value1"
        assert mapping[key2] == "value2"

    def test_string_representation(self) -> None:
        """Test that string representation includes all fields."""
        key = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id="conversation-456",
        )

        repr_str = repr(key)
        assert "http" in repr_str
        assert "trace-123" in repr_str
        assert "conversation-456" in repr_str

    def test_string_representation_no_group_id(self) -> None:
        """Test that string representation works without group_id."""
        key = SessionKey(
            protocol="codebuff",
            primary_id="codebuff:ws-789",
        )

        repr_str = repr(key)
        assert "codebuff" in repr_str
        assert "codebuff:ws-789" in repr_str

    def test_immutability(self) -> None:
        """Test that SessionKey is immutable (frozen dataclass)."""
        from dataclasses import FrozenInstanceError

        key = SessionKey(
            protocol="http",
            primary_id="trace-123",
        )

        with pytest.raises(FrozenInstanceError):
            key.primary_id = "modified"  # type: ignore[misc]

    def test_equality_different_protocol(self) -> None:
        """Test that SessionKey instances with different protocol are not equal."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
        )
        key2 = SessionKey(
            protocol="codebuff",
            primary_id="trace-123",
        )

        assert key1 != key2

    def test_none_group_id_equivalent_to_missing(self) -> None:
        """Test that None group_id is equivalent to missing group_id."""
        key1 = SessionKey(
            protocol="http",
            primary_id="trace-123",
            group_id=None,
        )
        key2 = SessionKey(
            protocol="http",
            primary_id="trace-123",
        )

        assert key1 == key2
        assert hash(key1) == hash(key2)
