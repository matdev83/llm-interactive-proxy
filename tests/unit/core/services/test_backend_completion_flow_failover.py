"""
Tests for BackendCompletionFlow failover behavior.

This module tests the failover execution logic in BackendCompletionFlow.
failover planning logic is tested in test_failover_planner.py.
"""

from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.backend_factory_interface import IBackendFactory
from src.core.interfaces.backend_lifecycle_manager_interface import (
    IBackendLifecycleManager,
)
from src.core.interfaces.backend_model_resolver_interface import (
    IBackendModelResolver,
    ResolvedTarget,
)
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.exception_normalizer_interface import IExceptionNormalizer
from src.core.interfaces.failover_interface import IFailoverCoordinator
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.planning_phase_manager_interface import IPlanningPhaseManager
from src.core.interfaces.reasoning_config_applicator_interface import (
    IReasoningConfigApplicator,
)
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.stream_formatting_interface import IStreamFormattingService
from src.core.interfaces.stream_session_id_resolver_interface import (
    IStreamSessionIdResolver,
)
from src.core.interfaces.uri_parameter_applicator_interface import (
    IURIParameterApplicator,
)
from src.core.interfaces.usage_tracking_wrapper_interface import IUsageTrackingWrapper
from src.core.services.backend_completion_flow import BackendCompletionFlow


@pytest.fixture
def mock_dependencies():
    """Create common mock dependencies for BackendCompletionFlow."""
    deps = {
        "backend_model_resolver": Mock(spec=IBackendModelResolver),
        "stream_session_id_resolver": Mock(spec=IStreamSessionIdResolver),
        "failover_planner": Mock(spec=IFailoverPlanner),
        "session_service": Mock(spec=ISessionService),
        "backend_lifecycle_manager": Mock(spec=IBackendLifecycleManager),
        "backend_config_service": Mock(spec=IBackendConfigProvider),
        "reasoning_config_applicator": Mock(spec=IReasoningConfigApplicator),
        "uri_parameter_applicator": Mock(spec=IURIParameterApplicator),
        "stream_formatting_service": Mock(spec=IStreamFormattingService),
        "usage_tracking_wrapper": Mock(spec=IUsageTrackingWrapper),
        "exception_normalizer": Mock(spec=IExceptionNormalizer),
        "planning_phase_manager": Mock(spec=IPlanningPhaseManager),
        "backend_factory": Mock(spec=IBackendFactory),
        "config": Mock(spec=IConfig),
        "app_state": Mock(spec=IApplicationState),
        "failover_coordinator": Mock(spec=IFailoverCoordinator),
    }

    # Defaults
    deps["backend_model_resolver"].resolve_target = AsyncMock(
        return_value=ResolvedTarget(backend="openai", model="gpt-4", uri_params={})
    )
    deps["backend_model_resolver"].synchronize_request_with_target = Mock(
        side_effect=lambda r, t: r
    )
    deps["config"].backends = Mock()
    deps["config"].backends.get = Mock(return_value=None)

    return deps


@pytest.fixture
def completion_flow(mock_dependencies):
    """Create a BackendCompletionFlow instance for testing."""
    return BackendCompletionFlow(**mock_dependencies)


class TestComplexFailoverExecution:
    """Test _execute_complex_failover behavior."""

    @pytest.mark.asyncio
    async def test_execute_complex_failover_uses_plan(
        self, completion_flow, mock_dependencies
    ):
        """Test that complex failover creates plan and attempts it."""
        mock_dependencies["failover_planner"].get_failover_plan = Mock(
            return_value=[("gemini", "gemini-2.0-flash")]
        )

        # Mock call_completion to succeed on first attempt
        # We need to mock call_completion on the instance itself to intercept the recursive call
        completion_flow.call_completion = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        result = await completion_flow._execute_complex_failover(
            request=request,
            effective_model="gpt-4",
            backend_type="openai",
            stream=False,
            context=None,
        )

        # Should have attempted failover via _attempt_failover_plan -> call_completion
        assert completion_flow.call_completion.called
        assert isinstance(result, ResponseEnvelope)

        # Verify planner usage
        mock_dependencies["failover_planner"].get_failover_plan.assert_called_with(
            "gpt-4", "openai"
        )

    @pytest.mark.asyncio
    async def test_execute_complex_failover_propagates_error(
        self, completion_flow, mock_dependencies
    ):
        """Test that complex failover propagates BackendError."""
        mock_dependencies["failover_planner"].get_failover_plan = Mock(return_value=[])

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError):
            await completion_flow._execute_complex_failover(
                request=request,
                effective_model="gpt-4",
                backend_type="openai",
                stream=False,
                context=None,
            )


class TestAttemptFailoverPlan:
    """Test _attempt_failover_plan behavior."""

    @pytest.mark.asyncio
    async def test_attempt_failover_succeeds_on_first(self, completion_flow):
        """Test that failover succeeds on first successful attempt."""
        # Mock call_completion to succeed
        completion_flow.call_completion = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        result = await completion_flow._attempt_failover_plan(
            request=request, plan=plan, stream=False, backend_type="openai"
        )

        # Should succeed on first attempt
        assert isinstance(result, ResponseEnvelope)
        assert completion_flow.call_completion.call_count == 1

        # Verify call args
        call_args = completion_flow.call_completion.call_args
        assert call_args.kwargs["allow_failover"] is False

        request_arg = call_args.kwargs.get("request")
        if request_arg is None and call_args.args:
            request_arg = call_args.args[0]

        assert request_arg.extra_body["backend_type"] == "anthropic"

    @pytest.mark.asyncio
    async def test_attempt_failover_tries_all_backends(self, completion_flow):
        """Test that failover tries all backends before failing."""
        # Mock call_completion to fail twice, then succeed
        completion_flow.call_completion = AsyncMock(
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

        result = await completion_flow._attempt_failover_plan(
            request=request, plan=plan, stream=False, backend_type="openai"
        )

        # Should have tried all three backends
        assert isinstance(result, ResponseEnvelope)
        assert completion_flow.call_completion.call_count == 3

    @pytest.mark.asyncio
    async def test_attempt_failover_raises_when_all_fail(self, completion_flow):
        """Test that failover raises BackendError when all attempts fail."""
        # Mock call_completion to always fail
        completion_flow.call_completion = AsyncMock(
            side_effect=BackendError("all failed", "backend")
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        with pytest.raises(BackendError) as exc_info:
            await completion_flow._attempt_failover_plan(
                request=request, plan=plan, stream=False, backend_type="openai"
            )

        # Should indicate all attempts failed
        assert "All failover attempts failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_attempt_failover_empty_plan_fails(self, completion_flow):
        """Test that empty plan immediately fails."""
        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError) as exc_info:
            await completion_flow._attempt_failover_plan(
                request=request, plan=[], stream=False, backend_type="openai"
            )

        assert "all backends failed" in str(exc_info.value)


class TestApplyFailureStrategy:
    """Test _apply_failure_strategy behavior."""

    @pytest.mark.asyncio
    async def test_no_strategy_surfaces_error(self, completion_flow, mock_dependencies):
        """Test that without strategy, errors are surfaced."""
        # Ensure no failure strategy
        mock_dependencies["failure_handling_strategy"] = None
        # We need to recreate the flow because we modified the dict but constructor was already called
        completion_flow = BackendCompletionFlow(**mock_dependencies)

        from src.core.interfaces.failure_strategy_interface import FailureDecision

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await completion_flow._apply_failure_strategy(
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
        completion_flow = BackendCompletionFlow(**mock_dependencies)

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await completion_flow._apply_failure_strategy(
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
