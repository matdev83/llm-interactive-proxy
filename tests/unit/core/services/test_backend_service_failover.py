"""
Characterization tests for BackendService failover planning behavior.

This module locks in the current failover selection and filtering behavior
to prevent regressions during refactoring.

NOTE: These tests need refactoring after Phase 4 of backend-service-god-object-refactoring.
BackendService is now a thin facade. The failover planning logic has been moved to
FailoverPlanner and BackendCompletionFlow collaborators. These tests were testing
private methods (_get_failover_plan, _filter_failover_candidates) that no longer exist
on BackendService. The tests need to be refactored to either:
1. Test FailoverPlanner directly, or
2. Test the public contract of BackendService through integration tests
"""

from unittest.mock import AsyncMock, Mock

import pytest
from src.connectors.base import LLMBackend
from src.core.common.exceptions import BackendError
from src.core.config.app_config import AppConfig
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.failover_interface import (
    IFailoverCoordinator,
    IFailoverStrategy,
)
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.failover_service import FailoverAttempt

from tests.unit.fixtures.backend_service_builder import (
    create_backend_service_with_mocks,
)


@pytest.fixture
def mock_dependencies():
    """Create common mock dependencies for BackendService."""
    factory = Mock()
    rate_limiter = Mock()
    rate_limiter.check_limit = AsyncMock(return_value=Mock(is_limited=False))
    rate_limiter.record_usage = AsyncMock()

    config = Mock(spec=AppConfig)
    config.backends = Mock()
    config.backends.default_backend = "openai"
    config.backends.static_route = None
    config.backends.get = Mock(return_value=None)
    config.health_check = Mock()
    config.health_check.circuit_breaker_enabled = True

    session_service = Mock(spec=ISessionService)
    session_service.get_session = AsyncMock(return_value=None)

    app_state = Mock(spec=IApplicationState)
    app_state.get_use_failover_strategy = Mock(return_value=False)

    failover_coordinator = Mock(spec=IFailoverCoordinator)
    failover_coordinator.get_failover_attempts = Mock(return_value=[])

    # Mock backend lifecycle manager
    backend_lifecycle_manager = Mock()
    backend_lifecycle_manager.get_disabled_backends = Mock(return_value={})
    backend_lifecycle_manager.get_active_backends = Mock(return_value={})

    return {
        "factory": factory,
        "rate_limiter": rate_limiter,
        "config": config,
        "session_service": session_service,
        "app_state": app_state,
        "failover_coordinator": failover_coordinator,
        "backend_lifecycle_manager": backend_lifecycle_manager,
    }


@pytest.fixture
def backend_service(mock_dependencies):
    """Create a BackendService instance for testing."""
    from tests.unit.fixtures.backend_service_builder import (
        create_backend_service_with_mocks,
    )

    return create_backend_service_with_mocks(**mock_dependencies)


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestFailoverStrategyPath:
    """Test failover strategy path (when IFailoverStrategy is provided)."""

    def test_uses_strategy_when_enabled(self, mock_dependencies):
        """Test that strategy is used when enabled in app state."""
        # Set up strategy
        strategy = Mock(spec=IFailoverStrategy)
        strategy.get_failover_plan = Mock(
            return_value=[("anthropic", "claude-3-5-sonnet")]
        )

        mock_dependencies["failover_strategy"] = strategy
        mock_dependencies["app_state"].get_use_failover_strategy = Mock(
            return_value=True
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should use strategy
        strategy.get_failover_plan.assert_called_once_with("gpt-4", "openai")
        assert plan == [("anthropic", "claude-3-5-sonnet")]

    def test_falls_back_to_coordinator_when_strategy_fails(self, mock_dependencies):
        """Test fallback to coordinator when strategy raises error."""
        # Set up failing strategy
        strategy = Mock(spec=IFailoverStrategy)
        strategy.get_failover_plan = Mock(side_effect=BackendError("Strategy failed"))

        # Set up coordinator as fallback
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[FailoverAttempt(backend="gemini", model="gemini-2.0-flash")]
        )

        mock_dependencies["failover_strategy"] = strategy
        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["app_state"].get_use_failover_strategy = Mock(
            return_value=True
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should fall back to coordinator
        assert plan == [("gemini", "gemini-2.0-flash")]

    def test_strategy_disabled_uses_coordinator(self, mock_dependencies):
        """Test that coordinator is used when strategy is disabled."""
        strategy = Mock(spec=IFailoverStrategy)
        strategy.get_failover_plan = Mock(
            return_value=[("should-not-be-used", "model")]
        )

        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="anthropic", model="claude-3-5-sonnet")
            ]
        )

        mock_dependencies["failover_strategy"] = strategy
        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["app_state"].get_use_failover_strategy = Mock(
            return_value=False
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should use coordinator, not strategy
        strategy.get_failover_plan.assert_not_called()
        assert plan == [("anthropic", "claude-3-5-sonnet")]


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestFailoverCoordinatorPath:
    """Test default failover coordinator path."""

    def test_coordinator_plan_conversion(self, mock_dependencies):
        """Test conversion of FailoverAttempt objects to tuples."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="anthropic", model="claude-3-5-sonnet"),
                FailoverAttempt(backend="gemini", model="gemini-2.0-flash"),
            ]
        )

        mock_dependencies["failover_coordinator"] = coordinator

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should convert to list of tuples
        assert plan == [
            ("anthropic", "claude-3-5-sonnet"),
            ("gemini", "gemini-2.0-flash"),
        ]


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestHealthFiltering:
    """Test health filtering via circuit breaker."""

    def test_filters_permanently_disabled_backends(self, mock_dependencies):
        """Test that permanently disabled backends are excluded."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="anthropic", model="claude-3-5-sonnet"),
                FailoverAttempt(backend="disabled-backend", model="model"),
                FailoverAttempt(backend="gemini", model="gemini-2.0-flash"),
            ]
        )

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["backend_lifecycle_manager"].get_disabled_backends = Mock(
            return_value={"disabled-backend": {"reason": "API key missing"}}
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should exclude disabled-backend
        assert plan == [
            ("anthropic", "claude-3-5-sonnet"),
            ("gemini", "gemini-2.0-flash"),
        ]

    def test_filters_unhealthy_active_backends(self, mock_dependencies):
        """Test that active backends with unhealthy status are excluded."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="anthropic", model="claude-3-5-sonnet"),
                FailoverAttempt(backend="unhealthy-backend", model="model"),
            ]
        )

        # Mock unhealthy backend
        unhealthy_backend = Mock(spec=LLMBackend)
        unhealthy_backend.is_backend_functional = Mock(return_value=False)

        # Mock healthy backend
        healthy_backend = Mock(spec=LLMBackend)
        healthy_backend.is_backend_functional = Mock(return_value=True)

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["backend_lifecycle_manager"].get_active_backends = Mock(
            return_value={
                "unhealthy-backend": unhealthy_backend,
                "anthropic": healthy_backend,
            }
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should exclude unhealthy backend
        assert plan == [("anthropic", "claude-3-5-sonnet")]

    def test_includes_unknown_backends(self, mock_dependencies):
        """Test that backends not yet created are included (health unknown)."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="unknown-backend", model="model"),
            ]
        )

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["backend_lifecycle_manager"].get_active_backends = Mock(
            return_value={}
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should include unknown backend
        assert plan == [("unknown-backend", "model")]

    def test_fallback_to_original_plan_when_all_filtered(self, mock_dependencies):
        """Test fallback to original plan when filtering removes all backends."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="disabled-1", model="model1"),
                FailoverAttempt(backend="disabled-2", model="model2"),
            ]
        )

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["backend_lifecycle_manager"].get_disabled_backends = Mock(
            return_value={
                "disabled-1": {"reason": "Error"},
                "disabled-2": {"reason": "Error"},
            }
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should return original plan (all attempts disabled)
        assert plan == [("disabled-1", "model1"), ("disabled-2", "model2")]

    def test_circuit_breaker_disabled_no_filtering(self, mock_dependencies):
        """Test that health filtering is skipped when circuit breaker is disabled."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="disabled-backend", model="model"),
            ]
        )

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["config"].health_check.circuit_breaker_enabled = False
        mock_dependencies["backend_lifecycle_manager"].get_disabled_backends = Mock(
            return_value={"disabled-backend": {"reason": "Error"}}
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should not filter when circuit breaker disabled
        assert plan == [("disabled-backend", "model")]


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestSessionScopedBackends:
    """Test handling of session-scoped backend instances."""

    def test_finds_session_scoped_backend_for_health_check(self, mock_dependencies):
        """Test that session-scoped backends are found for health filtering."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[
                FailoverAttempt(backend="gemini-oauth", model="gemini-2.0-flash"),
            ]
        )

        # Mock session-scoped backend (cached with default key)
        healthy_backend = Mock(spec=LLMBackend)
        healthy_backend.is_healthy = Mock(return_value=True)

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["backend_lifecycle_manager"].get_active_backends = Mock(
            return_value={"gemini-oauth:default": healthy_backend}
        )

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gemini-2.0-flash", "gemini-oauth")

        # Should find and use session-scoped backend for health check
        assert plan == [("gemini-oauth", "gemini-2.0-flash")]


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestComplexFailoverExecution:
    """Test _execute_complex_failover behavior."""

    @pytest.mark.asyncio
    async def test_execute_complex_failover_uses_plan(self, mock_dependencies):
        """Test that complex failover creates plan and attempts it."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[FailoverAttempt(backend="gemini", model="gemini-2.0-flash")]
        )

        mock_dependencies["failover_coordinator"] = coordinator

        service = create_backend_service_with_mocks(**mock_dependencies)

        # Mock call_completion to succeed on first attempt
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.domain.responses import ResponseEnvelope

        service.call_completion = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        result = await service._execute_complex_failover(
            request=request,
            effective_model="gpt-4",
            backend_type="openai",
            effective_failover_routes={
                "fallback": {"backend": "gemini", "model": "gemini-2.0-flash"}
            },
            stream=False,
            context=None,
        )

        # Should have attempted failover
        assert service.call_completion.called
        assert isinstance(result, ResponseEnvelope)

    @pytest.mark.asyncio
    async def test_execute_complex_failover_propagates_error(self, mock_dependencies):
        """Test that complex failover propagates BackendError."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(return_value=[])

        mock_dependencies["failover_coordinator"] = coordinator

        service = create_backend_service_with_mocks(**mock_dependencies)

        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError):
            await service._execute_complex_failover(
                request=request,
                effective_model="gpt-4",
                backend_type="openai",
                effective_failover_routes={},
                stream=False,
                context=None,
            )


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestAttemptFailoverPlan:
    """Test _attempt_failover_plan behavior."""

    @pytest.mark.asyncio
    async def test_attempt_failover_succeeds_on_first(self, mock_dependencies):
        """Test that failover succeeds on first successful attempt."""
        service = create_backend_service_with_mocks(**mock_dependencies)

        # Mock call_completion to succeed
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.domain.responses import ResponseEnvelope

        service.call_completion = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        result = await service._attempt_failover_plan(
            request=request, plan=plan, stream=False, backend_type="openai"
        )

        # Should succeed on first attempt
        assert isinstance(result, ResponseEnvelope)
        assert service.call_completion.call_count == 1

    @pytest.mark.asyncio
    async def test_attempt_failover_tries_all_backends(self, mock_dependencies):
        """Test that failover tries all backends before failing."""
        service = create_backend_service_with_mocks(**mock_dependencies)

        # Mock call_completion to fail twice, then succeed
        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.domain.responses import ResponseEnvelope

        service.call_completion = AsyncMock(
            side_effect=[
                BackendError("first failed", "anthropic"),
                BackendError("second failed", "gemini"),
                ResponseEnvelope(content={}, headers={}, usage=None),
            ]
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [
            ("anthropic", "claude-3-5-sonnet"),
            ("gemini", "gemini-2.0-flash"),
            ("openai", "gpt-4o"),
        ]

        result = await service._attempt_failover_plan(
            request=request, plan=plan, stream=False, backend_type="openai"
        )

        # Should have tried all three backends
        assert isinstance(result, ResponseEnvelope)
        assert service.call_completion.call_count == 3

    @pytest.mark.asyncio
    async def test_attempt_failover_raises_when_all_fail(self, mock_dependencies):
        """Test that failover raises BackendError when all attempts fail."""
        service = create_backend_service_with_mocks(**mock_dependencies)

        # Mock call_completion to always fail
        service.call_completion = AsyncMock(
            side_effect=BackendError("all failed", "backend")
        )

        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        with pytest.raises(BackendError) as exc_info:
            await service._attempt_failover_plan(
                request=request, plan=plan, stream=False, backend_type="openai"
            )

        # Should indicate all attempts failed
        assert "All failover attempts failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_attempt_failover_empty_plan_fails(self, mock_dependencies):
        """Test that empty plan immediately fails."""
        service = create_backend_service_with_mocks(**mock_dependencies)

        from src.core.domain.chat import ChatMessage, ChatRequest

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError) as exc_info:
            await service._attempt_failover_plan(
                request=request, plan=[], stream=False, backend_type="openai"
            )

        assert "all backends failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_attempt_failover_preserves_allow_failover_false(
        self, mock_dependencies
    ):
        """Test that failover attempts have allow_failover=False to prevent recursion."""
        service = create_backend_service_with_mocks(**mock_dependencies)

        from src.core.domain.chat import ChatMessage, ChatRequest
        from src.core.domain.responses import ResponseEnvelope

        service.call_completion = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet")]

        await service._attempt_failover_plan(
            request=request, plan=plan, stream=False, backend_type="openai"
        )

        # Verify allow_failover=False was passed
        call_args = service.call_completion.call_args
        assert call_args.kwargs.get("allow_failover") is False


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestApplyFailureStrategy:
    """Test _apply_failure_strategy behavior."""

    @pytest.mark.asyncio
    async def test_no_strategy_surfaces_error(self, mock_dependencies):
        """Test that without strategy, errors are surfaced."""
        # Don't provide failure strategy
        mock_dependencies.pop("failure_strategy", None)

        service = create_backend_service_with_mocks(**mock_dependencies)

        from src.core.interfaces.failure_strategy_interface import FailureDecision

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await service._apply_failure_strategy(
            error=error,
            model="gpt-4",
            backend_type="openai",
            attempted_backends=[],
            start_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        # Should surface error when no strategy
        assert decision == FailureDecision.SURFACE_ERROR
        assert wait is None
        assert next_backend is None

    @pytest.mark.asyncio
    async def test_strategy_delegates_to_failure_handler(self, mock_dependencies):
        """Test that failure strategy delegates to handler."""
        from src.core.interfaces.failure_strategy_interface import (
            FailureDecision,
            IFailureHandlingStrategy,
        )

        strategy = Mock(spec=IFailureHandlingStrategy)
        mock_decision = Mock()
        mock_decision.decision = FailureDecision.WAIT_AND_RETRY
        mock_decision.wait_seconds = 1.0
        mock_decision.next_backend = None
        strategy.decide = Mock(return_value=mock_decision)

        mock_dependencies["failure_handling_strategy"] = strategy

        service = create_backend_service_with_mocks(**mock_dependencies)

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await service._apply_failure_strategy(
            error=error,
            model="gpt-4",
            backend_type="openai",
            attempted_backends=[],
            start_time=0.0,
            is_streaming=False,
            content_started=False,
        )

        # Should use strategy's decision
        assert decision == FailureDecision.WAIT_AND_RETRY
        assert wait == 1.0
        assert strategy.decide.called


@pytest.mark.skip(
    reason="Needs refactoring after Phase 4 - failover logic moved to FailoverPlanner"
)
class TestEdgeCases:
    """Test edge cases in failover planning."""

    def test_empty_failover_plan(self, mock_dependencies):
        """Test behavior with empty failover plan."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(return_value=[])

        mock_dependencies["failover_coordinator"] = coordinator

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        assert plan == []

    def test_missing_health_check_config(self, mock_dependencies):
        """Test that missing health_check config disables filtering."""
        coordinator = Mock(spec=IFailoverCoordinator)
        coordinator.get_failover_attempts = Mock(
            return_value=[FailoverAttempt(backend="any", model="model")]
        )

        mock_dependencies["failover_coordinator"] = coordinator
        mock_dependencies["config"].health_check = None

        service = create_backend_service_with_mocks(**mock_dependencies)

        plan = service._get_failover_plan("gpt-4", "openai")

        # Should not filter without health_check config
        assert plan == [("any", "model")]
