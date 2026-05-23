"""Unit tests for ResilienceCoordinator."""

from src.core.common.exceptions import (
    AuthenticationError,
    InvalidRequestError,
    RateLimitExceededError,
)
from src.core.interfaces.resilience_interface import ActionType
from src.core.services.provider_error_classifier import ProviderErrorClassifier
from src.core.services.resilience import RateLimitStateManager, ResilienceCoordinator
from src.core.services.resilience.handlers import (
    AuthErrorHandler,
    RateLimitErrorHandler,
)


def _coordinator(
    manager: RateLimitStateManager,
    *,
    error_handler_chain=None,
) -> ResilienceCoordinator:
    return ResilienceCoordinator(
        manager,
        error_handler_chain=error_handler_chain,
        provider_error_classifier=ProviderErrorClassifier(),
    )


class TestCheckAvailability:
    """Tests for check_availability method."""

    def test_proceeds_when_all_available(self) -> None:
        """Should return PROCEED when instance and model are available."""
        manager = RateLimitStateManager()
        coordinator = _coordinator(manager)

        decision = coordinator.check_availability("backend.1", "gpt-4")

        assert decision.should_proceed() is True
        assert decision.action == ActionType.PROCEED

    def test_rejects_when_instance_disabled(self) -> None:
        """Should return REJECT when instance is disabled."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Auth failed")
        coordinator = _coordinator(manager)

        decision = coordinator.check_availability("backend.1", "gpt-4")

        assert decision.should_proceed() is False
        assert decision.action == ActionType.REJECT
        assert "disabled" in decision.reason.lower()

    def test_rejects_when_instance_rate_limited(self) -> None:
        """Should return REJECT when instance is rate limited."""
        manager = RateLimitStateManager()
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)
        coordinator = _coordinator(manager)

        decision = coordinator.check_availability("backend.1", "gpt-4")

        assert decision.should_proceed() is False
        assert decision.action == ActionType.REJECT
        assert decision.cooldown_remaining is not None
        assert decision.cooldown_remaining > 0

    def test_rejects_when_model_rate_limited(self) -> None:
        """Should return REJECT when model is rate limited."""
        manager = RateLimitStateManager()
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)
        coordinator = _coordinator(manager)

        decision = coordinator.check_availability("backend.1", "gpt-4")

        assert decision.should_proceed() is False
        assert decision.action == ActionType.REJECT

    def test_proceeds_for_other_model_when_one_limited(self) -> None:
        """Should proceed for model not in cooldown."""
        manager = RateLimitStateManager()
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)
        coordinator = _coordinator(manager)

        decision = coordinator.check_availability("backend.1", "gpt-3.5")

        assert decision.should_proceed() is True


class TestRecordSuccess:
    """Tests for record_success method."""

    def test_clears_model_cooldown_on_success(self) -> None:
        """Should clear model cooldown after success."""
        manager = RateLimitStateManager()
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)
        coordinator = _coordinator(manager)

        coordinator.record_success("backend.1", "gpt-4")

        assert manager.is_model_available("backend.1", "gpt-4") is True

    def test_success_does_not_clear_permanent_unsupported_state(self) -> None:
        """Successful calls should not clear permanent unsupported outcomes."""
        manager = RateLimitStateManager()
        manager.mark_model_unsupported(
            "backend.1",
            "gpt-4",
            reason="Provider model not found",
        )
        coordinator = _coordinator(manager)

        coordinator.record_success("backend.1", "gpt-4")

        decision = coordinator.check_availability("backend.1", "gpt-4")
        assert decision.should_proceed() is False
        assert "unsupported" in decision.reason.lower()


class TestRecordFailure:
    """Tests for record_failure method."""

    def test_handles_rate_limit_error(self) -> None:
        """Should handle rate limit error via handler chain."""
        manager = RateLimitStateManager()
        rate_handler = RateLimitErrorHandler(manager)
        coordinator = _coordinator(manager, error_handler_chain=rate_handler)

        error = RateLimitExceededError(
            "Rate limited", details={"retry_after_seconds": 120}
        )
        action = coordinator.record_failure("backend.1", "gpt-4", error)

        assert action.type == ActionType.COOLDOWN
        assert action.duration == 120.0

    def test_handles_auth_error(self) -> None:
        """Should handle auth error via handler chain."""
        manager = RateLimitStateManager()
        auth_handler = AuthErrorHandler(manager)
        rate_handler = RateLimitErrorHandler(manager, next_handler=auth_handler)
        coordinator = _coordinator(manager, error_handler_chain=rate_handler)

        error = AuthenticationError("Invalid API key")
        action = coordinator.record_failure("backend.1", "gpt-4", error)

        assert action.type == ActionType.DISABLE_INSTANCE
        assert manager.is_instance_available("backend.1") is False

    def test_respects_error_context_metadata(self) -> None:
        """Should pass attached error context into handlers."""
        manager = RateLimitStateManager()
        auth_handler = AuthErrorHandler(manager)
        coordinator = _coordinator(manager, error_handler_chain=auth_handler)

        error = AuthenticationError("Invalid API key")
        error.__resilience_context__ = {  # type: ignore[attr-defined]
            "is_personal_backend": True
        }

        action = coordinator.record_failure("backend.1", "gpt-4", error)

        assert action.type == ActionType.PROCEED
        assert manager.is_instance_available("backend.1") is True

    def test_returns_proceed_for_unhandled_error(self) -> None:
        """Should return PROCEED for unhandled error types."""
        manager = RateLimitStateManager()
        coordinator = _coordinator(manager)  # No handler chain

        error = ValueError("Some error")
        action = coordinator.record_failure("backend.1", "gpt-4", error)

        assert action.type == ActionType.PROCEED

    def test_marks_permanent_unsupported_pair_from_model_not_found_error(self) -> None:
        """Permanent model-not-found should mark (instance, model) as unsupported."""
        manager = RateLimitStateManager()
        coordinator = _coordinator(manager)

        error = InvalidRequestError(
            "Model gpt-4 does not exist on this backend",
            details={"code": "model_not_found"},
            status_code=404,
        )
        action = coordinator.record_failure("backend.1", "gpt-4", error)

        assert action.type == ActionType.PROCEED
        decision = coordinator.check_availability("backend.1", "gpt-4")
        assert decision.should_proceed() is False
        assert "unsupported" in decision.reason.lower()


class TestFullWorkflow:
    """Integration tests for full resilience workflow."""

    def test_rate_limit_then_recovery(self) -> None:
        """Should block requests during cooldown, allow after recovery."""
        manager = RateLimitStateManager()
        rate_handler = RateLimitErrorHandler(manager)
        coordinator = _coordinator(manager, error_handler_chain=rate_handler)

        # Initially available
        assert coordinator.check_availability("backend.1", "gpt-4").should_proceed()

        # Record rate limit failure
        error = RateLimitExceededError(
            "Rate limited", details={"retry_after_seconds": 60}
        )
        coordinator.record_failure("backend.1", "gpt-4", error)

        # Now should reject
        assert not coordinator.check_availability("backend.1", "gpt-4").should_proceed()

        # Record success (simulating recovery)
        coordinator.record_success("backend.1", "gpt-4")

        # Should be available again
        assert coordinator.check_availability("backend.1", "gpt-4").should_proceed()

    def test_auth_failure_permanently_disables(self) -> None:
        """Auth failure should permanently disable instance."""
        manager = RateLimitStateManager()
        auth_handler = AuthErrorHandler(manager)
        rate_handler = RateLimitErrorHandler(manager, next_handler=auth_handler)
        coordinator = _coordinator(manager, error_handler_chain=rate_handler)

        # Initially available
        assert coordinator.check_availability("backend.1", "gpt-4").should_proceed()

        # Record auth failure
        error = AuthenticationError("Invalid API key")
        coordinator.record_failure("backend.1", "gpt-4", error)

        # Should reject all models on this instance
        assert not coordinator.check_availability("backend.1", "gpt-4").should_proceed()
        assert not coordinator.check_availability(
            "backend.1", "gpt-3.5"
        ).should_proceed()

        # Success should NOT re-enable (need manual reactivation)
        coordinator.record_success("backend.1", "gpt-4")
        assert not coordinator.check_availability("backend.1", "gpt-4").should_proceed()

    def test_instance_limit_affects_all_models(self) -> None:
        """Instance-level limit should affect all models."""
        manager = RateLimitStateManager()
        rate_handler = RateLimitErrorHandler(manager)
        coordinator = _coordinator(manager, error_handler_chain=rate_handler)

        # Record organization-level rate limit
        error = RateLimitExceededError(
            "Organization rate limit exceeded",
            details={"retry_after_seconds": 600},
        )
        coordinator.record_failure("backend.1", "gpt-4", error)

        # All models should be blocked
        assert not coordinator.check_availability("backend.1", "gpt-4").should_proceed()
        assert not coordinator.check_availability(
            "backend.1", "gpt-3.5"
        ).should_proceed()

        # Other instances should be fine
        assert coordinator.check_availability("backend.2", "gpt-4").should_proceed()
