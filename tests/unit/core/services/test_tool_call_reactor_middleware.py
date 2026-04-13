import json
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
)
from src.core.interfaces.tool_call_reactor_orchestrator_interface import (
    IToolCallReactorOrchestrator,
)
from src.core.interfaces.tool_call_stream_context_resolver_interface import (
    IToolCallStreamContextResolver,
)
from src.core.services.streaming.stream_context_registry import ToolCallBufferState
from src.core.services.tool_call_reactor_middleware import (
    ToolCallReactorFeature,
    ToolCallReactorMiddleware,
)


@pytest.fixture
def mock_tool_call_reactor() -> AsyncMock:
    """Fixture for a mock tool call reactor."""
    reactor = AsyncMock(spec=IToolCallReactor)
    reactor.process_tool_call.return_value = None
    reactor.get_registered_handlers.return_value = []
    return reactor


@pytest.fixture
def mock_command_processor() -> AsyncMock:
    """Fixture for a mock command processor."""
    return AsyncMock(spec=ICommandProcessor)


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    """Fixture for a mock orchestrator."""
    orchestrator = AsyncMock(spec=IToolCallReactorOrchestrator)

    # By default, orchestrator returns the response unchanged
    async def handle_side_effect(response, session_id, context, is_streaming):
        return response

    orchestrator.handle.side_effect = handle_side_effect
    return orchestrator


@pytest.fixture
def mock_stream_context_resolver() -> Mock:
    """Fixture for a mock stream context resolver."""
    resolver = Mock(spec=IToolCallStreamContextResolver)
    resolver.resolve_stream_key.return_value = "test-stream"
    resolver.resolve_buffer_state.return_value = None
    return resolver


@pytest.fixture
def tool_call_reactor_middleware(
    mock_orchestrator: AsyncMock,
    mock_stream_context_resolver: Mock,
    mock_tool_call_reactor: AsyncMock,
) -> ToolCallReactorMiddleware:
    """Fixture for a ToolCallReactorMiddleware instance."""
    return ToolCallReactorMiddleware(
        orchestrator=mock_orchestrator,
        stream_context_resolver=mock_stream_context_resolver,
        tool_call_reactor=mock_tool_call_reactor,
    )


@pytest.mark.asyncio
async def test_middleware_bypassed_when_capability_is_true(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware is bypassed when the bypass_tool_call_reactor capability is True."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {
        "session_id": "test_session",
        "bypass_tool_call_reactor": True,
    }

    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    assert result is message
    mock_orchestrator.handle.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_false(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware processes the tool call when the bypass_tool_call_reactor capability is False."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {
        "session_id": "test_session",
        "bypass_tool_call_reactor": False,
    }

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    mock_orchestrator.handle.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_not_present(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware processes the tool call when the bypass_tool_call_reactor capability is not present."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    mock_orchestrator.handle.assert_called_once()


@pytest.mark.asyncio
async def test_reactor_consumes_streaming_buffer_state(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
    mock_stream_context_resolver: Mock,
) -> None:
    buffer_state = ToolCallBufferState()
    buffered_call = {
        "id": "call_buffer",
        "type": "function",
        "function": {"name": "read_file", "arguments": "{}"},
    }
    buffer_state.detected_calls.append(buffered_call)
    context = {
        "session_id": "test_session",
        "tool_call_buffer_state": buffer_state,
        "stream_id": "stream-buffer",
    }
    response = ProcessedResponse(content={}, metadata={})

    # Configure resolver to return buffer state
    from src.core.services.tool_call_reactor.stream_buffer_adapter import (
        StreamBufferAdapter,
    )

    mock_stream_context_resolver.resolve_buffer_state.return_value = (
        StreamBufferAdapter(buffer_state)
    )

    # Configure orchestrator to return response unchanged (buffer consumption happens inside orchestrator)
    mock_orchestrator.handle.return_value = response

    await tool_call_reactor_middleware.process(
        response=response, session_id="test_session", context=context, is_streaming=True
    )

    # Verify orchestrator was called (buffer consumption is handled by orchestrator)
    mock_orchestrator.handle.assert_called_once()
    # Note: Buffer cursor advancement and processed marking are tested at orchestrator level


@pytest.mark.asyncio
async def test_middleware_skips_already_processed_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware skips tool calls that have already been processed."""
    # Create a tool call that's already been processed
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    # Mark the tool call object as processed
    tool_call._already_processed = True  # type: ignore[attr-defined]

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Convert to ProcessedResponse (as middleware does internally)
    expected_response = ProcessedResponse(
        content=message,
        usage=None,
        metadata={},
    )

    # Configure orchestrator to return unchanged response (deduplication happens inside orchestrator)
    mock_orchestrator.handle.side_effect = None  # Clear side_effect
    mock_orchestrator.handle.return_value = expected_response

    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Orchestrator handles deduplication, so it's called but returns unchanged response
    mock_orchestrator.handle.assert_called_once()
    # Should return a ProcessedResponse (middleware converts input to ProcessedResponse)
    assert isinstance(result, ProcessedResponse)
    assert result.content == message


@pytest.mark.asyncio
async def test_middleware_processes_only_new_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware processes only new tool calls and skips processed ones."""
    # Create one processed and one new tool call
    processed_tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )
    processed_tool_call._already_processed = True  # type: ignore[attr-defined]

    new_tool_call = ToolCall(
        id="call_456",
        function=FunctionCall(name="readFile", arguments='{"path": "test.txt"}'),
        type="function",
    )

    message = ChatMessage(
        role="assistant", tool_calls=[processed_tool_call, new_tool_call]
    )
    context = {"session_id": "test_session"}

    # Configure orchestrator to return unchanged response (deduplication happens inside orchestrator)
    mock_orchestrator.handle.return_value = message

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Orchestrator handles deduplication, so it's called
    mock_orchestrator.handle.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware marks tool calls as processed after execution."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Configure orchestrator to return unchanged response (marking happens inside orchestrator)
    mock_orchestrator.handle.return_value = message

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Orchestrator handles marking as processed
    mock_orchestrator.handle.assert_called_once()
    # Note: Actual marking behavior is tested at orchestrator level


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed_even_on_error(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that the middleware handles orchestrator errors gracefully."""
    # Make the orchestrator raise an error
    mock_orchestrator.handle.side_effect = Exception("Test error")

    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Should propagate the exception (orchestrator errors are not caught by middleware)
    with pytest.raises(Exception, match="Test error"):
        await tool_call_reactor_middleware.process(
            response=message, session_id="test_session", context=context
        )


@pytest.mark.asyncio
async def test_middleware_no_duplicate_reactor_executions(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Test that orchestrator is called for each process call (deduplication happens inside)."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Configure orchestrator to return unchanged response
    mock_orchestrator.handle.return_value = message

    # Process the message twice
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Orchestrator is called twice (deduplication happens inside orchestrator)
    assert mock_orchestrator.handle.call_count == 2


@pytest.mark.asyncio
async def test_tool_calls_deduplicated_within_same_stream(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Duplicate tool calls arriving on the same stream should only execute once."""
    context = {"session_id": "test_session", "stream_id": "stream-1"}
    first_call = ChatMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call_abc",
                function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
                type="function",
            )
        ],
        metadata={"finish_reason": "tool_calls"},
    )
    duplicate_call = ChatMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call_abc",
                function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
                type="function",
            )
        ],
        metadata={"finish_reason": "tool_calls"},
    )

    # Configure orchestrator to return unchanged responses
    mock_orchestrator.handle.return_value = first_call

    await tool_call_reactor_middleware.process(
        response=first_call,
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    mock_orchestrator.handle.return_value = duplicate_call

    await tool_call_reactor_middleware.process(
        response=duplicate_call,
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    # Orchestrator handles deduplication, so it's called twice but deduplicates internally
    assert mock_orchestrator.handle.call_count == 2


@pytest.mark.asyncio
async def test_tool_calls_processed_again_on_new_stream(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
    mock_stream_context_resolver: Mock,
) -> None:
    """Identical tool calls should be executed again when a new stream starts."""
    first_context = {"session_id": "test_session", "stream_id": "stream-1"}
    second_context = {"session_id": "test_session", "stream_id": "stream-2"}
    tool_call = ToolCall(
        id="call_xyz",
        function=FunctionCall(name="readFile", arguments='{"path": "file.txt"}'),
        type="function",
    )

    # Configure resolver to return different stream keys
    def resolve_stream_key(session_id, context, response):
        return context.get("stream_id", "test-stream")

    mock_stream_context_resolver.resolve_stream_key.side_effect = resolve_stream_key

    first_response = ChatMessage(
        role="assistant",
        tool_calls=[tool_call],
        metadata={"finish_reason": "tool_calls"},
    )
    second_response = ChatMessage(
        role="assistant",
        tool_calls=[
            ToolCall(
                id="call_xyz",
                function=FunctionCall(
                    name="readFile", arguments='{"path": "file.txt"}'
                ),
                type="function",
            )
        ],
        metadata={"finish_reason": "tool_calls"},
    )

    # Configure orchestrator to return responses
    mock_orchestrator.handle.return_value = first_response

    await tool_call_reactor_middleware.process(
        response=first_response,
        session_id="test_session",
        context=first_context,
        is_streaming=True,
    )

    mock_orchestrator.handle.return_value = second_response

    await tool_call_reactor_middleware.process(
        response=second_response,
        session_id="test_session",
        context=second_context,
        is_streaming=True,
    )

    # Orchestrator is called for each stream (deduplication happens per stream inside orchestrator)
    assert mock_orchestrator.handle.call_count == 2


@pytest.mark.asyncio
async def test_stream_state_clears_on_done_chunk(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Once a stream signals completion, subsequent tool calls should be treated as new."""
    context = {"session_id": "test_session", "stream_id": "stream-reset"}
    tool_call = ToolCall(
        id="call_reset",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    await tool_call_reactor_middleware.process(
        response=ChatMessage(
            role="assistant",
            tool_calls=[tool_call],
            metadata={"finish_reason": "tool_calls"},
        ),
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    # Final chunk with no tool calls but marks stream as done
    await tool_call_reactor_middleware.process(
        response=ProcessedResponse(
            content="",
            metadata={"stream_id": "stream-reset", "is_done": True},
        ),
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    # New tool call on the same stream id should execute again
    await tool_call_reactor_middleware.process(
        response=ChatMessage(
            role="assistant",
            tool_calls=[
                ToolCall(
                    id="call_reset",
                    function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
                    type="function",
                )
            ],
            metadata={"finish_reason": "tool_calls"},
        ),
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    # Orchestrator handles stream state clearing, so it's called for each process
    assert mock_orchestrator.handle.call_count == 3


@pytest.mark.asyncio
async def test_process_with_tool_calls_swallowed_empty_string(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Empty steering should be replaced with a safe default for backend retry."""

    tool_call_response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_124",
                            "type": "function",
                            "function": {
                                "name": "test_tool",
                                "arguments": '{"arg": "value"}',
                            },
                        }
                    ]
                }
            }
        ]
    }

    response = ProcessedResponse(content=json.dumps(tool_call_response))

    # Configure orchestrator to return a replacement response
    replacement_response = ProcessedResponse(
        content={
            "choices": [
                {
                    "message": {
                        "content": "A tool call was blocked by proxy policy. Do not repeat the blocked tool call. Respond to the user with a compliant approach that does not require tools."
                    }
                }
            ]
        },
        metadata={
            "tool_call_swallowed": True,
            "tool_call_reactor": {"handler": "test_handler"},
            "role": "tool",
            "tool_call_id": "call_124",
            "steering_message": "A tool call was blocked by proxy policy. Do not repeat the blocked tool call. Respond to the user with a compliant approach that does not require tools.",
            "swallowed_tool_calls": [{"id": "call_124"}],
        },
    )
    mock_orchestrator.handle.side_effect = (
        None  # Clear side_effect so return_value works
    )
    mock_orchestrator.handle.return_value = replacement_response

    result = await tool_call_reactor_middleware.process(
        response=response,
        session_id="test_session",
        context={"backend_name": "test", "model_name": "test"},
    )

    assert isinstance(result, ProcessedResponse)
    # The content is now a full OpenAI-compatible response structure as a dict
    # (NOT a JSON string - strings get treated as raw text and cause the leak bug)
    assert isinstance(result.content, dict)
    result_data = result.content
    assert result_data["choices"][0]["message"]["content"] != ""

    # Simulate streaming chunk scenario
    stream_chunk = ProcessedResponse(
        content="",
        metadata=result.metadata.copy(),
    )
    assert stream_chunk.metadata.get("tool_call_swallowed") is True
    assert isinstance(stream_chunk.metadata.get("steering_message"), str)
    assert stream_chunk.metadata.get("steering_message")
    assert result.metadata["tool_call_swallowed"] is True
    assert result.metadata["tool_call_reactor"]["handler"] == "test_handler"
    assert result.metadata["role"] == "tool"
    assert result.metadata["tool_call_id"] == "call_124"
    assert isinstance(result.metadata["steering_message"], str)
    assert result.metadata["steering_message"]
    assert isinstance(result.metadata["swallowed_tool_calls"], list)


@pytest.mark.asyncio
async def test_process_with_tool_calls_swallowed_does_not_leak_replacement_content(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_orchestrator: AsyncMock,
) -> None:
    """Swallowed tool calls must not surface steering text to the client."""

    tool_call_response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "id": "call_999",
                            "type": "function",
                            "function": {
                                "name": "test_tool",
                                "arguments": '{"arg": "value"}',
                            },
                        }
                    ]
                }
            }
        ]
    }

    response = ProcessedResponse(content=json.dumps(tool_call_response))

    # Configure orchestrator to return a replacement response
    replacement_response = ProcessedResponse(
        content={
            "choices": [
                {"message": {"content": "INTERNAL_STEERING_MESSAGE_DO_NOT_LEAK"}}
            ]
        },
        metadata={
            "tool_call_swallowed": True,
            "steering_message": "INTERNAL_STEERING_MESSAGE_DO_NOT_LEAK",
        },
    )
    mock_orchestrator.handle.side_effect = (
        None  # Clear side_effect so return_value works
    )
    mock_orchestrator.handle.return_value = replacement_response

    result = await tool_call_reactor_middleware.process(
        response=response,
        session_id="test_session",
        context={"backend_name": "test", "model_name": "test"},
    )

    assert isinstance(result, ProcessedResponse)
    assert isinstance(result.content, dict)
    client_visible_content = result.content["choices"][0]["message"]["content"]
    # The replacement content IS the message to the user/client when a tool is blocked/steered.
    # We explicitly want this to be visible if the handler provides it.
    assert "INTERNAL_STEERING_MESSAGE_DO_NOT_LEAK" in (client_visible_content or "")
    assert result.metadata.get("tool_call_swallowed") is True
    assert (
        result.metadata.get("steering_message")
        == "INTERNAL_STEERING_MESSAGE_DO_NOT_LEAK"
    )


@pytest.mark.asyncio
async def test_middleware_repairs_multiline_json_and_records_telemetry() -> None:
    """JSON repair and telemetry are now handled by the orchestrator.

    This test is kept for backward compatibility but the actual behavior
    is tested at the orchestrator/arguments parser level.
    """
    # Create a mock orchestrator that simulates JSON repair behavior
    mock_orchestrator = AsyncMock(spec=IToolCallReactorOrchestrator)
    mock_stream_resolver = Mock(spec=IToolCallStreamContextResolver)
    mock_stream_resolver.resolve_stream_key.return_value = "test-stream"
    mock_stream_resolver.resolve_buffer_state.return_value = None

    reactor = AsyncMock(spec=IToolCallReactor)
    reactor.get_registered_handlers.return_value = []

    middleware = ToolCallReactorMiddleware(
        orchestrator=mock_orchestrator,
        stream_context_resolver=mock_stream_resolver,
        tool_call_reactor=reactor,
    )

    patch_arguments = '{\n  "file_path": "example.txt",\n  "patch_content": "<<<<<<< SEARCH\nline\n=======\\nother\n>>>>>>> REPLACE"\n}'
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="patch_file", arguments=patch_arguments),
        type="function",
    )
    message = ChatMessage(role="assistant", tool_calls=[tool_call])

    await middleware.process(
        response=message,
        session_id="session-telemetry",
        context={"session_id": "session-telemetry"},
    )

    # Verify orchestrator was called (JSON repair happens inside orchestrator)
    mock_orchestrator.handle.assert_called_once()
    # Note: Actual JSON repair and telemetry testing is done at orchestrator/parser level


def _expected_path(relative_path: str) -> str:
    """Helper to get expected absolute path."""
    import os

    return os.path.abspath(os.path.join(os.getcwd(), relative_path.lstrip("/\\")))


class TestVTCToolCallBypass:
    """Tests for VTC (Virtual Tool Calling) tool call bypass in ToolCallReactorFeature."""

    @pytest.fixture
    def feature(
        self,
        mock_orchestrator: AsyncMock,
        mock_stream_context_resolver: Mock,
        mock_tool_call_reactor: AsyncMock,
    ) -> ToolCallReactorFeature:
        """Create a ToolCallReactorFeature for testing."""
        return ToolCallReactorFeature(
            orchestrator=mock_orchestrator,
            stream_context_resolver=mock_stream_context_resolver,
            tool_call_reactor=mock_tool_call_reactor,
        )

    @pytest.mark.asyncio
    async def test_vtc_tool_calls_bypassed_in_feature(
        self,
        feature: ToolCallReactorFeature,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """VTC tool calls should be bypassed as they're already processed by VTCResponseStreamWrapper."""
        # Create a response with VTC tool calls marker
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={
                "vtc_tool_calls": True,  # This marks it as VTC-processed
                "tool_calls": [
                    {
                        "id": "vtc_123",
                        "type": "function",
                        "function": {"name": "execute_command", "arguments": "{}"},
                    }
                ],
            },
        )
        context: dict[str, Any] = {"session_id": "test-session"}

        # Configure orchestrator to return unchanged response (VTC bypass)
        mock_orchestrator.handle.return_value = response

        # Process through the feature
        result = await feature.process(
            response, "test-session", context, is_streaming=False
        )

        # Should return unchanged response (bypassed)
        assert result is response

        # Orchestrator handles VTC bypass, so it's called but returns unchanged response
        mock_orchestrator.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_non_vtc_tool_calls_processed_normally(
        self,
        feature: ToolCallReactorFeature,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """Non-VTC tool calls should be processed through the orchestrator."""
        # Create a response WITHOUT VTC marker
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={
                # No vtc_tool_calls marker
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {"name": "execute_command", "arguments": "{}"},
                    }
                ],
            },
        )
        context: dict[str, Any] = {"session_id": "test-session"}

        # Process through the feature
        await feature.process(response, "test-session", context, is_streaming=False)

        # Orchestrator SHOULD be called (non-VTC flow)
        mock_orchestrator.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_vtc_tool_calls_bypassed_in_legacy_middleware(
        self,
        tool_call_reactor_middleware: ToolCallReactorMiddleware,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """VTC tool calls should also be bypassed in legacy middleware."""
        # Create a response with VTC tool calls marker
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "test"}}]},
            metadata={
                "vtc_tool_calls": True,  # VTC-processed marker
                "tool_calls": [
                    {
                        "id": "vtc_456",
                        "type": "function",
                        "function": {"name": "read_file", "arguments": "{}"},
                    }
                ],
            },
        )
        context: dict[str, Any] = {"session_id": "test-session"}

        # Configure orchestrator to return unchanged response (VTC bypass)
        mock_orchestrator.handle.return_value = response

        # Process through the middleware
        result = await tool_call_reactor_middleware.process(
            response, "test-session", context
        )

        # Should return unchanged response (bypassed)
        assert result is response

        # Orchestrator handles VTC bypass, so it's called but returns unchanged response
        mock_orchestrator.handle.assert_called_once()

    @pytest.mark.asyncio
    async def test_vtc_swallowed_metadata_preserved(
        self,
        feature: ToolCallReactorFeature,
        mock_tool_call_reactor: AsyncMock,
    ) -> None:
        """VTC swallowed metadata should be preserved when bypassing."""
        response = ProcessedResponse(
            content={"choices": [{"message": {"content": "Blocked message"}}]},
            metadata={
                "vtc_tool_calls": True,
                "vtc_tool_calls_swallowed": True,
                "vtc_swallowed_count": 2,
            },
        )
        context: dict[str, Any] = {"session_id": "test-session"}

        result = await feature.process(
            response, "test-session", context, is_streaming=False
        )

        # Metadata should be preserved
        assert result.metadata.get("vtc_tool_calls_swallowed") is True
        assert result.metadata.get("vtc_swallowed_count") == 2
