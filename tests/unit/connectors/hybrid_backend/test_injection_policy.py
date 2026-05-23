"""Unit tests for InjectionPolicy service.

Tests cover injection decision logic including first-turn forcing,
probability-based injection, adaptive backoff, and state management.

Requirements satisfied:
- Req 8: Injection Policy Extraction
- Req 11: Test-preserving migration
"""

import random
from unittest.mock import MagicMock

import pytest
from src.connectors.hybrid_backend.models.injection_decision import InjectionDecision
from src.connectors.hybrid_backend.protocols import IInjectionPolicy
from src.core.domain.configuration.app_identity_config import AppIdentityConfig


class TestInjectionPolicy:
    """Test InjectionPolicy service implementation."""

    @pytest.fixture
    def config(self):
        """Create a mock AppConfig for testing."""
        config = MagicMock()
        config.backends.reasoning_injection_probability = 0.5
        config.backends.hybrid_reasoning_force_initial_turns = 0
        return config

    @pytest.fixture
    def policy(self, config):
        """Create an InjectionPolicy instance for testing."""
        from src.connectors.hybrid_backend.orchestration.injection_policy import (
            InjectionPolicy,
        )

        return InjectionPolicy(config=config)

    def test_policy_implements_protocol(self, policy):
        """Verify policy implements IInjectionPolicy protocol."""
        assert isinstance(policy, IInjectionPolicy)

    def test_first_turn_forcing(self, policy):
        """Test that first turn always forces injection."""
        processed_messages = [{"role": "user", "content": "hello"}]
        request_messages = None

        decision = policy.should_inject(
            processed_messages=processed_messages,
            request_messages=request_messages,
        )

        assert decision.should_inject is True
        assert decision.is_first_turn is True
        assert "first" in decision.reason.lower()

    def test_first_turn_with_empty_messages(self, policy):
        """Test that empty messages are treated as first turn."""
        decision = policy.should_inject(
            processed_messages=None,
            request_messages=None,
        )

        assert decision.should_inject is True
        assert decision.is_first_turn is True

    def test_not_first_turn_with_assistant_message(self, policy):
        """Test that assistant message indicates not first turn."""
        processed_messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "how are you"},
        ]

        decision = policy.should_inject(
            processed_messages=processed_messages,
            request_messages=None,
        )

        assert decision.is_first_turn is False

    def test_forced_initial_turns_window(self, policy, config):
        """Test forced initial turns window."""
        config.backends.hybrid_reasoning_force_initial_turns = 3
        identity = AppIdentityConfig(session_turn_count=2)

        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=None,
            identity=identity,
        )

        assert decision.should_inject is True
        assert (
            "initial turns" in decision.reason.lower()
            or "force" in decision.reason.lower()
        )

    def test_forced_initial_turns_boundary(self, policy, config):
        """Test forced initial turns boundary (turn_count == limit)."""
        config.backends.hybrid_reasoning_force_initial_turns = 3
        identity = AppIdentityConfig(session_turn_count=3)

        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=None,
            identity=identity,
        )

        assert decision.should_inject is True

    def test_forced_initial_turns_expired(self, policy, config):
        """Test that forced initial turns expires after limit."""
        config.backends.hybrid_reasoning_force_initial_turns = 3
        identity = AppIdentityConfig(session_turn_count=4)

        # Set random seed for deterministic test
        random.seed(42)
        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=None,
            identity=identity,
        )

        # Should use probability-based decision (not forced)
        assert decision.is_first_turn is False
        # May or may not inject based on probability

    def test_probability_based_injection(self, policy):
        """Test probability-based injection with deterministic seed."""
        random.seed(123)
        decision1 = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=0.8,  # High probability
        )

        random.seed(123)
        decision2 = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=0.8,
        )

        # Should be deterministic with same seed
        assert decision1.should_inject == decision2.should_inject
        assert decision1.probability_used == 0.8
        assert decision2.probability_used == 0.8

    def test_probability_override(self, policy):
        """Test probability override parameter."""
        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=0.9,
        )

        assert decision.probability_used == 0.9

    def test_adaptive_backoff_active(self, policy):
        """Test adaptive backoff prevents injection."""
        # Set backoff state
        policy._reasoning_backoff_remaining = 2

        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
        )

        assert decision.should_inject is False
        assert "backoff" in decision.reason.lower()
        # Backoff counter should be decremented
        assert policy._reasoning_backoff_remaining == 1

    def test_adaptive_backoff_ignored_on_first_turn(self, policy):
        """Test that backoff is ignored on first turn."""
        policy._reasoning_backoff_remaining = 2

        decision = policy.should_inject(
            processed_messages=[{"role": "user", "content": "hello"}],
            request_messages=None,
        )

        assert decision.should_inject is True
        assert decision.is_first_turn is True
        # Backoff should not be decremented on first turn
        assert policy._reasoning_backoff_remaining == 2

    def test_adaptive_backoff_ignored_in_forced_window(self, policy, config):
        """Test that backoff is ignored in forced initial turns window."""
        config.backends.hybrid_reasoning_force_initial_turns = 3
        policy._reasoning_backoff_remaining = 2
        identity = AppIdentityConfig(session_turn_count=2)

        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            identity=identity,
        )

        assert decision.should_inject is True
        # Backoff should not be decremented in forced window
        assert policy._reasoning_backoff_remaining == 2

    def test_update_backoff_on_success(self, policy, config):
        """Test that backoff is reset on successful reasoning."""
        policy._reasoning_backoff_remaining = 2

        policy.update_backoff(success=True)

        assert policy._reasoning_backoff_remaining == 0

    def test_update_backoff_on_failure(self, policy, config):
        """Test that backoff is set on failed reasoning."""
        policy._reasoning_backoff_remaining = 0
        config.backends.hybrid_reasoning_backoff_turns = 3

        policy.update_backoff(success=False)

        assert policy._reasoning_backoff_remaining == 3

    def test_update_backoff_increments_existing(self, policy, config):
        """Test that backoff increments existing backoff."""
        policy._reasoning_backoff_remaining = 1
        config.backends.hybrid_reasoning_backoff_turns = 3

        policy.update_backoff(success=False)

        assert policy._reasoning_backoff_remaining == 4  # 1 + 3

    def test_injection_decision_fields_populated(self, policy):
        """Test that InjectionDecision has all fields populated."""
        decision = policy.should_inject(
            processed_messages=[{"role": "user", "content": "hello"}],
            request_messages=None,
            probability_override=0.7,
        )

        assert isinstance(decision, InjectionDecision)
        assert isinstance(decision.should_inject, bool)
        assert isinstance(decision.reason, str)
        assert len(decision.reason) > 0
        assert isinstance(decision.is_first_turn, bool)
        assert isinstance(decision.probability_used, float)
        assert 0.0 <= decision.probability_used <= 1.0

    def test_probability_zero_never_injects(self, policy):
        """Test that probability 0.0 never injects (except forced cases)."""
        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=0.0,
        )

        assert decision.should_inject is False
        assert decision.probability_used == 0.0

    def test_probability_one_always_injects(self, policy):
        """Test that probability 1.0 always injects (when not in backoff)."""
        decision = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=1.0,
        )

        assert decision.should_inject is True
        assert decision.probability_used == 1.0

    def test_message_role_extraction_various_formats(self, policy):
        """Test message role extraction handles various formats."""
        # Dict format
        decision1 = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
        )

        # Pydantic-like object
        class MockMessage:
            def __init__(self):
                self.role = "assistant"
                self.content = "hi"

        decision2 = policy.should_inject(
            processed_messages=[MockMessage()],
            request_messages=None,
        )

        assert decision1.is_first_turn == decision2.is_first_turn

    def test_state_persistence_across_calls(self, policy):
        """Test that backoff state persists across calls."""
        policy._reasoning_backoff_remaining = 2

        # First call decrements
        policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
        )
        assert policy._reasoning_backoff_remaining == 1

        # Second call decrements again
        policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
        )
        assert policy._reasoning_backoff_remaining == 0

        # Third call should allow injection (backoff expired)
        decision3 = policy.should_inject(
            processed_messages=[{"role": "assistant", "content": "hi"}],
            request_messages=None,
            probability_override=1.0,
        )
        assert decision3.should_inject is True
