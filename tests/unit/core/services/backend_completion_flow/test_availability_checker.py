from unittest.mock import Mock

import pytest
from src.core.common.exceptions import BackendError, RateLimitExceededError
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.resilience_interface import (
    ActionType,
    IResilienceCoordinator,
    ResilienceDecision,
)
from src.core.services.backend_completion_flow.availability_checker import (
    BackendAvailabilityChecker,
)


class TestBackendAvailabilityChecker:
    @pytest.fixture
    def lifecycle_manager(self):
        return Mock(spec=IBackendLifecycleManager)

    @pytest.fixture
    def resilience_coordinator(self):
        return Mock(spec=IResilienceCoordinator)

    @pytest.fixture
    def checker(self, lifecycle_manager, resilience_coordinator):
        return BackendAvailabilityChecker(
            backend_lifecycle_manager=lifecycle_manager,
            resilience_coordinator=resilience_coordinator,
            failover_routes={},
        )

    @pytest.mark.asyncio
    async def test_raises_if_backend_permanently_disabled(
        self, checker, lifecycle_manager
    ):
        lifecycle_manager.get_disabled_backends.return_value = {
            "openai": {"reason": "auth failed"}
        }

        with pytest.raises(BackendError) as exc:
            await checker.check_backend_availability(
                backend_type="openai", effective_model="gpt-4", allow_failover=True
            )

        assert "permanently disabled" in str(exc.value)

    @pytest.mark.asyncio
    async def test_allows_disabled_backend_if_failover_route_exists(
        self, lifecycle_manager, resilience_coordinator
    ):
        lifecycle_manager.get_disabled_backends.return_value = {
            "openai": {"reason": "auth failed"}
        }

        # Checker with failover routes
        checker = BackendAvailabilityChecker(
            backend_lifecycle_manager=lifecycle_manager,
            resilience_coordinator=resilience_coordinator,
            failover_routes={"openai": {"target": "gemini"}},
        )

        # Should not raise
        await checker.check_backend_availability(
            backend_type="openai", effective_model="gpt-4", allow_failover=True
        )

    @pytest.mark.asyncio
    async def test_raises_if_resilience_denies(
        self, checker, lifecycle_manager, resilience_coordinator
    ):
        lifecycle_manager.get_disabled_backends.return_value = {}

        decision = ResilienceDecision(
            action=ActionType.REJECT,
            reason="Circuit breaker open",
            cooldown_remaining=10.0,
        )
        resilience_coordinator.check_availability.return_value = decision

        with pytest.raises(RateLimitExceededError) as exc:
            await checker.check_backend_availability(
                backend_type="openai", effective_model="gpt-4", allow_failover=True
            )

        assert "Circuit breaker open" in str(exc.value)
        assert exc.value.reset_at is not None

    @pytest.mark.asyncio
    async def test_happy_path(self, checker, lifecycle_manager, resilience_coordinator):
        lifecycle_manager.get_disabled_backends.return_value = {}

        decision = ResilienceDecision(
            action=ActionType.PROCEED, reason="", cooldown_remaining=0.0
        )
        resilience_coordinator.check_availability.return_value = decision

        # Should not raise
        await checker.check_backend_availability(
            backend_type="openai", effective_model="gpt-4", allow_failover=True
        )
