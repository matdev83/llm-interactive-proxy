from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.composite_routing import (
    CompositeLeafNode,
    CompositeLeafSelector,
    CompositeParallelGroupNode,
    CompositeRoutePlan,
)
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session, SessionState
from src.core.services.backend_completion_flow.service import BackendCompletionFlow


def _parallel_plan() -> CompositeRoutePlan:
    return CompositeRoutePlan(
        source_selector="openai:gpt-4!anthropic:claude-3",
        normalized_selector="openai:gpt-4!anthropic:claude-3",
        root_node=CompositeParallelGroupNode(
            children=[
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="openai:gpt-4",
                        normalized_selector="openai:gpt-4",
                        uri_params={},
                    )
                ),
                CompositeLeafNode(
                    leaf_selector=CompositeLeafSelector(
                        raw_selector="anthropic:claude-3",
                        normalized_selector="anthropic:claude-3",
                        uri_params={},
                    )
                ),
            ]
        ),
    )


def _build_flow() -> BackendCompletionFlow:
    deps: dict[str, Any] = {
        "availability_checker": MagicMock(),
        "request_preparer": MagicMock(),
        "session_resolver": MagicMock(),
        "backend_invoker": MagicMock(),
        "failover_executor": MagicMock(),
        "wire_capture_orchestrator": MagicMock(),
        "usage_accounting_orchestrator": MagicMock(),
        "exception_normalizer": MagicMock(),
        "stream_formatting_service": MagicMock(),
        "connector_invoker": MagicMock(),
    }
    deps["exception_normalizer"].normalize.side_effect = lambda exc, _backend: exc
    deps["request_preparer"].prepare_request = AsyncMock()
    deps["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    return BackendCompletionFlow(**deps)


def _request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="openai:gpt-4!anthropic:claude-3",
        messages=[ChatMessage(role="user", content="hello")],
    )


def _special_thinker_parallel_request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model=(
            "[thinker]opencode-go:opencode-go/glm-5.2?reasoning_effort=high^"
            "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
            "opencode-go:minimaxai/minimax-m3"
        ),
        messages=[ChatMessage(role="user", content="hello")],
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-parallel-flow",
        session_id="session-parallel-flow",
    )


@pytest.mark.asyncio
async def test_call_completion_dispatches_non_streaming_parallel_plan() -> None:
    flow = _build_flow()
    expected = ResponseEnvelope(content={"choices": []})

    async def fake_execute_parallel_streaming_completion(
        self: BackendCompletionFlow,
        *,
        plan: CompositeRoutePlan,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        stream: bool,
    ) -> ResponseEnvelope:
        assert plan.source_selector == _parallel_plan().source_selector
        assert request.model == "openai:gpt-4!anthropic:claude-3"
        assert context is not None
        assert stream is False
        return expected

    flow._execute_parallel_streaming_completion = (  # type: ignore[method-assign]
        fake_execute_parallel_streaming_completion.__get__(flow, BackendCompletionFlow)
    )

    with patch(
        "src.core.services.backend_completion_flow.service.try_parse_parallel_plan",
        return_value=_parallel_plan(),
    ):
        result = await flow.call_completion(
            request=_request(),
            stream=False,
            allow_failover=True,
            context=_context(),
        )
    assert result is expected
    cast(Any, flow._request_preparer.prepare_request).assert_not_awaited()


@pytest.mark.asyncio
async def test_call_completion_dispatches_streaming_parallel_plan() -> None:
    flow = _build_flow()
    expected = StreamingResponseEnvelope(content=None)

    async def fake_execute_parallel_streaming_completion(
        self: BackendCompletionFlow,
        *,
        plan: CompositeRoutePlan,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        stream: bool,
    ) -> StreamingResponseEnvelope:
        assert plan.source_selector == _parallel_plan().source_selector
        assert request.model == "openai:gpt-4!anthropic:claude-3"
        assert context is not None
        return expected

    flow._execute_parallel_streaming_completion = (  # type: ignore[method-assign]
        fake_execute_parallel_streaming_completion.__get__(flow, BackendCompletionFlow)
    )

    with patch(
        "src.core.services.backend_completion_flow.service.try_parse_parallel_plan",
        return_value=_parallel_plan(),
    ):
        result = await flow.call_completion(
            request=_request(),
            stream=True,
            allow_failover=True,
            context=_context(),
        )

    assert result is expected
    cast(Any, flow._request_preparer.prepare_request).assert_not_awaited()


@pytest.mark.asyncio
async def test_special_thinker_parallel_route_persists_executor_cycle_state() -> None:
    flow = _build_flow()
    session = Session("session-parallel-flow", state=SessionState())
    flow._session_resolver.resolve_session = AsyncMock(  # type: ignore[method-assign]
        return_value=(session, session.session_id)
    )
    expected = ResponseEnvelope(content={"choices": []})

    async def fake_execute_parallel_streaming_completion(
        self: BackendCompletionFlow,
        *,
        plan: CompositeRoutePlan,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        stream: bool,
    ) -> ResponseEnvelope:
        assert isinstance(plan.root_node, CompositeParallelGroupNode)
        leaves = [child.leaf_selector for child in plan.root_node.children]
        assert leaves[0].normalized_selector == (
            "nvidia:minimaxai/minimax-m3?reasoning_effort=high"
        )
        assert leaves[0].handicap_seconds == 10.0
        assert leaves[1].normalized_selector == "opencode-go:minimaxai/minimax-m3"
        assert request is not None
        assert context is not None
        assert stream is False
        return expected

    flow._execute_parallel_streaming_completion = (  # type: ignore[method-assign]
        fake_execute_parallel_streaming_completion.__get__(flow, BackendCompletionFlow)
    )

    result = await flow._maybe_execute_parallel_completion(
        request=_special_thinker_parallel_request(),
        context=_context(),
        stream=False,
    )

    assert result is expected
    cycle_state = session.state.interleaved_thinking_weighted_cycle_state
    assert cycle_state is not None
    assert cycle_state["next_index"] == 1


@pytest.mark.asyncio
async def test_special_thinker_parallel_route_without_session_keeps_context_cycle_unchanged() -> (
    None
):
    flow = _build_flow()
    flow._session_resolver.resolve_session = AsyncMock(  # type: ignore[method-assign]
        return_value=(None, None)
    )
    expected = ResponseEnvelope(content={"choices": []})

    async def fake_execute_parallel_streaming_completion(
        self: BackendCompletionFlow,
        *,
        plan: CompositeRoutePlan,
        request: CanonicalChatRequest,
        context: RequestContext | None,
        stream: bool,
    ) -> ResponseEnvelope:
        assert isinstance(plan.root_node, CompositeParallelGroupNode)
        assert request is not None
        assert context is not None
        assert stream is False
        return expected

    flow._execute_parallel_streaming_completion = (  # type: ignore[method-assign]
        fake_execute_parallel_streaming_completion.__get__(flow, BackendCompletionFlow)
    )

    context = _context()
    result = await flow._maybe_execute_parallel_completion(
        request=_special_thinker_parallel_request(),
        context=context,
        stream=False,
    )

    assert result is expected
    flow._session_resolver.resolve_session.assert_awaited_once()
    assert "interleaved_thinking_weighted_cycle_state" not in context.extensions


@pytest.mark.asyncio
async def test_special_thinker_parallel_route_skips_parallel_on_thinker_turn() -> None:
    flow = _build_flow()
    session = Session(
        "session-parallel-flow",
        state=SessionState().with_interleaved_thinking_weighted_cycle_state(
            {
                "selector": (
                    "[weight=1][thinker]opencode-go:opencode-go/glm-5.2?reasoning_effort=high^"
                    "[weight=1][handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
                    "opencode-go:minimaxai/minimax-m3"
                ),
                "sequence": [
                    "[handicap=10]nvidia:minimaxai/minimax-m3?reasoning_effort=high!"
                    "opencode-go:minimaxai/minimax-m3",
                    "opencode-go:opencode-go/glm-5.2?reasoning_effort=high",
                ],
                "next_index": 1,
            }
        ),
    )
    flow._session_resolver.resolve_session = AsyncMock(  # type: ignore[method-assign]
        return_value=(session, session.session_id)
    )
    flow._execute_parallel_streaming_completion = AsyncMock()  # type: ignore[method-assign]

    result = await flow._maybe_execute_parallel_completion(
        request=_special_thinker_parallel_request(),
        context=_context(),
        stream=False,
    )

    assert result is None
    flow._execute_parallel_streaming_completion.assert_not_awaited()
