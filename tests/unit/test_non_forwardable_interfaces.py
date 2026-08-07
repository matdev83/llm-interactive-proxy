"""
Unit tests for non-forwardable message tagging service interfaces.

Tests coverage for:
- INonForwardableMessageIdentityService: identity computation contract
- INonForwardableMessageRegistry: session-scoped tagging and lookup
- INonForwardableMessageEnforcer: filtering contract with fail-closed behavior

Requirements: 1.2, 1.3, 1.4, 1.9, 1.10, 7.3, 10.1, 12.1
"""

import pytest
from src.core.domain.non_forwardable import (
    MessageIdentity,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageEnforcer,
    INonForwardableMessageIdentityService,
    INonForwardableMessageRegistry,
)


class TestINonForwardableMessageIdentityService:
    """Tests for INonForwardableMessageIdentityService interface contract."""

    def test_interface_has_compute_identity_method(self) -> None:
        """Interface defines compute_identity method."""
        assert hasattr(INonForwardableMessageIdentityService, "compute_identity")
        method = INonForwardableMessageIdentityService.compute_identity
        assert callable(method)

    def test_compute_identity_signature(self) -> None:
        """compute_identity accepts ChatMessage and returns str."""
        # Check method signature via abstract method
        import inspect

        sig = inspect.signature(INonForwardableMessageIdentityService.compute_identity)
        params = list(sig.parameters.keys())
        assert "message" in params
        # Return annotation is MessageIdentity (which is a type alias for str)
        assert sig.return_annotation in (str, MessageIdentity, "MessageIdentity")

    def test_interface_is_abstract(self) -> None:
        """Interface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            INonForwardableMessageIdentityService()  # type: ignore


class TestINonForwardableMessageRegistry:
    """Tests for INonForwardableMessageRegistry interface contract."""

    def test_interface_has_tag_identities_method(self) -> None:
        """Interface defines tag_identities method."""
        assert hasattr(INonForwardableMessageRegistry, "tag_identities")
        method = INonForwardableMessageRegistry.tag_identities
        assert callable(method)

    def test_interface_has_is_tagged_method(self) -> None:
        """Interface defines is_tagged method."""
        assert hasattr(INonForwardableMessageRegistry, "is_tagged")
        method = INonForwardableMessageRegistry.is_tagged
        assert callable(method)

    def test_tag_identities_signature(self) -> None:
        """tag_identities accepts session_id, identities, scope, and reason."""
        import inspect

        sig = inspect.signature(INonForwardableMessageRegistry.tag_identities)
        params = list(sig.parameters.keys())
        assert "session_id" in params
        assert "identities" in params
        assert "scope" in params
        assert "reason" in params

    def test_is_tagged_signature(self) -> None:
        """is_tagged accepts session_id, identity, and scope."""
        import inspect

        sig = inspect.signature(INonForwardableMessageRegistry.is_tagged)
        params = list(sig.parameters.keys())
        assert "session_id" in params
        assert "identity" in params
        assert "scope" in params
        # Return type should be bool (may be string annotation)
        assert sig.return_annotation in (bool, "bool")

    def test_interface_is_abstract(self) -> None:
        """Interface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            INonForwardableMessageRegistry()  # type: ignore


class TestINonForwardableMessageEnforcer:
    """Tests for INonForwardableMessageEnforcer interface contract."""

    def test_interface_has_filter_messages_method(self) -> None:
        """Interface defines filter_messages method."""
        assert hasattr(INonForwardableMessageEnforcer, "filter_messages")
        method = INonForwardableMessageEnforcer.filter_messages
        assert callable(method)

    def test_filter_messages_signature(self) -> None:
        """filter_messages accepts session_id, messages, and context."""
        import inspect

        sig = inspect.signature(INonForwardableMessageEnforcer.filter_messages)
        params = list(sig.parameters.keys())
        assert "session_id" in params
        assert "messages" in params
        assert "context" in params
        # Return type should be tuple[list[ChatMessage], int]
        assert sig.return_annotation != inspect.Signature.empty

    def test_interface_is_abstract(self) -> None:
        """Interface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            INonForwardableMessageEnforcer()  # type: ignore
