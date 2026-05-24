"""Unit tests for RateLimitStateManager."""

from unittest.mock import patch

from src.core.services.resilience.rate_limit_state import (
    InstanceStatus,
    RateLimitStateManager,
)


class TestInstanceLevelState:
    """Tests for instance-level state management."""

    def test_new_instance_is_active(self) -> None:
        """New instances should have ACTIVE status by default."""
        manager = RateLimitStateManager()
        assert manager.get_instance_status("backend.1") == InstanceStatus.ACTIVE
        assert manager.is_instance_available("backend.1") is True

    def test_set_instance_cooldown(self) -> None:
        """Setting cooldown should mark instance as RATE_LIMITED."""
        manager = RateLimitStateManager()
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        assert manager.get_instance_status("backend.1") == InstanceStatus.RATE_LIMITED
        assert manager.is_instance_available("backend.1") is False

    def test_cooldown_expires(self) -> None:
        """Instance should become ACTIVE after cooldown expires."""
        manager = RateLimitStateManager()

        # Set a very short cooldown
        with patch("time.time", return_value=1000.0):
            manager.set_instance_cooldown("backend.1", retry_after_seconds=10.0)

        # After cooldown expires
        with patch("time.time", return_value=1020.0):
            assert manager.get_instance_status("backend.1") == InstanceStatus.ACTIVE
            assert manager.is_instance_available("backend.1") is True

    def test_disable_instance(self) -> None:
        """Disabled instances should stay disabled."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Invalid API key")

        assert manager.get_instance_status("backend.1") == InstanceStatus.DISABLED
        assert manager.is_instance_available("backend.1") is False

    def test_disable_overrides_cooldown(self) -> None:
        """Disabled status should take precedence over cooldown."""
        manager = RateLimitStateManager()

        # First set cooldown
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)
        # Then disable
        manager.disable_instance("backend.1", "Auth failed")

        assert manager.get_instance_status("backend.1") == InstanceStatus.DISABLED

    def test_cooldown_does_not_override_disabled(self) -> None:
        """Setting cooldown on disabled instance should be ignored."""
        manager = RateLimitStateManager()

        manager.disable_instance("backend.1", "Auth failed")
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        assert manager.get_instance_status("backend.1") == InstanceStatus.DISABLED

    def test_reactivate_instance(self) -> None:
        """Reactivating should restore ACTIVE status."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Auth failed")

        result = manager.reactivate_instance("backend.1")

        assert result is True
        assert manager.get_instance_status("backend.1") == InstanceStatus.ACTIVE

    def test_reactivate_nonexistent(self) -> None:
        """Reactivating nonexistent instance should return False."""
        manager = RateLimitStateManager()
        result = manager.reactivate_instance("backend.1")
        assert result is False


class TestModelLevelState:
    """Tests for model-level state management."""

    def test_model_available_when_instance_available(self) -> None:
        """Model should be available when instance is available."""
        manager = RateLimitStateManager()
        assert manager.is_model_available("backend.1", "gpt-4") is True

    def test_model_unavailable_when_instance_limited(self) -> None:
        """Model should be unavailable when instance is rate limited."""
        manager = RateLimitStateManager()
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        assert manager.is_model_available("backend.1", "gpt-4") is False

    def test_model_unavailable_when_instance_disabled(self) -> None:
        """Model should be unavailable when instance is disabled."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Auth failed")

        assert manager.is_model_available("backend.1", "gpt-4") is False

    def test_set_model_cooldown(self) -> None:
        """Setting model cooldown should only affect that model."""
        manager = RateLimitStateManager()
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)

        assert manager.is_model_available("backend.1", "gpt-4") is False
        assert manager.is_model_available("backend.1", "gpt-3.5") is True
        assert manager.is_instance_available("backend.1") is True

    def test_model_cooldown_expires(self) -> None:
        """Model should become available after cooldown expires."""
        manager = RateLimitStateManager()

        with patch("time.time", return_value=1000.0):
            manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=10.0)

        with patch("time.time", return_value=1020.0):
            assert manager.is_model_available("backend.1", "gpt-4") is True

    def test_mark_model_unsupported_blocks_pair_permanently(self) -> None:
        """Permanent unsupported state should block only the marked pair."""
        manager = RateLimitStateManager()
        manager.mark_model_unsupported(
            "backend.1",
            "gpt-4",
            reason="Provider reported model not found",
        )

        assert manager.is_model_available("backend.1", "gpt-4") is False
        assert manager.is_model_available("backend.1", "gpt-3.5") is True

        availability = manager.check_model_availability("backend.1", "gpt-4")
        assert availability.available is False
        assert "unsupported" in availability.reason.lower()

    def test_reactivate_instance_preserves_model_unsupported_state(self) -> None:
        """Instance reactivation should not clear permanent model unsupported state."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Auth failed")
        manager.mark_model_unsupported(
            "backend.1",
            "gpt-4",
            reason="Provider reported model not found",
        )

        assert manager.reactivate_instance("backend.1") is True
        availability = manager.check_model_availability("backend.1", "gpt-4")
        assert availability.available is False
        assert "unsupported" in availability.reason.lower()


class TestCooldownManagement:
    """Tests for cooldown tracking and clearing."""

    def test_get_cooldown_remaining_instance(self) -> None:
        """Should return remaining cooldown for instance."""
        manager = RateLimitStateManager()

        with patch("time.time", return_value=1000.0):
            manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        with patch("time.time", return_value=1030.0):
            remaining = manager.get_cooldown_remaining("backend.1")
            assert remaining is not None
            assert 29.0 <= remaining <= 31.0

    def test_get_cooldown_remaining_model(self) -> None:
        """Should return remaining cooldown for model."""
        manager = RateLimitStateManager()

        with patch("time.time", return_value=1000.0):
            manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)

        with patch("time.time", return_value=1030.0):
            remaining = manager.get_cooldown_remaining("backend.1", "gpt-4")
            assert remaining is not None
            assert 29.0 <= remaining <= 31.0

    def test_get_cooldown_remaining_none(self) -> None:
        """Should return None when no cooldown active."""
        manager = RateLimitStateManager()
        assert manager.get_cooldown_remaining("backend.1") is None
        assert manager.get_cooldown_remaining("backend.1", "gpt-4") is None

    def test_clear_model_cooldown(self) -> None:
        """Clearing model cooldown should make model available."""
        manager = RateLimitStateManager()
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)

        manager.clear_cooldown("backend.1", "gpt-4")

        assert manager.is_model_available("backend.1", "gpt-4") is True

    def test_clear_instance_cooldown(self) -> None:
        """Clearing instance cooldown should make instance available."""
        manager = RateLimitStateManager()
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        manager.clear_cooldown("backend.1")

        assert manager.is_instance_available("backend.1") is True

    def test_clear_cooldown_does_not_remove_permanent_unsupported_state(self) -> None:
        """Cooldown clearing should not erase permanent unsupported outcomes."""
        manager = RateLimitStateManager()
        manager.mark_model_unsupported(
            "backend.1",
            "gpt-4",
            reason="Provider reported model not found",
        )
        manager.set_model_cooldown("backend.1", "gpt-4", retry_after_seconds=60.0)

        manager.clear_cooldown("backend.1", "gpt-4")

        availability = manager.check_model_availability("backend.1", "gpt-4")
        assert availability.available is False
        assert "unsupported" in availability.reason.lower()

    def test_clear_model_unsupported_requires_explicit_reset(self) -> None:
        """Permanent unsupported state should only clear via explicit reset."""
        manager = RateLimitStateManager()
        manager.mark_model_unsupported(
            "backend.1",
            "gpt-4",
            reason="Provider reported model not found",
        )

        assert manager.clear_model_unsupported("backend.1", "gpt-4") is True
        assert manager.is_model_available("backend.1", "gpt-4") is True


class TestAvailabilityChecks:
    """Tests for detailed availability checks."""

    def test_check_instance_availability_active(self) -> None:
        """Should return available=True for active instance."""
        manager = RateLimitStateManager()
        result = manager.check_instance_availability("backend.1")

        assert result.available is True
        assert result.reason == ""

    def test_check_instance_availability_rate_limited(self) -> None:
        """Should return available=False with reason for rate limited."""
        manager = RateLimitStateManager()
        manager.set_instance_cooldown("backend.1", retry_after_seconds=60.0)

        result = manager.check_instance_availability("backend.1")

        assert result.available is False
        assert "rate limited" in result.reason.lower()
        assert result.cooldown_remaining is not None

    def test_check_instance_availability_disabled(self) -> None:
        """Should return available=False with reason for disabled."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Invalid key")

        result = manager.check_instance_availability("backend.1")

        assert result.available is False
        assert "disabled" in result.reason.lower()

    def test_check_model_availability_returns_instance_error(self) -> None:
        """Model check should return instance error if instance unavailable."""
        manager = RateLimitStateManager()
        manager.disable_instance("backend.1", "Invalid key")

        result = manager.check_model_availability("backend.1", "gpt-4")

        assert result.available is False
        assert "disabled" in result.reason.lower()
