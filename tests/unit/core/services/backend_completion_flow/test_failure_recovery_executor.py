from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import BackendError
from src.core.domain.chat import ChatRequest
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingResult,
    IFailureHandlingStrategy,
)
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)


class TestFailureRecoveryExecutor:
    @pytest.fixture
    def failover_planner(self):
        return Mock(spec=IFailoverPlanner)

    @pytest.fixture
    def failure_strategy(self):
        return Mock(spec=IFailureHandlingStrategy)

    @pytest.fixture
    def config(self):
        return Mock(spec=IConfig)

    @pytest.fixture
    def executor(self, failover_planner, failure_strategy, config):
        return FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
        )

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_surfaces_error_if_no_strategy(self, executor):
        executor._failure_strategy = None

        request = Mock(spec=ChatRequest)
        error = BackendError("Boom", "openai")

        with pytest.raises(BackendError) as exc:
            await executor.apply_failure_recovery(
                error=error,
                model="gpt-4",
                backend_type="openai",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=False,
                content_started=False,
                request=request,
                call_completion_callback=AsyncMock(),
            )

        assert str(exc.value) == "Boom"

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_executes_retry(
        self, executor, failure_strategy
    ):
        # Arrange
        decision = FailureHandlingResult(
            decision=FailureDecision.WAIT_AND_RETRY, wait_seconds=0.1, next_backend=None
        )
        failure_strategy.decide.return_value = decision

        request = Mock(spec=ChatRequest)
        request.model_copy.return_value = request
        request.extra_body = {}

        callback = AsyncMock()
        callback.return_value = "Success"

        # Act
        result = await executor.apply_failure_recovery(
            error=BackendError("Fail", "openai"),
            model="gpt-4",
            backend_type="openai",
            attempted_backends=[],
            start_time=0.0,
            is_streaming=False,
            content_started=False,
            request=request,
            call_completion_callback=callback,
        )

        # Assert
        assert result == "Success"
        callback.assert_called_once()
