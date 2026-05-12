from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.models.backends import BackendSettings
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope
from src.core.domain.session import SessionState
from src.core.services.backend_completion_flow.service import BackendCompletionFlow
from src.core.services.composite_routing_state import (
    COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY,
)
from src.core.services.interleaved_thinking.output_recorder import (
    InterleavedThinkingOutputRecorder,
)
from src.core.services.interleaved_thinking.transformer import (
    InterleavedThinkingRequestTransformer,
)


def _context(*, thinker: bool) -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-flow-thinking",
        session_id="session-flow-thinking",
    )
    context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] = thinker
    context.extensions["composite_selected_leaf_selector"] = "openai:gpt-4"
    return context


def _build_flow(
    *,
    session: Any,
    target: BackendTarget,
    response: ResponseEnvelope,
    settings: BackendSettings,
) -> tuple[BackendCompletionFlow, dict[str, Any]]:
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
    deps["request_preparer"].prepare_request = AsyncMock(return_value=target)
    deps["request_preparer"].synchronize_request_with_target.side_effect = (
        lambda req, _target: req
    )
    deps["failover_executor"].check_complex_failover = AsyncMock(return_value=False)
    deps["availability_checker"].check_backend_availability = AsyncMock()
    deps["session_resolver"].resolve_session = AsyncMock(
        return_value=(session, "session-flow-thinking")
    )
    deps["backend_invoker"].acquire_backend = AsyncMock(return_value=MagicMock())
    deps["request_preparer"].prepare_backend_request = AsyncMock(
        side_effect=lambda request, *_args, **_kwargs: request
    )
    deps["request_preparer"].prepare_backend_kwargs = MagicMock(return_value={})
    deps["wire_capture_orchestrator"].prepare_wire_capture_context = AsyncMock(
        return_value=None
    )
    deps["wire_capture_orchestrator"].capture_wire_outbound = AsyncMock()
    deps["wire_capture_orchestrator"].capture_inbound_response = AsyncMock()
    deps["wire_capture_orchestrator"].detect_key_name.return_value = "key"
    deps["usage_accounting_orchestrator"].calculate_and_record_usage = AsyncMock(
        return_value=(0, None, None)
    )
    deps["usage_accounting_orchestrator"].wrap_response_for_usage = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_non_streaming_response = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_backend_error = AsyncMock()
    deps["usage_accounting_orchestrator"].handle_auth_failure = AsyncMock()
    deps["connector_invoker"].invoke = AsyncMock(return_value=response)

    flow = BackendCompletionFlow(
        availability_checker=deps["availability_checker"],
        request_preparer=deps["request_preparer"],
        session_resolver=deps["session_resolver"],
        backend_invoker=deps["backend_invoker"],
        failover_executor=deps["failover_executor"],
        wire_capture_orchestrator=deps["wire_capture_orchestrator"],
        usage_accounting_orchestrator=deps["usage_accounting_orchestrator"],
        exception_normalizer=deps["exception_normalizer"],
        stream_formatting_service=deps["stream_formatting_service"],
        connector_invoker=deps["connector_invoker"],
        interleaved_thinking_transformer=InterleavedThinkingRequestTransformer(
            settings
        ),
        interleaved_thinking_output_recorder=InterleavedThinkingOutputRecorder(),
    )
    return flow, deps


@pytest.mark.asyncio
async def test_completion_flow_applies_thinker_transform_and_records_output(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = MagicMock()
    session.state = SessionState()
    session.update_state = MagicMock()
    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "new thinker memo"}}]}
        ),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file)
        ),
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            tools=[{"type": "function", "function": {"name": "tool"}}],
        ),
        stream=False,
        allow_failover=False,
        context=_context(thinker=True),
    )

    assert isinstance(result, ResponseEnvelope)
    invoked_request = deps["connector_invoker"].invoke.call_args.kwargs[
        "domain_request"
    ]
    assert invoked_request.messages[0].content == "Thinker instructions"
    assert invoked_request.tools == [{"type": "function", "function": {"name": "tool"}}]
    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "new thinker memo"


@pytest.mark.asyncio
async def test_completion_flow_injects_existing_memo_for_non_thinker() -> None:
    session = MagicMock()
    session.state = SessionState(
        interleaved_thinking_state={
            "memo": "stored memo",
            "source_selector": "openai:gpt-4",
        }
    )
    session.update_state = MagicMock()
    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}
        ),
        settings=BackendSettings(),
    )

    await flow.call_completion(
        request=CanonicalChatRequest(
            model="flash",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        stream=False,
        allow_failover=False,
        context=_context(thinker=False),
    )

    invoked_request = deps["connector_invoker"].invoke.call_args.kwargs[
        "domain_request"
    ]
    assert any(
        message.reasoning_content == "stored memo"
        for message in invoked_request.messages
    )
    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 1


@pytest.mark.asyncio
async def test_completion_flow_recovery_uses_untransformed_request(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = MagicMock()
    session.state = SessionState()
    session.update_state = MagicMock()
    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "ok"}}]}
        ),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file)
        ),
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=BackendError("upstream failed", backend_name="openai")
    )
    deps["failover_executor"].apply_failure_recovery = AsyncMock(
        return_value=ResponseEnvelope(content={"ok": True})
    )
    original_request = CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
        tools=[{"type": "function", "function": {"name": "tool"}}],
    )

    result = await flow.call_completion(
        request=original_request,
        stream=False,
        allow_failover=True,
        context=_context(thinker=True),
    )

    assert isinstance(result, ResponseEnvelope)
    recovery_call = deps["failover_executor"].apply_failure_recovery.await_args
    assert recovery_call is not None
    recovery_request = recovery_call.kwargs["request"]
    assert recovery_request.messages == original_request.messages
    assert recovery_request.tools == original_request.tools
