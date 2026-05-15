from __future__ import annotations

import logging
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import SessionState
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.interleaved_thinking.output_recorder import (
    INTERLEAVED_THINKING_RECORDER_DIAGNOSTIC_KEY,
    InterleavedThinkingOutputRecorder,
)


def _context() -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-recorder",
        session_id="session-recorder",
    )
    context.extensions["composite_selected_leaf_selector"] = "openai:gpt-4"
    return context


def _session() -> MagicMock:
    session = MagicMock()
    session.state = SessionState()
    session.update_state = MagicMock()
    return session


def _diagnostic(context: RequestContext) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        context.extensions[INTERLEAVED_THINKING_RECORDER_DIAGNOSTIC_KEY],
    )


def test_recorder_captures_non_streaming_reasoning_content() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)
    response = ResponseEnvelope(
        content={
            "choices": [{"message": {"reasoning_content": "memo from reasoning field"}}]
        }
    )

    recorder.capture_non_streaming(
        response=response,
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "memo from reasoning field"
    assert stored["backend"] == "openai"
    assert stored["model"] == "gpt-4"
    assert stored["extraction_source"] == "reasoning_content"
    diagnostic = _diagnostic(context)
    assert diagnostic["extraction_source"] == "reasoning_content"


def test_recorder_uses_configured_regular_turns_remaining() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(
        max_output_chars=8000,
        regular_turns_remaining=4,
    )
    response = ResponseEnvelope(
        content={
            "choices": [{"message": {"reasoning_content": "memo from reasoning field"}}]
        }
    )

    recorder.capture_non_streaming(
        response=response,
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["regular_turns_remaining"] == 4


def test_recorder_writes_capture_diagnostic_when_memo_is_stored() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    recorder.capture_non_streaming(
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "visible memo"}}]}
        ),
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_stored"
    assert diagnostic["backend"] == "openai"
    assert diagnostic["model"] == "gpt-4"
    assert diagnostic["memo_chars"] == len("visible memo")
    assert diagnostic["source_selector"] == "openai:gpt-4"
    assert diagnostic["extraction_source"] == "content"


def test_recorder_writes_skip_diagnostic_for_empty_memo() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    recorder.capture_non_streaming(
        response=ResponseEnvelope(content={"choices": [{"message": {"content": ""}}]}),
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_store_skipped"
    assert diagnostic["reason"] == "empty_memo"


def test_recorder_writes_skip_diagnostic_for_unsupported_response_shape() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    recorder.capture_non_streaming(
        response=ResponseEnvelope(content={"candidate": {"text": "gemini shape"}}),
        session=session,
        context=context,
        backend_type="gemini",
        effective_model="gemini-pro",
    )

    session.update_state.assert_not_called()
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_store_skipped"
    assert diagnostic["reason"] == "no_extractable_memo"
    assert diagnostic["backend"] == "gemini"


def test_recorder_falls_back_to_non_streaming_message_content() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)
    response = ResponseEnvelope(
        content={"choices": [{"message": {"content": "visible memo"}}]}
    )

    recorder.capture_non_streaming(
        response=response,
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "visible memo"
    assert stored["extraction_source"] == "content"


def test_recorder_strips_proxy_thinker_memo_tags_before_storing() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)
    response = ResponseEnvelope(
        content={
            "choices": [
                {
                    "message": {
                        "content": (
                            "prefix <proxy_thinker_memo>inner memo"
                            "</proxy_thinker_memo> suffix"
                        )
                    }
                }
            ]
        }
    )

    recorder.capture_non_streaming(
        response=response,
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "inner memo"
    assert "<proxy_thinker_memo>" not in stored["memo"]


def test_recorder_preserves_xml_tool_call_text_in_stored_memo_and_response() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)
    tool_call_text = (
        "Thinking: I should inspect files.\n"
        "<tool_call>\n"
        "<function=bash>\n"
        "<parameter=command>git diff</parameter>\n"
        "</function>\n"
        "</tool_call>\n"
        "Next: review the diff."
    )
    response = ResponseEnvelope(
        content={"choices": [{"message": {"content": tool_call_text}}]}
    )

    recorder.capture_non_streaming(
        response=response,
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert "<tool_call>" in stored["memo"]
    assert "<function=bash>" in stored["memo"]
    assert "git diff" in stored["memo"]
    assert "Next: review the diff." in stored["memo"]
    response_content = cast(dict[str, Any], response.content)
    message = response_content["choices"][0]["message"]
    assert "<tool_call>" in message["content"]
    assert "git diff" in message["content"]


def test_recorder_ignores_empty_non_streaming_output() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    recorder.capture_non_streaming(
        response=ResponseEnvelope(content={"choices": [{"message": {"content": ""}}]}),
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    session.update_state.assert_not_called()


@pytest.mark.asyncio
async def test_recorder_wraps_stream_without_buffering_before_yield() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    async def stream():
        yield ProcessedResponse(
            content={
                "choices": [
                    {"delta": {"reasoning_content": "memo ", "content": "visible "}}
                ]
            }
        )
        yield ProcessedResponse(
            content={"choices": [{"delta": {"reasoning_content": "done"}}]}
        )

    envelope = StreamingResponseEnvelope(content=stream())
    wrapped = recorder.wrap_streaming(
        response=envelope,
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    assert wrapped is envelope
    assert wrapped.content is not None
    first = await anext(wrapped.content)
    assert isinstance(first.content, dict)
    session.update_state.assert_not_called()
    second = await anext(wrapped.content)
    assert isinstance(second.content, dict)
    with pytest.raises(StopAsyncIteration):
        await anext(wrapped.content)

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "memo done"


@pytest.mark.asyncio
async def test_recorder_sanitizes_visible_stream_and_converts_reasoning_to_content() -> (
    None
):
    recorder = InterleavedThinkingOutputRecorder(
        max_output_chars=8000,
        stream_to_client=True,
    )

    async def stream():
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": ("<proxy_thinker_memo>visible memo")
                        }
                    }
                ]
            }
        )
        yield ProcessedResponse(
            content={
                "choices": [{"delta": {"reasoning_content": "</proxy_thinker_memo>"}}]
            }
        )

    chunks = [item async for item in recorder.sanitize_visible_stream(stream())]

    assert len(chunks) == 1
    chunk = cast(dict[str, Any], chunks[0].content)
    delta = chunk["choices"][0]["delta"]
    assert delta["content"] == "visible memo"
    assert "reasoning_content" not in delta
    assert recorder.stream_to_client is True


@pytest.mark.asyncio
async def test_recorder_preserves_streaming_tool_call_text_before_yielding() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    async def stream():
        yield ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {
                            "content": (
                                "Memo start <tool_call><function=bash>"
                                "<parameter=command>git status</parameter>"
                                "</function></tool_call> memo end"
                            )
                        }
                    }
                ]
            }
        )

    envelope = StreamingResponseEnvelope(content=stream())
    wrapped = recorder.wrap_streaming(
        response=envelope,
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    assert wrapped.content is not None
    first = await anext(wrapped.content)
    assert isinstance(first.content, dict)
    first_content = cast(dict[str, Any], first.content)
    delta = first_content["choices"][0]["delta"]
    assert "<tool_call>" in delta["content"]
    assert "git status" in delta["content"]
    assert "memo end" in delta["content"]
    with pytest.raises(StopAsyncIteration):
        await anext(wrapped.content)
    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert "git status" in stored["memo"]


@pytest.mark.asyncio
async def test_recorder_records_diagnostic_when_stream_is_interrupted() -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    async def stream():
        yield ProcessedResponse(
            content={"choices": [{"delta": {"reasoning_content": "partial memo"}}]}
        )
        raise RuntimeError("stream failed")

    envelope = StreamingResponseEnvelope(content=stream())
    wrapped = recorder.wrap_streaming(
        response=envelope,
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    assert wrapped.content is not None
    await anext(wrapped.content)
    with pytest.raises(RuntimeError, match="stream failed"):
        await anext(wrapped.content)

    session.update_state.assert_not_called()
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_store_skipped"
    assert diagnostic["reason"] == "stream_interrupted"
    assert diagnostic["partial_memo_chars"] == len("partial memo")


@pytest.mark.asyncio
async def test_recorder_does_not_warn_when_stream_is_closed_by_disconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    session = _session()
    context = _context()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=8000)

    async def stream():
        yield ProcessedResponse(
            content={"choices": [{"delta": {"reasoning_content": "partial memo"}}]}
        )

    envelope = StreamingResponseEnvelope(content=stream())
    wrapped = recorder.wrap_streaming(
        response=envelope,
        session=session,
        context=context,
        backend_type="openai",
        effective_model="gpt-4",
    )

    assert wrapped.content is not None
    with caplog.at_level(
        logging.WARNING,
        logger="src.core.services.interleaved_thinking.output_recorder",
    ):
        await anext(wrapped.content)
        await cast(Any, wrapped.content).aclose()

    session.update_state.assert_not_called()
    assert not [
        record
        for record in caplog.records
        if "Interleaved thinking memo store skipped: stream interrupted"
        in record.message
    ]
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_store_skipped"
    assert diagnostic["reason"] == "stream_interrupted"
    assert diagnostic["partial_memo_chars"] == len("partial memo")


def test_recorder_truncates_stored_memo() -> None:
    session = _session()
    recorder = InterleavedThinkingOutputRecorder(max_output_chars=4)

    recorder.capture_non_streaming(
        response=ResponseEnvelope(
            content={"choices": [{"message": {"content": "123456"}}]}
        ),
        session=session,
        context=_context(),
        backend_type="openai",
        effective_model="gpt-4",
    )

    stored = session.update_state.call_args.args[0].interleaved_thinking_state
    assert stored["memo"] == "1234"
