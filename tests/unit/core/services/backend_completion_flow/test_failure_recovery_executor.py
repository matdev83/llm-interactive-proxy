from collections.abc import AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.common.exceptions import (
    AuthenticationError,
    BackendError,
    RoutingError,
    SessionCancelledError,
)
from src.core.domain.b2bua_identity import B2buaIdentity
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.client_termination import ClientTerminationReason
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.domain.session_key import SessionKey
from src.core.interfaces.backend_work_guard_interface import IBackendWorkGuard
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.failure_strategy_interface import (
    FailureDecision,
    FailureHandlingResult,
    IFailureHandlingStrategy,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_completion_flow.failure_recovery_executor import (
    FailureRecoveryExecutor,
)
from src.core.services.composite_failure_recovery_bridge import (
    CompositeFailureRecoveryBridge,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector


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
    async def test_apply_failure_recovery_surfaces_strategy_error_to_surface(
        self, executor, failure_strategy
    ) -> None:
        decision = FailureHandlingResult(
            decision=FailureDecision.SURFACE_ERROR,
            error_to_surface=RoutingError(
                "Attempt budget exhausted",
                details={
                    "code": "temporarily_unavailable",
                    "reason": "attempt_budget_exhausted",
                },
            ),
            reason="Max failover hops exceeded",
        )
        failure_strategy.decide.return_value = decision

        request = Mock(spec=ChatRequest)

        with pytest.raises(RoutingError) as exc:
            await executor.apply_failure_recovery(
                error=BackendError("Fail", "openai"),
                model="gpt-4",
                backend_type="openai",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=False,
                content_started=False,
                request=request,
                call_completion_callback=AsyncMock(),
            )

        assert exc.value.details.get("code") == "temporarily_unavailable"
        assert exc.value.details.get("reason") == "attempt_budget_exhausted"

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

    @pytest.mark.asyncio
    async def test_retry_wait_honors_cancellation_during_wait_window(
        self, failover_planner, failure_strategy, config
    ) -> None:
        """Proxy cancellation should preempt connector wait windows."""
        cancellation_coordinator = Mock()
        call_counter = {"count": 0}

        def _ensure_not_cancelled(_session_key):
            call_counter["count"] += 1
            if call_counter["count"] >= 2:
                raise SessionCancelledError(message="Session cancelled during wait")

        cancellation_coordinator.ensure_not_cancelled.side_effect = (
            _ensure_not_cancelled
        )

        executor = FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
            cancellation_coordinator=cancellation_coordinator,
        )

        request = Mock(spec=ChatRequest)
        request.model_copy.return_value = request
        request.extra_body = {}

        callback = AsyncMock()
        callback.return_value = "Success"

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-123",
        )

        with pytest.raises(SessionCancelledError):
            await executor.execute_retry(
                request=request,
                backend_type="openai.1",
                wait_seconds=0.2,
                is_streaming=False,
                model="gpt-4",
                attempted_backends=[],
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_stream_retry_keepalive_uses_a_leg_identity_in_b2bua_mode(
        self, executor
    ) -> None:
        request = Mock(spec=ChatRequest)
        request.model_copy.side_effect = (
            lambda **kwargs: request.model_copy.return_value  # pragma: no cover
        )
        request.model_copy.return_value = Mock(spec=ChatRequest)
        request.model_copy.return_value.extra_body = {"backend_type": "openai.1"}
        request.model_copy.return_value.stream = True
        request.extra_body = {}
        request.stream = True

        async def _result_stream():
            if False:
                yield None

        callback = AsyncMock(
            return_value=StreamingResponseEnvelope(
                content=_result_stream(),
                media_type="text/event-stream",
                headers={},
            )
        )

        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-b2bua-hold-window",
            session_id="llm-b2bua-b-1001-1",
        )
        context.b2bua_identity = B2buaIdentity(
            a_session_id="llm-b2bua-a-1001",
            b_session_id="llm-b2bua-b-1001-1",
            b_seq=1,
        )

        stream_result = await executor.execute_retry(
            request=request,
            backend_type="openai.1",
            wait_seconds=0.25,
            is_streaming=True,
            model="gpt-4",
            attempted_backends=["openai.1"],
            call_completion_callback=callback,
            context=context,
        )

        assert isinstance(stream_result, StreamingResponseEnvelope)
        stream_content = cast(AsyncIterator[ProcessedResponse], stream_result.content)
        keepalive_chunk = await anext(stream_content)
        assert keepalive_chunk.metadata["session_id"] == "llm-b2bua-a-1001"
        assert keepalive_chunk.metadata["stream_id"] == "llm-b2bua-a-1001"

    @pytest.mark.asyncio
    async def test_execute_retry_aborts_when_backend_work_guard_blocks(
        self, failover_planner, failure_strategy, config
    ) -> None:
        """Backend work guard cancellation must preempt retry dispatch."""
        backend_work_guard = Mock(spec=IBackendWorkGuard)
        backend_work_guard.ensure_session_active.side_effect = SessionCancelledError(
            session_key=SessionKey(protocol="http", primary_id="req-guard-cancelled"),
            reason=ClientTerminationReason.CLIENT_DISCONNECTED,
        )

        executor = FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
            backend_work_guard=backend_work_guard,
        )

        request = Mock(spec=ChatRequest)
        request.model_copy.return_value = request
        request.extra_body = {}
        callback = AsyncMock()
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-guard-cancelled",
        )

        with pytest.raises(SessionCancelledError):
            await executor.execute_retry(
                request=request,
                backend_type="openai.1",
                wait_seconds=0.0,
                is_streaming=False,
                model="gpt-4",
                attempted_backends=[],
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_advances_composite_failover_pre_output(
        self, executor
    ) -> None:
        executor._failure_strategy = None
        request = cast(
            CanonicalChatRequest,
            ChatRequest(
                model="openai:gpt-4",
                messages=[ChatMessage(role="user", content="hello")],
                extra_body={
                    "backend_type": "openai",
                    "_resolved_uri_params": {"a": "1"},
                },
            ),
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-composite-recovery",
        )
        context.extensions["composite_routing_state"] = {
            "mode": "failover",
            "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
            "next_index": 1,
            "hop_count": 0,
            "max_hops": 2,
        }
        callback = AsyncMock(return_value="ok")

        result = await executor.apply_failure_recovery(
            error=BackendError("backend down", "openai"),
            model="gpt-4",
            backend_type="openai",
            attempted_backends=[],
            start_time=0.0,
            is_streaming=False,
            content_started=False,
            request=request,
            call_completion_callback=callback,
            context=context,
        )

        assert result == "ok"
        callback.assert_awaited_once()
        assert callback.await_args is not None
        retry_request = callback.await_args.kwargs["request"]
        assert retry_request.extra_body is not None
        assert retry_request.model == "anthropic:claude-3-5-sonnet"
        assert retry_request.extra_body["backend_type"] == "anthropic"
        assert retry_request.extra_body["_resolved_uri_params"] == {}
        assert context.extensions["retry_attempt"] == 1
        assert context.extensions["last_retry_reason"] == "composite_failover"
        state = cast(dict[str, Any], context.extensions["composite_routing_state"])
        assert state["next_index"] == 2
        assert state["hop_count"] == 1

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_does_not_advance_composite_failover_post_output(
        self, executor
    ) -> None:
        executor._failure_strategy = None
        request = ChatRequest(
            model="openai:gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            extra_body={"backend_type": "openai", "_resolved_uri_params": {}},
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-composite-recovery-post-output",
        )
        context.extensions["composite_routing_state"] = {
            "mode": "failover",
            "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
            "next_index": 1,
            "hop_count": 0,
            "max_hops": 2,
        }
        callback = AsyncMock(return_value="ok")

        with pytest.raises(BackendError):
            await executor.apply_failure_recovery(
                error=BackendError("backend down", "openai"),
                model="gpt-4",
                backend_type="openai",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=True,
                content_started=True,
                request=request,
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()
        state = cast(dict[str, Any], context.extensions["composite_routing_state"])
        assert state["next_index"] == 1
        assert state["hop_count"] == 0

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_surfaces_composite_budget_exhaustion(
        self, executor
    ) -> None:
        executor._failure_strategy = None
        request = ChatRequest(
            model="openai:gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            extra_body={"backend_type": "openai", "_resolved_uri_params": {}},
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-composite-recovery-exhausted",
        )
        context.extensions["composite_routing_state"] = {
            "mode": "failover",
            "branches": ["openai:gpt-4", "anthropic:claude-3-5-sonnet"],
            "next_index": 1,
            "hop_count": 1,
            "max_hops": 1,
        }
        callback = AsyncMock(return_value="ok")

        with pytest.raises(RoutingError) as exc_info:
            await executor.apply_failure_recovery(
                error=BackendError("backend down", "openai"),
                model="gpt-4",
                backend_type="openai",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=False,
                content_started=False,
                request=request,
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()
        assert exc_info.value.details["reason"] == "attempt_budget_exhausted"

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_rerolls_weighted_selector_pre_output(
        self, failover_planner, failure_strategy, config
    ) -> None:
        bridge = CompositeFailureRecoveryBridge(
            weighted_branch_selector=WeightedBranchSelector(
                random_value_provider=lambda: 0.0
            )
        )
        executor = FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
            composite_failure_recovery_bridge=bridge,
        )
        executor._failure_strategy = None
        request = cast(
            CanonicalChatRequest,
            ChatRequest(
                model="openai:gpt-4",
                messages=[ChatMessage(role="user", content="hello")],
                extra_body={
                    "backend_type": "openai",
                    "_resolved_uri_params": {"a": "1"},
                },
            ),
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-weighted-runtime-recovery",
        )
        context.extensions["composite_routing_state"] = {
            "mode": "weighted_retry",
            "branches": [
                {"selector": "openai:gpt-4", "weight": 1},
                {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
                {"selector": "gemini:gemini-2.0-flash", "weight": 1},
            ],
            "excluded_selectors": [],
            "selected_selector": "openai:gpt-4",
            "hop_count": 0,
            "max_hops": 3,
        }
        callback = AsyncMock(return_value="ok")

        result = await executor.apply_failure_recovery(
            error=BackendError("backend down", "openai", status_code=502),
            model="gpt-4",
            backend_type="openai",
            attempted_backends=[],
            start_time=0.0,
            is_streaming=False,
            content_started=False,
            request=request,
            call_completion_callback=callback,
            context=context,
        )

        assert result == "ok"
        callback.assert_awaited_once()
        assert callback.await_args is not None
        retry_request = callback.await_args.kwargs["request"]
        assert retry_request.model == "anthropic:claude-3-5-sonnet"
        assert retry_request.extra_body is not None
        assert retry_request.extra_body["backend_type"] == "anthropic"
        assert retry_request.extra_body["_resolved_uri_params"] == {}
        assert context.extensions["retry_attempt"] == 1
        assert context.extensions["last_retry_reason"] == "composite_failover"
        state = cast(dict[str, Any], context.extensions["composite_routing_state"])
        assert state["mode"] == "weighted_retry"
        assert state["selected_selector"] == "anthropic:claude-3-5-sonnet"
        assert state["excluded_selectors"] == ["openai:gpt-4"]
        assert state["hop_count"] == 1

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_skips_weighted_reroll_for_authentication_errors(
        self, failover_planner, failure_strategy, config
    ) -> None:
        bridge = CompositeFailureRecoveryBridge(
            weighted_branch_selector=WeightedBranchSelector(
                random_value_provider=lambda: 0.5
            )
        )
        executor = FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
            composite_failure_recovery_bridge=bridge,
        )
        executor._failure_strategy = None
        request = cast(
            CanonicalChatRequest,
            ChatRequest(
                model="openai:gpt-4",
                messages=[ChatMessage(role="user", content="hello")],
                extra_body={"backend_type": "openai"},
            ),
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-weighted-auth-no-reroll",
        )
        context.extensions["composite_routing_state"] = {
            "mode": "weighted_retry",
            "branches": [
                {"selector": "openai:gpt-4", "weight": 1},
                {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
            ],
            "excluded_selectors": [],
            "selected_selector": "openai:gpt-4",
            "hop_count": 0,
            "max_hops": 3,
        }
        callback = AsyncMock(return_value="ok")

        with pytest.raises(AuthenticationError):
            await executor.apply_failure_recovery(
                error=AuthenticationError("invalid token"),
                model="gpt-4",
                backend_type="openai",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=False,
                content_started=False,
                request=request,
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()
        state = cast(dict[str, Any], context.extensions["composite_routing_state"])
        assert state["selected_selector"] == "openai:gpt-4"
        assert state["excluded_selectors"] == []
        assert state["hop_count"] == 0

    @pytest.mark.asyncio
    async def test_apply_failure_recovery_surfaces_last_error_when_weighted_candidates_exhausted(
        self, failover_planner, failure_strategy, config
    ) -> None:
        bridge = CompositeFailureRecoveryBridge(
            weighted_branch_selector=WeightedBranchSelector(
                random_value_provider=lambda: 0.5
            )
        )
        executor = FailureRecoveryExecutor(
            failover_planner=failover_planner,
            failure_handling_strategy=failure_strategy,
            routing_service=None,
            config=config,
            failover_routes={},
            composite_failure_recovery_bridge=bridge,
        )
        executor._failure_strategy = None
        request = cast(
            CanonicalChatRequest,
            ChatRequest(
                model="anthropic:claude-3-5-sonnet",
                messages=[ChatMessage(role="user", content="hello")],
                extra_body={"backend_type": "anthropic"},
            ),
        )
        context = RequestContext(
            headers={},
            cookies={},
            state={},
            app_state=None,
            request_id="req-weighted-exhausted",
        )
        # Single weighted leaf: composite bridge cannot pick another selector (even
        # after in-budget recycle), so it returns None and the executor surfaces the
        # backend error. Two-branch states with a prior exclusion recycle instead.
        context.extensions["composite_routing_state"] = {
            "mode": "weighted_retry",
            "branches": [
                {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
            ],
            "excluded_selectors": [],
            "selected_selector": "anthropic:claude-3-5-sonnet",
            "hop_count": 0,
            "max_hops": 3,
        }
        callback = AsyncMock(return_value="ok")

        with pytest.raises(BackendError, match="secondary down"):
            await executor.apply_failure_recovery(
                error=BackendError("secondary down", "anthropic", status_code=503),
                model="claude-3-5-sonnet",
                backend_type="anthropic",
                attempted_backends=[],
                start_time=0.0,
                is_streaming=False,
                content_started=False,
                request=request,
                call_completion_callback=callback,
                context=context,
            )

        callback.assert_not_called()
        state = cast(dict[str, Any], context.extensions["composite_routing_state"])
        assert state["excluded_selectors"] == ["anthropic:claude-3-5-sonnet"]
        assert state["selected_selector"] == "anthropic:claude-3-5-sonnet"
        assert state["hop_count"] == 0
