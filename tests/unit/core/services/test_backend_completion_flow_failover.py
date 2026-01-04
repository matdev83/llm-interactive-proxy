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
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.failure_strategy_interface import IFailureHandlingStrategy
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.backend_routing_service import BackendRoutingService


@pytest.fixture
def mock_dependencies():
    """Create common mock dependencies for FailureRecoveryExecutor."""
    deps = {
        "failover_planner": Mock(spec=IFailoverPlanner),
        "failure_handling_strategy": Mock(spec=IFailureHandlingStrategy),
        "routing_service": Mock(spec=BackendRoutingService),
        "config": Mock(spec=IConfig),
        "failover_routes": {},
    }
    return deps


@pytest.fixture
def failover_executor(mock_dependencies):
    """Create a FailureRecoveryExecutor instance for testing."""
    return FailureRecoveryExecutor(**mock_dependencies)


class TestComplexFailoverExecution:
    """Test execute_complex_failover behavior."""

    @pytest.mark.asyncio
    async def test_execute_complex_failover_uses_plan(
        self, failover_executor, mock_dependencies
    ):
        """Test that complex failover creates plan and attempts it."""
        # get_failover_plan returns tuples, not FailoverAttempt objects
        mock_dependencies["failover_planner"].get_failover_plan = Mock(
            return_value=[("gemini", "gemini-2.0-flash")]
        )

        mock_callback = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        result = await failover_executor.execute_complex_failover(
            request=request,
            effective_model="gpt-4",
            backend_type="openai",
            stream=False,
            call_completion_callback=mock_callback,
            context=None,
        )

        # Should have attempted failover via attempt_failover_plan -> call_completion
        assert mock_callback.called
        assert isinstance(result, ResponseEnvelope)

        # Verify planner usage
        mock_dependencies["failover_planner"].get_failover_plan.assert_called_with(
            "gpt-4", "openai"
        )

    @pytest.mark.asyncio
    async def test_execute_complex_failover_propagates_error(
        self, failover_executor, mock_dependencies
    ):
        """Test that complex failover propagates BackendError."""
        mock_dependencies["failover_planner"].get_failover_plan = Mock(return_value=[])

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError):
            await failover_executor.execute_complex_failover(
                request=request,
                effective_model="gpt-4",
                backend_type="openai",
                stream=False,
                call_completion_callback=AsyncMock(),
                context=None,
            )


class TestAttemptFailoverPlan:
    """Test attempt_failover_plan behavior."""

    @pytest.mark.asyncio
    async def test_attempt_failover_succeeds_on_first(self, failover_executor):
        """Test that failover succeeds on first successful attempt."""
        mock_callback = AsyncMock(
            return_value=ResponseEnvelope(content={}, headers={}, usage=None)
        )

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        result = await failover_executor.attempt_failover_plan(
            request=request,
            plan=plan,
            stream=False,
            backend_type="openai",
            call_completion_callback=mock_callback,
        )

        # Should succeed on first attempt
        assert isinstance(result, ResponseEnvelope)
        assert mock_callback.call_count == 1

        # Verify call args
        call_args = mock_callback.call_args
        assert call_args.kwargs["allow_failover"] is False

        request_arg = call_args.kwargs.get("request")
        if request_arg is None and call_args.args:
            request_arg = call_args.args[0]

        assert request_arg.extra_body["backend_type"] == "anthropic"

    @pytest.mark.asyncio
    async def test_attempt_failover_tries_all_backends(self, failover_executor):
        """Test that failover tries all backends before failing."""
        mock_callback = AsyncMock(
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

        result = await failover_executor.attempt_failover_plan(
            request=request,
            plan=plan,
            stream=False,
            backend_type="openai",
            call_completion_callback=mock_callback,
        )

        # Should have tried all three backends
        assert isinstance(result, ResponseEnvelope)
        assert mock_callback.call_count == 3

    @pytest.mark.asyncio
    async def test_attempt_failover_raises_when_all_fail(self, failover_executor):
        """Test that failover raises BackendError when all attempts fail."""
        mock_callback = AsyncMock(side_effect=BackendError("all failed", "backend"))

        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )
        plan = [("anthropic", "claude-3-5-sonnet"), ("gemini", "gemini-2.0-flash")]

        with pytest.raises(BackendError) as exc_info:
            await failover_executor.attempt_failover_plan(
                request=request,
                plan=plan,
                stream=False,
                backend_type="openai",
                call_completion_callback=mock_callback,
            )

        # Should indicate all attempts failed
        assert "All failover attempts failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_attempt_failover_empty_plan_fails(self, failover_executor):
        """Test that empty plan immediately fails."""
        request = ChatRequest(
            model="gpt-4", messages=[ChatMessage(role="user", content="test")]
        )

        with pytest.raises(BackendError) as exc_info:
            await failover_executor.attempt_failover_plan(
                request=request,
                plan=[],
                stream=False,
                backend_type="openai",
                call_completion_callback=AsyncMock(),
            )

        assert "all backends failed" in str(exc_info.value)


class TestApplyFailureStrategy:
    """Test apply_failure_strategy behavior."""

    @pytest.mark.asyncio
    async def test_no_strategy_surfaces_error(self, mock_dependencies):
        """Test that without strategy, errors are surfaced."""
        # Ensure no failure strategy
        mock_dependencies["failure_handling_strategy"] = None
        failover_executor = FailureRecoveryExecutor(**mock_dependencies)

        from src.core.interfaces.failure_strategy_interface import FailureDecision

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await failover_executor.apply_failure_strategy(
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
        failover_executor = FailureRecoveryExecutor(**mock_dependencies)

        error = BackendError("test error", "openai")

        decision, wait, next_backend = await failover_executor.apply_failure_strategy(
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
