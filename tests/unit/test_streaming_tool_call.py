from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.app.controllers.chat_controller import ChatController
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.processed_result import ProcessedResult
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.response_processor_interface import (
    IResponseMiddleware,
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.interfaces.tool_call_repair_service_interface import (
    IToolCallRepairService,
)
from src.core.ports.streaming_contracts import StreamingContent
from src.core.services.request_processor_service import RequestProcessor
from src.core.services.streaming.middleware_application_processor import (
    MiddlewareApplicationProcessor,
)
from src.core.services.streaming.stream_normalizer import StreamNormalizer
from src.core.services.streaming.tool_call_repair_processor import (
    ToolCallRepairProcessor,
)
from src.core.services.tool_call_repair_service import ToolCallRepairService


async def _create_streaming_response(content: list[str]) -> StreamingResponseEnvelope:
    """Creates a streaming response envelope from a list of content strings."""

    async def stream_generator() -> AsyncGenerator[ProcessedResponse, None]:
        for item in content:
            yield ProcessedResponse(content=item)

    return StreamingResponseEnvelope(
        content=stream_generator(),
        media_type="text/event-stream",
        headers={},
        cancel_callback=None,
    )


@pytest.mark.asyncio
async def test_streaming_tool_call_in_first_chunk():
    """
    Tests that a tool call in the first chunk of a streaming response is correctly handled.
    """
    print("DEBUG: Test started")
    # 1. Mock a backend that returns a streaming response with a tool call in the first chunk
    mock_backend_processor = MagicMock(spec=IBackendProcessor)

    # Create the streaming response
    async def get_streaming_response():
        return await _create_streaming_response(
            [
                'data: {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1761032732, "model": "code-assist-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": null, "tool_calls": [{"index": 0, "id": "call_123", "function": {"arguments": "{"file_path": "README.md"}", "name": "read_file"}, "type": "function"}]}}]}',
                'data: {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 1761032732, "model": "code-assist-model", "choices": [{"index": 0, "delta": {"role": "assistant", "content": " some content"}}]}',
            ]
        )

    mock_backend_processor.process_backend_request = AsyncMock(
        return_value=await get_streaming_response()
    )

    # 2. Setup the necessary services
    mock_command_processor = MagicMock()
    # Simulate the agent executing a shell tool and returning a rich result.
    rich_output = "exit code: 0\nREADME contents..."
    fake_tool_message = ChatMessage(
        role="tool",
        content=rich_output,
        tool_call_id="call_123",
        name="shell",
    )
    mock_command_processor.process_messages = AsyncMock(
        return_value=ProcessedResult(
            command_executed=True,
            modified_messages=[
                ChatMessage(role="user", content="!/run ls"),
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }
                    ],
                ),
            ],
            command_results=[fake_tool_message],
        )
    )
    mock_session_manager = MagicMock()
    mock_session_manager.resolve_session_id = AsyncMock(return_value="test_session")
    mock_session_manager.get_session = AsyncMock(return_value=MagicMock())
    mock_session_manager.update_session_agent = AsyncMock(return_value=MagicMock())
    mock_session_manager.update_session_history = AsyncMock()
    mock_response_manager = MagicMock()
    MagicMock(spec=IResponseProcessor)

    # Create a real response processor that processes the stream
    from src.core.services.response_parser_service import ResponseParser
    from src.core.services.response_processor_service import ResponseProcessor
    from src.core.services.streaming.content_accumulation_processor import (
        ContentAccumulationProcessor,
    )
    from src.core.services.streaming.stream_normalizer import StreamNormalizer

    response_parser = ResponseParser()
    stream_normalizer = StreamNormalizer([ContentAccumulationProcessor()])
    real_response_processor = ResponseProcessor(
        response_parser=response_parser,
        stream_normalizer=stream_normalizer,
    )

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    backend_request_manager = create_backend_request_manager(
        backend_processor=mock_backend_processor,
        response_processor=real_response_processor,
    )

    from src.core.services import tool_text_renderer

    tool_text_renderer.render_tool_call = MagicMock(
        return_value="<read_file><path>README.md</path></read_file>"
    )

    # Create required mocks for refactored RequestProcessor
    from src.core.interfaces.request_processor_internal import (
        IBackendPreparer,
        ICommandHandler,
        IRequestSideEffects,
        IRequestTransformPipeline,
        ISessionEnricher,
    )

    session_enricher = AsyncMock(spec=ISessionEnricher)
    session_enricher.enrich.return_value = (
        MagicMock(),
        ChatRequest(
            model="test_model", messages=[ChatMessage(role="user", content="test")]
        ),
    )

    request_side_effects = AsyncMock(spec=IRequestSideEffects)
    request_side_effects.apply.return_value = ChatRequest(
        model="test_model", messages=[ChatMessage(role="user", content="test")]
    )

    command_handler = AsyncMock(spec=ICommandHandler)

    async def handle_command(context, session, session_id, request_data):
        # Return the same result as mock_command_processor to maintain the tool message
        # But strip the command prefix from user messages (simulating real command processing)
        return ProcessedResult(
            modified_messages=[
                ChatMessage(role="user", content="run ls"),  # Command prefix stripped
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {"name": "shell", "arguments": "{}"},
                        }
                    ],
                ),
            ],
            command_executed=True,
            command_results=[fake_tool_message],
        )

    command_handler.handle.side_effect = handle_command

    backend_preparer = AsyncMock(spec=IBackendPreparer)

    # backend_preparer should build the request from command_result
    async def prepare_backend_request(
        context, session_id, request_data, command_result
    ):
        # Use modified messages from command result if available
        messages = (
            command_result.modified_messages
            if command_result.modified_messages
            else request_data.messages
        )
        # Append command results (tool messages) if present
        if command_result.command_results:
            messages = list(messages) + command_result.command_results
        print(f"DEBUG: backend_preparer creating request with {len(messages)} messages")
        return ChatRequest(
            model=request_data.model,
            messages=messages,
            stream=getattr(request_data, "stream", None),
        )

    backend_preparer.prepare.side_effect = prepare_backend_request

    transform_pipeline = AsyncMock(spec=IRequestTransformPipeline)
    # transform_pipeline should pass through the request preserving messages
    transform_pipeline.transform.side_effect = lambda ctx, sess, sid, req: req

    # Use real BackendExecutor that calls through to backend_request_manager
    from src.core.interfaces.session_manager_interface import ISessionManager
    from src.core.services.backend_executor import BackendExecutor

    mock_session_manager_for_executor = AsyncMock(spec=ISessionManager)
    mock_session_manager_for_executor.update_session_history = AsyncMock()
    backend_executor = BackendExecutor(
        backend_request_manager=backend_request_manager,
        session_manager=mock_session_manager_for_executor,
        replacement_service=None,
    )

    request_processor = RequestProcessor(
        command_processor=mock_command_processor,
        session_manager=mock_session_manager,
        backend_request_manager=backend_request_manager,
        response_manager=mock_response_manager,
        session_enricher=session_enricher,
        request_side_effects=request_side_effects,
        command_handler=command_handler,
        backend_preparer=backend_preparer,
        transform_pipeline=transform_pipeline,
        backend_executor=backend_executor,
    )

    chat_controller = ChatController(request_processor=request_processor)

    # 3. Call the ChatController with a request that will trigger the streaming response
    chat_request = ChatRequest(
        model="test_model",
        messages=[ChatMessage(role="user", content="test")],
        stream=True,
    )
    request = MagicMock()
    response = await chat_controller.handle_chat_completion(
        request=request, request_data=chat_request
    )

    # 4. Assert that the response received by the client contains the tool call
    response_content = b""
    async for chunk in response.body_iterator:
        response_content += chunk

    assert b"tool_calls" in response_content
    assert b"read_file" in response_content

    # Verify that each backend request only contains the latest tool output once.
    # Check that the backend was called via the mock
    assert (
        mock_backend_processor.process_backend_request.called
    ), "Backend was not called"

    # Get the request that was passed to the backend
    call_args = mock_backend_processor.process_backend_request.call_args
    last_request = call_args.kwargs.get("request") or call_args.args[0]

    tool_messages = [msg for msg in last_request.messages if msg.role == "tool"]
    assert len(tool_messages) == 1, f"Expected 1 tool message, got {len(tool_messages)}"
    assert rich_output in (tool_messages[0].content or "")

    stripped_user_commands = [
        msg.content
        for msg in last_request.messages
        if msg.role == "user" and isinstance(msg.content, str)
    ]
    assert all("!/" not in (content or "") for content in stripped_user_commands)


class _RecordingStreamingProcessor(IResponseProcessor):
    """Minimal processor that runs stream normalization with tool-call repair."""

    def __init__(self) -> None:
        self.tool_call_seen = False

        class _RecorderMiddleware(IResponseMiddleware):
            def __init__(self, outer: _RecordingStreamingProcessor) -> None:
                super().__init__(priority=0)
                self.outer = outer

            async def process(
                self,
                response: Any,
                session_id: str,
                context: dict[str, Any],
                is_streaming: bool = False,
                stop_event: Any = None,
            ) -> Any:
                tool_calls = getattr(response, "metadata", {}).get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    self.outer.tool_call_seen = True
                return response

        repair_service: IToolCallRepairService = cast(
            IToolCallRepairService, ToolCallRepairService()
        )
        repair_processor = ToolCallRepairProcessor(repair_service)
        recorder = _RecorderMiddleware(self)
        middleware_processor = MiddlewareApplicationProcessor(middleware=[recorder])
        self._normalizer = StreamNormalizer([repair_processor, middleware_processor])

    async def process_response(
        self,
        response: Any,
        session_id: str,
        context: dict[str, Any] | None = None,
    ) -> ProcessedResponse:
        return ProcessedResponse(content=response, metadata={})

    def process_streaming_response(
        self,
        response_iterator: AsyncIterator[Any],
        session_id: str,
        **kwargs: Any,
    ) -> AsyncIterator[ProcessedResponse]:
        async def _generator() -> AsyncIterator[ProcessedResponse]:
            async for chunk in self._normalizer.process_stream(
                response_iterator, output_format="objects"
            ):
                assert isinstance(chunk, StreamingContent)
                yield ProcessedResponse(
                    content=chunk.content,
                    usage=chunk.usage,
                    metadata=chunk.metadata,
                )

        return _generator()

    async def register_middleware(
        self, middleware: Any, priority: int = 0
    ) -> None:  # pragma: no cover - not needed for these tests
        return None


def _make_request_context() -> RequestContext:
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
async def test_streaming_xml_content_passes_through_unchanged() -> None:
    """XML content in streaming output passes through unchanged.

    Virtual tool call detection has been disabled. XML content should
    pass through to the client for client-side parsing.
    """

    from tests.helpers.backend_request_manager_fixtures import (
        create_backend_request_manager,
    )

    response_processor = _RecordingStreamingProcessor()
    backend_processor = AsyncMock()
    manager = create_backend_request_manager(
        backend_processor=backend_processor,
        response_processor=response_processor,
    )

    original_request = ChatRequest(
        model="zenmux:kuaishou/kat-coder-pro-v1",
        messages=[ChatMessage(role="user", content="fix it")],
        stream=True,
    )

    xml_content = (
        "Here is the change:\n"
        "<patch_file>\n"
        "<path>C:/Users/Mateusz/source/repos/llm-interactive-proxy/pyproject.toml</path>\n"
        "<patch_content>abc</patch_content>\n"
        "</patch_file>\n"
    )

    async def source_stream() -> AsyncGenerator[ProcessedResponse, None]:
        yield ProcessedResponse(content=xml_content)
        yield ProcessedResponse(content="", metadata={"is_done": True})

    envelope = StreamingResponseEnvelope(content=source_stream())
    backend_processor.process_backend_request.return_value = envelope

    result = await manager.process_backend_request(
        original_request, "sess-123", _make_request_context()
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None

    chunks = [chunk async for chunk in result.content]
    # XML content should pass through unchanged (no tool_calls added)
    all_content = "".join(
        chunk.content for chunk in chunks if isinstance(chunk.content, str)
    )
    assert "<patch_file>" in all_content, "XML content should pass through unchanged"
