from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.common.exceptions import BackendError
from src.core.config.models.backends import BackendSettings
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import SessionState
from src.core.interfaces.response_processor_interface import ProcessedResponse
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
    response: ResponseEnvelope | StreamingResponseEnvelope,
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
    deps["usage_accounting_orchestrator"].handle_streaming_response = AsyncMock(
        side_effect=lambda **kwargs: kwargs["result"]
    )
    deps["usage_accounting_orchestrator"].handle_backend_error = AsyncMock()
    deps["usage_accounting_orchestrator"].handle_auth_failure = AsyncMock()
    deps["stream_formatting_service"].stream_as_sse_bytes.side_effect = (
        _stream_as_sse_bytes
    )
    deps["wire_capture_orchestrator"].wrap_inbound_stream.side_effect = (
        lambda **kwargs: kwargs["stream"]
    )
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
        interleaved_thinking_output_recorder=InterleavedThinkingOutputRecorder(
            stream_to_client=settings.interleaved_thinking_stream_to_client
        ),
    )
    return flow, deps


async def _stream_as_sse_bytes(source: Any) -> Any:
    async for item in source:
        yield f"data: {json.dumps(item.content)}\n\n".encode()


def _stateful_session(state: SessionState | None = None) -> MagicMock:
    session = MagicMock()
    session.state = state or SessionState()

    def update_state(updated_state: SessionState) -> None:
        session.state = updated_state

    session.update_state = MagicMock(side_effect=update_state)
    return session


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
    invoked_request = (
        deps["connector_invoker"].invoke.await_args_list[0].kwargs["domain_request"]
    )
    assert invoked_request.messages[0].content == "Thinker instructions"
    assert invoked_request.tools is None
    assert invoked_request.tool_choice is None
    assert invoked_request.parallel_tool_calls is None
    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "new thinker memo"


@pytest.mark.asyncio
async def test_completion_flow_swallows_thinker_stream_and_continues_with_executor(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()

    async def thinker_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "content": "<proxy_thinker_memo>plan it</proxy_thinker_memo>"
                        }
                    }
                ]
            }
        )

    async def executor_stream() -> Any:
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "final answer"}}]}
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=StreamingResponseEnvelope(content=thinker_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file)
        ),
    )
    deps["request_preparer"].prepare_request = AsyncMock(
        side_effect=[
            BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            BackendTarget(backend="openrouter", model="flash", uri_params={}),
        ]
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=thinker_stream()),
            StreamingResponseEnvelope(content=executor_stream()),
        ]
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        stream=True,
        allow_failover=False,
        context=_context(thinker=True),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [item async for item in result.content]
    rendered = "\n".join(str(chunk.content) for chunk in chunks)
    assert "plan it" not in rendered
    assert "final answer" in rendered
    assert all("proxy_thinker_memo" not in str(chunk.content) for chunk in chunks)
    assert deps["connector_invoker"].invoke.await_count == 2
    executor_request = (
        deps["connector_invoker"].invoke.await_args_list[1].kwargs["domain_request"]
    )
    assert executor_request.messages[0].role == "system"
    assert "plan it" in str(executor_request.messages[0].content)
    assert any(
        message.reasoning_content == "plan it" for message in executor_request.messages
    )
    assert all(
        message.metadata
        != {
            "source": "interleaved_thinking",
            "kind": "visible_thinker_output",
        }
        for message in executor_request.messages
    )
    assert executor_request.messages[0].metadata == {
        "source": "interleaved_thinking",
        "kind": "thinker_memo_system",
    }
    assert any(
        message.metadata
        == {
            "source": "interleaved_thinking",
            "kind": "thinker_memo_reasoning",
        }
        for message in executor_request.messages
    )
    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "plan it"
    assert stored["visible_to_client"] is False


@pytest.mark.asyncio
async def test_completion_flow_can_stream_sanitized_thinker_text_before_executor(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()

    async def thinker_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [{"delta": {"content": "<proxy_thinker_memo>visible plan"}}]
            }
        )
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "</proxy_thinker_memo>"}}]}
        )

    async def executor_stream() -> Any:
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "executor answer"}}]}
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=StreamingResponseEnvelope(content=thinker_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )
    deps["request_preparer"].prepare_request = AsyncMock(
        side_effect=[
            BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            BackendTarget(backend="openrouter", model="flash", uri_params={}),
        ]
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=thinker_stream()),
            StreamingResponseEnvelope(content=executor_stream()),
        ]
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        stream=True,
        allow_failover=False,
        context=_context(thinker=True),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [item async for item in result.content]
    rendered = "\n".join(str(chunk.content) for chunk in chunks)
    assert "visible plan" in rendered
    assert "executor answer" in rendered
    assert "proxy_thinker_memo" not in rendered
    thinker_chunk = cast(dict[str, Any], chunks[0].content)
    thinker_delta = thinker_chunk["choices"][0]["delta"]
    assert thinker_delta["reasoning_content"] == "visible plan"
    assert thinker_delta["content"] == ""
    assert deps["connector_invoker"].invoke.await_count == 2
    executor_request = (
        deps["connector_invoker"].invoke.await_args_list[1].kwargs["domain_request"]
    )
    assert executor_request.messages[-2].role == "user"
    assert executor_request.messages[-1].role == "assistant"
    assert executor_request.messages[-1].content == "visible plan"


@pytest.mark.asyncio
async def test_completion_flow_strips_client_carried_reasoning_before_thinker_call(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()
    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "fresh memo"}}]}
        ),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )

    await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[
                ChatMessage(role="user", content="start"),
                ChatMessage(
                    role="assistant",
                    content="",
                    reasoning_content=(
                        "Goal:\nPreviously visible thinker memo that must not loop"
                    ),
                ),
                ChatMessage(role="user", content="continue"),
            ],
        ),
        stream=False,
        allow_failover=False,
        context=_context(thinker=True),
    )

    invoked_request = (
        deps["connector_invoker"].invoke.await_args_list[0].kwargs["domain_request"]
    )
    assert all(
        message.reasoning_content is None for message in invoked_request.messages
    )
    assert "Previously visible thinker memo" not in "\n".join(
        str(message.content) for message in invoked_request.messages
    )


@pytest.mark.asyncio
async def test_completion_flow_preserves_non_thinker_reasoning_for_interleaved_selector(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()

    async def executor_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "deepseek hidden reasoning",
                            "content": "",
                        }
                    }
                ]
            }
        )
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "executor answer"}}]}
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="opencode-zen.1", model="deepseek", uri_params={}),
        response=StreamingResponseEnvelope(content=executor_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[
                ChatMessage(role="user", content="start"),
                ChatMessage(
                    role="assistant",
                    content="",
                    reasoning_content="old visible thinker memo",
                ),
                ChatMessage(role="user", content="continue"),
            ],
        ),
        stream=True,
        allow_failover=False,
        context=_context(thinker=False),
    )

    invoked_request = (
        deps["connector_invoker"].invoke.await_args_list[0].kwargs["domain_request"]
    )
    assert invoked_request.messages[1].reasoning_content == "old visible thinker memo"
    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [item async for item in result.content]
    rendered = "\n".join(str(chunk.content) for chunk in chunks)
    assert "executor answer" in rendered
    assert "deepseek hidden reasoning" in rendered
    assert any("reasoning_content" in str(chunk.content) for chunk in chunks)


@pytest.mark.asyncio
async def test_completion_flow_preserves_executor_reasoning_from_visible_thinker_stream(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()

    async def thinker_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "content": (
                                "<proxy_thinker_memo>thinker plan"
                                "</proxy_thinker_memo>"
                            )
                        }
                    }
                ]
            }
        )

    async def executor_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "executor hidden reasoning",
                            "content": "",
                        }
                    }
                ]
            }
        )
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "executor answer"}}]}
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=StreamingResponseEnvelope(content=thinker_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )
    deps["request_preparer"].prepare_request = AsyncMock(
        side_effect=[
            BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            BackendTarget(backend="opencode-zen.1", model="deepseek", uri_params={}),
        ]
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=thinker_stream()),
            StreamingResponseEnvelope(content=executor_stream()),
        ]
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[
                ChatMessage(role="user", content="hello"),
                ChatMessage(
                    role="assistant",
                    content="",
                    reasoning_content="prior deepseek reasoning",
                ),
                ChatMessage(role="user", content="continue"),
            ],
        ),
        stream=True,
        allow_failover=False,
        context=_context(thinker=True),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [item async for item in result.content]
    rendered = "\n".join(str(chunk.content) for chunk in chunks)
    assert "thinker plan" in rendered
    assert "executor answer" in rendered
    assert "executor hidden reasoning" in rendered
    assert any("reasoning_content" in str(chunk.content) for chunk in chunks[1:])
    executor_request = (
        deps["connector_invoker"].invoke.await_args_list[1].kwargs["domain_request"]
    )
    assert any(
        message.reasoning_content == "prior deepseek reasoning"
        for message in executor_request.messages
    )


@pytest.mark.asyncio
async def test_completion_flow_streams_visible_thinker_text_before_thinker_finishes(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()
    thinker_can_finish = asyncio.Event()

    async def thinker_stream() -> Any:
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "<proxy_thinker_memo>visible"}}]}
        )
        await thinker_can_finish.wait()
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "</proxy_thinker_memo>"}}]}
        )

    async def executor_stream() -> Any:
        yield ProcessedResponse(
            content={"choices": [{"delta": {"content": "executor answer"}}]}
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=StreamingResponseEnvelope(content=thinker_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )
    deps["request_preparer"].prepare_request = AsyncMock(
        side_effect=[
            BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            BackendTarget(backend="openrouter", model="flash", uri_params={}),
        ]
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=thinker_stream()),
            StreamingResponseEnvelope(content=executor_stream()),
        ]
    )

    result = await asyncio.wait_for(
        flow.call_completion(
            request=CanonicalChatRequest(
                model="alias:hybrid",
                messages=[ChatMessage(role="user", content="hello")],
            ),
            stream=True,
            allow_failover=False,
            context=_context(thinker=True),
        ),
        timeout=1,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    stream_iter = result.content.__aiter__()
    first = await asyncio.wait_for(anext(stream_iter), timeout=1)
    assert "visible" in str(first.content)
    assert deps["connector_invoker"].invoke.await_count == 1

    thinker_can_finish.set()
    remaining = [item async for item in stream_iter]
    rendered_remaining = "\n".join(str(chunk.content) for chunk in remaining)
    assert "executor answer" in rendered_remaining
    assert deps["connector_invoker"].invoke.await_count == 2


@pytest.mark.asyncio
async def test_completion_flow_visible_thinker_wraps_non_streaming_executor_result(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    session = _stateful_session()

    async def thinker_stream() -> Any:
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "content": "<proxy_thinker_memo>visible plan</proxy_thinker_memo>"
                        }
                    }
                ]
            }
        )

    flow, deps = _build_flow(
        session=session,
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        response=StreamingResponseEnvelope(content=thinker_stream()),
        settings=BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
            interleaved_thinking_stream_to_client=True,
        ),
    )
    deps["request_preparer"].prepare_request = AsyncMock(
        side_effect=[
            BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            BackendTarget(backend="openrouter", model="flash", uri_params={}),
        ]
    )
    deps["connector_invoker"].invoke = AsyncMock(
        side_effect=[
            StreamingResponseEnvelope(content=thinker_stream()),
            ResponseEnvelope(content={"choices": [{"message": {"content": "done"}}]}),
        ]
    )

    result = await flow.call_completion(
        request=CanonicalChatRequest(
            model="alias:hybrid",
            messages=[ChatMessage(role="user", content="hello")],
        ),
        stream=True,
        allow_failover=False,
        context=_context(thinker=True),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [item async for item in result.content]
    rendered = "\n".join(str(chunk.content) for chunk in chunks)
    assert "visible plan" in rendered
    assert "done" in rendered


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
