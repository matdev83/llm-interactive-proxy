from __future__ import annotations

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.backend_request_manager_service import BackendRequestManager

from tests.helpers.angel_factory_stub import AngelFactoryStub


def _make_context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state=None,
        app_state=None,
        client_host=None,
        session_id=None,
        agent=None,
        original_request=None,
        processing_context=None,
    )


@pytest.mark.asyncio
async def test_streaming_retry_replays_full_replacement_stream() -> None:
    """Ensure streaming retries forward the complete replacement stream."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    backend_response = ResponseEnvelope(
        content="dangerous tool response",
        metadata={
            "tool_call_swallowed": True,
            "steering_message": "Do not execute that command.",
            "swallowed_original_content": "rm -rf /",
            "swallowed_tool_calls": [
                {"function": {"name": "shell", "arguments": "{}"}}
            ],
        },
    )

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="safe replacement 1", metadata={})
        yield ProcessedResponse(
            content="safe replacement 2", metadata={"is_done": True}
        )

    backend_processor.process_backend_request.return_value = StreamingResponseEnvelope(
        content=retry_stream()
    )

    result = await manager._retry_after_tool_swallow(
        original_request,
        backend_response,
        "session-x",
        _make_context(),
        is_streaming=True,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks: list[str] = []
    async for chunk in result.content:
        chunks.append(str(chunk.content))

    assert chunks == ["safe replacement 1", "safe replacement 2"]
    assert backend_processor.process_backend_request.await_count == 1


@pytest.mark.asyncio
async def test_empty_stream_is_retried_before_forwarding() -> None:
    """Empty streaming responses should trigger a retry instead of reaching the client."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="hi")],
        stream=True,
    )

    async def empty_stream():
        yield ProcessedResponse(content={"usage": {"prompt_tokens": 1}}, metadata={})
        yield ProcessedResponse(content="", metadata={"is_done": True})

    async def retry_stream():
        yield ProcessedResponse(content="meaningful output", metadata={})
        yield ProcessedResponse(content="", metadata={"is_done": True})

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=retry_stream())
    ]

    envelope = await manager._process_streaming_response(
        StreamingResponseEnvelope(content=empty_stream()),
        original_request,
        "session-empty",
        _make_context(),
    )

    assert envelope.content is not None
    chunks = [chunk async for chunk in envelope.content]

    assert backend_processor.process_backend_request.await_count == 1
    retry_args = backend_processor.process_backend_request.await_args_list[0].kwargs
    retry_request = retry_args["request"]
    assert isinstance(retry_request, ChatRequest)
    assert retry_request.messages[-1].content == manager._STREAM_RECOVERY_PROMPT

    assert any(chunk.content == "meaningful output" for chunk in chunks)
    assert all(chunk.content != {"usage": {"prompt_tokens": 1}} for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_retry_skipped_when_retry_marker_present() -> None:
    """When retry marker is present, the reactor should not trigger again."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    flagged_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="continue")],
        stream=True,
        extra_body={"_tool_call_reactor_retry": True},
    )

    async def original_stream():
        yield ProcessedResponse(
            content="proxy replacement",
            metadata={
                "tool_call_swallowed": True,
                "steering_message": "Already handled.",
            },
        )

    stream_envelope = StreamingResponseEnvelope(content=original_stream())

    result = await manager._process_streaming_response(
        stream_envelope,
        flagged_request,
        "session-y",
        _make_context(),
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    assert len(chunks) == 1
    assert chunks[0].metadata.get("tool_call_swallowed") is True
    assert backend_processor.process_backend_request.await_count == 0


@pytest.mark.asyncio
async def test_full_suite_swallow_replays_history_and_hides_steering() -> None:
    """Full-suite steering should replay the request with history and hide steering output."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "please target specific tests",
        "swallowed_original_content": "original llm response",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "pytest"}}
        ],
    }
    steering_processed = ProcessedResponse(
        content="steering-text", metadata=steering_metadata
    )
    corrected_processed = ProcessedResponse(
        content="corrected output", metadata={"clean": True}
    )
    response_processor.process_response = AsyncMock(
        side_effect=[steering_processed, corrected_processed]
    )
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_messages = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="run all tests"),
    ]
    original_request = ChatRequest(
        model="gemini",
        messages=original_messages,
        stream=False,
    )

    backend_processor.process_backend_request.side_effect = [
        ResponseEnvelope(content="raw tool call"),
        ResponseEnvelope(content="second response"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-full-suite", _make_context()
    )

    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    retry_request = retry_args["request"]
    assert isinstance(retry_request, ChatRequest)
    assert len(retry_request.messages) == len(original_messages) + 1
    assert retry_request.messages[: len(original_messages)] == original_messages
    assert retry_request.messages[-1].role == "system"
    proxy_notice = retry_request.messages[-1].content
    assert "Proxy Notice" in proxy_notice
    assert "please target specific tests" in proxy_notice
    assert "execute_command" in proxy_notice
    assert "pytest" in proxy_notice
    assert retry_request.extra_body.get("_tool_call_reactor_retry") is True

    assert isinstance(result, ResponseEnvelope)
    assert result.content == "corrected output"
    assert result.metadata.get("clean") is True
    assert result.content != steering_processed.content


@pytest.mark.asyncio
async def test_full_suite_swallow_retry_failure_does_not_leak_steering() -> None:
    """If steering replay fails, do not forward steering text to the client."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "avoid full suite",
        "swallowed_original_content": "raw llm response",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "pytest"}}
        ],
    }
    steering_processed = ProcessedResponse(
        content="steering-text", metadata=steering_metadata
    )
    response_processor.process_response = AsyncMock(return_value=steering_processed)
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="please run pytest")],
        stream=False,
    )

    backend_processor.process_backend_request.side_effect = [
        ResponseEnvelope(content="raw tool call"),
        RuntimeError("backend failure"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-retry-fail", _make_context()
    )

    assert backend_processor.process_backend_request.await_count == 2
    assert isinstance(result, ResponseEnvelope)
    assert result.content == ""
    assert result.metadata.get("tool_call_swallowed") is True
    assert result.content != steering_processed.content


@pytest.mark.asyncio
async def test_streaming_full_suite_swallow_replays_history_and_hides_steering() -> (
    None
):
    """Streaming full-suite steering should replay history and hide steering chunk."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_messages = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="run all tests"),
    ]
    original_request = ChatRequest(
        model="gemini",
        messages=original_messages,
        stream=True,
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "please target specific tests",
        "swallowed_original_content": "stream steering content",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "pytest"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="fixed 1", metadata={})
        yield ProcessedResponse(content="fixed 2", metadata={"is_done": True})

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        StreamingResponseEnvelope(content=retry_stream()),
    ]

    result = await manager.process_backend_request(
        original_request, "session-stream-full-suite", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]

    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    retry_request = retry_args["request"]
    assert isinstance(retry_request, ChatRequest)
    assert len(retry_request.messages) == len(original_messages) + 1
    assert retry_request.messages[: len(original_messages)] == original_messages
    assert retry_request.messages[-1].role == "system"
    proxy_notice = retry_request.messages[-1].content
    assert "Proxy Notice" in proxy_notice
    assert "please target specific tests" in proxy_notice
    assert "execute_command" in proxy_notice
    assert retry_request.extra_body.get("_tool_call_reactor_retry") is True

    assert [chunk.content for chunk in chunks] == ["fixed 1", "fixed 2"]
    assert all("steering chunk" not in str(chunk.content) for chunk in chunks)


@pytest.mark.asyncio
async def test_streaming_full_suite_swallow_retry_failure_does_not_leak_steering() -> (
    None
):
    """Streaming replay failures should not surface steering content."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="run all tests")],
        stream=True,
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "avoid full suite",
        "swallowed_original_content": "stream steering content",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "pytest"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        RuntimeError("backend failure"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-stream-retry-fail", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]

    assert backend_processor.process_backend_request.await_count == 2
    assert len(chunks) == 1
    assert chunks[0].content == ""
    metadata = getattr(chunks[0], "metadata", {})
    assert metadata.get("tool_call_swallowed") is True
    assert metadata.get("tool_call_reactor_retry_failed") is True
    assert "steering chunk" not in str(chunks[0].content)


@pytest.mark.asyncio
async def test_dangerous_command_swallow_replays_history_and_hides_steering() -> None:
    """Dangerous command steering should replay history and hide steering output."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "dangerous command blocked",
        "swallowed_original_content": "raw dangerous output",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "git reset --hard"}}
        ],
    }
    steering_processed = ProcessedResponse(
        content="steering-text", metadata=steering_metadata
    )
    corrected_processed = ProcessedResponse(content="safe reply", metadata={})
    response_processor.process_response = AsyncMock(
        side_effect=[steering_processed, corrected_processed]
    )
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_messages = [
        ChatMessage(role="user", content="do git reset --hard"),
    ]
    original_request = ChatRequest(
        model="gemini",
        messages=original_messages,
        stream=False,
    )

    backend_processor.process_backend_request.side_effect = [
        ResponseEnvelope(content="raw tool call"),
        ResponseEnvelope(content="second response"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-dangerous", _make_context()
    )

    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    retry_request = retry_args["request"]
    proxy_notice = retry_request.messages[-1].content
    assert "git reset --hard" in proxy_notice
    assert "dangerous command blocked" in proxy_notice
    assert retry_request.extra_body.get("_tool_call_reactor_retry") is True

    assert isinstance(result, ResponseEnvelope)
    assert result.content == "safe reply"
    assert result.content != steering_processed.content


@pytest.mark.asyncio
async def test_tool_access_block_non_streaming_replays_and_hides_steering() -> None:
    """Tool access control steering should replay history and hide steering for non-stream."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "tool not allowed",
        "swallowed_original_content": "blocked content",
        "swallowed_tool_calls": [
            {"function": {"name": "deploy_service", "arguments": "{}"}}
        ],
    }
    steering_processed = ProcessedResponse(
        content="steering-text", metadata=steering_metadata
    )
    corrected_processed = ProcessedResponse(content="allowed output", metadata={})
    response_processor.process_response = AsyncMock(
        side_effect=[steering_processed, corrected_processed]
    )
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="deploy now")],
        stream=False,
    )

    backend_processor.process_backend_request.side_effect = [
        ResponseEnvelope(content="raw tool call"),
        ResponseEnvelope(content="second response"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-tool-access-ns", _make_context()
    )

    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    proxy_notice = retry_args["request"].messages[-1].content
    assert "deploy_service" in proxy_notice
    assert "tool not allowed" in proxy_notice
    assert retry_args["request"].extra_body.get("_tool_call_reactor_retry") is True
    assert isinstance(result, ResponseEnvelope)
    assert result.content == "allowed output"


@pytest.mark.asyncio
async def test_tool_access_block_streaming_replays_and_hides_steering() -> None:
    """Tool access control steering should replay history and hide steering chunk."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "tool not allowed",
        "swallowed_original_content": "blocked stream content",
        "swallowed_tool_calls": [
            {"function": {"name": "deploy_service", "arguments": "{}"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="allowed later", metadata={})

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        StreamingResponseEnvelope(content=retry_stream()),
    ]

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="deploy now")],
        stream=True,
    )

    result = await manager.process_backend_request(
        original_request, "session-tool-access", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    retry_request = retry_args["request"]
    proxy_notice = retry_request.messages[-1].content
    assert "deploy_service" in proxy_notice
    assert "tool not allowed" in proxy_notice
    assert retry_request.extra_body.get("_tool_call_reactor_retry") is True
    assert [chunk.content for chunk in chunks] == ["allowed later"]
    assert all("steering chunk" not in str(chunk.content) for chunk in chunks)


@pytest.mark.asyncio
async def test_config_steering_streaming_retry_failure_does_not_leak() -> None:
    """Config steering replay failures should not leak steering content."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "use patch_file",
        "swallowed_original_content": "apply_diff steering",
        "swallowed_tool_calls": [
            {"function": {"name": "apply_diff", "arguments": "{}"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        RuntimeError("backend failure"),
    ]

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="apply diff")],
        stream=True,
    )

    result = await manager.process_backend_request(
        original_request, "session-config-retry-fail", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    assert backend_processor.process_backend_request.await_count == 2
    assert len(chunks) == 1
    assert chunks[0].content == ""
    metadata = getattr(chunks[0], "metadata", {})
    assert metadata.get("tool_call_swallowed") is True
    assert metadata.get("tool_call_reactor_retry_failed") is True
    assert "steering chunk" not in str(chunks[0].content)


@pytest.mark.asyncio
async def test_config_steering_non_streaming_replays_and_hides_steering() -> None:
    """Config steering (apply_diff) should replay history and hide steering output."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "use patch_file",
        "swallowed_original_content": "apply_diff steering",
        "swallowed_tool_calls": [
            {"function": {"name": "apply_diff", "arguments": "{}"}}
        ],
    }
    steering_processed = ProcessedResponse(
        content="steering-text", metadata=steering_metadata
    )
    corrected_processed = ProcessedResponse(content="patched", metadata={})
    response_processor.process_response = AsyncMock(
        side_effect=[steering_processed, corrected_processed]
    )
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="apply diff")],
        stream=False,
    )

    backend_processor.process_backend_request.side_effect = [
        ResponseEnvelope(content="raw tool call"),
        ResponseEnvelope(content="second response"),
    ]

    result = await manager.process_backend_request(
        original_request, "session-config-ns", _make_context()
    )

    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    proxy_notice = retry_args["request"].messages[-1].content
    assert "apply_diff" in proxy_notice
    assert "use patch_file" in proxy_notice
    assert isinstance(result, ResponseEnvelope)
    assert result.content == "patched"


@pytest.mark.asyncio
async def test_file_sandboxing_streaming_retry_failure_does_not_leak() -> None:
    """File sandboxing steering replay failures should not leak steering content."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "File operation blocked",
        "swallowed_original_content": "file sandbox steer",
        "swallowed_tool_calls": [
            {"function": {"name": "write_file", "arguments": "{}"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        RuntimeError("backend failure"),
    ]

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="write file")],
        stream=True,
    )

    result = await manager.process_backend_request(
        original_request, "session-file-sandbox", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    assert backend_processor.process_backend_request.await_count == 2
    assert len(chunks) == 1
    assert chunks[0].content == ""
    metadata = getattr(chunks[0], "metadata", {})
    assert metadata.get("tool_call_swallowed") is True
    assert metadata.get("tool_call_reactor_retry_failed") is True
    assert "steering chunk" not in str(chunks[0].content)


@pytest.mark.asyncio
async def test_dangerous_command_streaming_replays_and_hides_steering() -> None:
    """Dangerous command steering should replay history and hide steering chunk (streaming)."""
    backend_processor = AsyncMock()
    response_processor = MagicMock()
    response_processor.process_streaming_response = lambda stream, _session_id: stream
    manager = BackendRequestManager(
        backend_processor, response_processor, AngelFactoryStub()
    )

    steering_metadata = {
        "tool_call_swallowed": True,
        "steering_message": "dangerous command blocked",
        "swallowed_original_content": "steering content",
        "swallowed_tool_calls": [
            {"function": {"name": "execute_command", "arguments": "git reset --hard"}}
        ],
    }

    async def initial_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="steering chunk", metadata=steering_metadata)

    async def retry_stream() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content="safer command", metadata={})

    backend_processor.process_backend_request.side_effect = [
        StreamingResponseEnvelope(content=initial_stream()),
        StreamingResponseEnvelope(content=retry_stream()),
    ]

    original_request = ChatRequest(
        model="gemini",
        messages=[ChatMessage(role="user", content="do git reset --hard")],
        stream=True,
    )

    result = await manager.process_backend_request(
        original_request, "session-dangerous-stream", _make_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunks = [chunk async for chunk in result.content]
    assert backend_processor.process_backend_request.await_count == 2
    retry_args = backend_processor.process_backend_request.await_args_list[1].kwargs
    proxy_notice = retry_args["request"].messages[-1].content
    assert "git reset --hard" in proxy_notice
    assert "dangerous command blocked" in proxy_notice
    assert [chunk.content for chunk in chunks] == ["safer command"]
