"""Unit tests for explicit backend reactivation control-plane contract."""

from __future__ import annotations

from unittest.mock import Mock

from src.core.services.backend_reactivation_control import BackendReactivationControl
from src.core.services.provider_error_classifier import ProviderErrorClassifier
from src.core.services.resilience import RateLimitStateManager, ResilienceCoordinator


def test_reactivation_transitions_disabled_instance_to_active() -> None:
    state_manager = RateLimitStateManager()
    state_manager.disable_instance("openai.1", "auth failed")
    resilience = ResilienceCoordinator(
        state_manager,
        provider_error_classifier=ProviderErrorClassifier(),
    )

    lifecycle_manager = Mock()
    lifecycle_manager.reactivate.return_value = True

    control = BackendReactivationControl(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=resilience,
    )
    result = control.reactivate_backend_instance("openai.1")

    assert result.reactivated is True
    assert result.lifecycle_reactivated is True
    assert result.resilience_reactivated is True
    assert resilience.check_availability("openai.1", "gpt-4").should_proceed() is True


def test_reactivation_does_not_clear_unsupported_state_by_default() -> None:
    state_manager = RateLimitStateManager()
    state_manager.disable_instance("openai.1", "auth failed")
    state_manager.mark_model_unsupported(
        "openai.1",
        "gpt-4",
        reason="provider model not found",
    )
    resilience = ResilienceCoordinator(
        state_manager,
        provider_error_classifier=ProviderErrorClassifier(),
    )

    lifecycle_manager = Mock()
    lifecycle_manager.reactivate.return_value = True

    control = BackendReactivationControl(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=resilience,
    )
    result = control.reactivate_backend_instance("openai.1")

    assert result.reactivated is True
    decision = resilience.check_availability("openai.1", "gpt-4")
    assert decision.should_proceed() is False
    assert "unsupported" in decision.reason.lower()


def test_reactivation_can_explicitly_clear_unsupported_state_when_requested() -> None:
    state_manager = RateLimitStateManager()
    state_manager.disable_instance("openai.1", "auth failed")
    state_manager.mark_model_unsupported(
        "openai.1",
        "gpt-4",
        reason="provider model not found",
    )
    resilience = ResilienceCoordinator(
        state_manager,
        provider_error_classifier=ProviderErrorClassifier(),
    )

    lifecycle_manager = Mock()
    lifecycle_manager.reactivate.return_value = True

    control = BackendReactivationControl(
        backend_lifecycle_manager=lifecycle_manager,
        resilience_coordinator=resilience,
    )
    result = control.reactivate_backend_instance("openai.1", clear_unsupported=True)

    assert result.reactivated is True
    assert result.unsupported_pairs_cleared > 0
    assert resilience.check_availability("openai.1", "gpt-4").should_proceed() is True
