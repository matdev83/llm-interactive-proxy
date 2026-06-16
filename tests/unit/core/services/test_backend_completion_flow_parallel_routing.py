from __future__ import annotations

from typing import Any
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
    flow._request_preparer.prepare_request.assert_not_awaited()


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
    flow._request_preparer.prepare_request.assert_not_awaited()
