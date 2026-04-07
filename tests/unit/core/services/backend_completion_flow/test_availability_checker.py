from unittest.mock import Mock

import pytest
from src.core.common.exceptions import (
    BackendError,
    RoutingError,
    ServiceUnavailableError,
)
from src.core.domain.request_context import RequestContext
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
from src.core.services.backend_lifecycle_types import DisabledBackendInfo


class TestBackendAvailabilityChecker:
    @pytest.fixture
    def lifecycle_manager(self):
        return Mock(spec=IBackendLifecycleManager)

    @pytest.fixture
    def resilience_coordinator(self):
        mock = Mock(spec=IResilienceCoordinator)
        mock.try_acquire_circuit_breaker_probe.return_value = True
        return mock

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
            "openai": DisabledBackendInfo(reason="auth failed", timestamp=0)
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
            "openai": DisabledBackendInfo(reason="auth failed", timestamp=0)
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

        with pytest.raises(ServiceUnavailableError) as exc:
            await checker.check_backend_availability(
                backend_type="openai", effective_model="gpt-4", allow_failover=True
            )

        assert "Circuit breaker open" in str(exc.value)
        assert exc.value.details.get("retry_after_seconds", 0) > 0

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
        resilience_coordinator.try_acquire_circuit_breaker_probe.assert_called_once_with(
            "openai"
        )

    @pytest.mark.asyncio
    async def test_raises_routing_error_for_permanent_unsupported_pair(
        self, checker, lifecycle_manager, resilience_coordinator
    ):
        lifecycle_manager.get_disabled_backends.return_value = {}
        resilience_coordinator.check_availability.return_value = ResilienceDecision(
            action=ActionType.REJECT,
            reason="Model permanently unsupported on openai.1",
            cooldown_remaining=None,
        )

        with pytest.raises(RoutingError) as exc:
            await checker.check_backend_availability(
                backend_type="openai.1",
                effective_model="gpt-4",
                allow_failover=True,
            )

        assert exc.value.details is not None
        assert exc.value.details.get("code") == "unsupported_on_instance"

    @pytest.mark.asyncio
    async def test_scopes_personal_backend_with_session_id(
        self, checker, lifecycle_manager, resilience_coordinator
    ):
        lifecycle_manager.get_disabled_backends.return_value = {}

        decision = ResilienceDecision(
            action=ActionType.PROCEED, reason="", cooldown_remaining=0.0
        )
        resilience_coordinator.check_availability.return_value = decision

        context = RequestContext(
            headers={},
            cookies={},
            state=None,
            app_state=None,
            session_id="session-123",
        )

        await checker.check_backend_availability(
            backend_type="qwen-oauth",
            effective_model="qwen3-coder-plus",
            allow_failover=True,
            context=context,
        )

        resilience_coordinator.check_availability.assert_called_once_with(
            "qwen-oauth:session-123",
            "qwen3-coder-plus",
        )
        resilience_coordinator.try_acquire_circuit_breaker_probe.assert_called_once_with(
            "qwen-oauth:session-123"
        )

    @pytest.mark.asyncio
    async def test_raises_routing_error_when_half_open_probe_capacity_exhausted(
        self, checker, lifecycle_manager, resilience_coordinator
    ):
        lifecycle_manager.get_disabled_backends.return_value = {}
        resilience_coordinator.check_availability.return_value = ResilienceDecision(
            action=ActionType.PROCEED, reason="", cooldown_remaining=0.0
        )
        resilience_coordinator.try_acquire_circuit_breaker_probe.return_value = False

        with pytest.raises(RoutingError) as exc:
            await checker.check_backend_availability(
                backend_type="openai.1",
                effective_model="gpt-4",
                allow_failover=True,
            )

        assert exc.value.details is not None
        assert exc.value.details.get("reason") == "half_open_probe_inflight"
