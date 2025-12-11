import json
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.domain.responses import ProcessedResponse
from src.core.interfaces.command_processor_interface import ICommandProcessor
from src.core.interfaces.tool_call_reactor_interface import (
    IToolCallReactor,
    ToolCallContext,
    ToolCallReactionResult,
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
def tool_call_reactor_middleware(
    mock_tool_call_reactor: AsyncMock,
) -> ToolCallReactorMiddleware:
    """Fixture for a ToolCallReactorMiddleware instance."""
    return ToolCallReactorMiddleware(tool_call_reactor=mock_tool_call_reactor)


@pytest.mark.asyncio
async def test_middleware_bypassed_when_capability_is_true(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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
    mock_tool_call_reactor.process_tool_call.assert_not_called()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_false(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_middleware_processes_tool_call_when_capability_is_not_present(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_reactor_consumes_streaming_buffer_state(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    await tool_call_reactor_middleware.process(
        response=response, session_id="test_session", context=context, is_streaming=True
    )

    mock_tool_call_reactor.process_tool_call.assert_called_once()
    assert buffer_state.reactor_cursor == 1
    assert buffered_call.get("_already_processed") is True
    assert buffer_state.processed_signatures


@pytest.mark.asyncio
async def test_middleware_skips_already_processed_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Should not process the tool call
    mock_tool_call_reactor.process_tool_call.assert_not_called()
    # Should return the original response
    assert result is message


@pytest.mark.asyncio
async def test_middleware_processes_only_new_tool_calls(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Should process only the new tool call
    mock_tool_call_reactor.process_tool_call.assert_called_once()
    call_args = mock_tool_call_reactor.process_tool_call.call_args[0][0]
    assert call_args.tool_name == "readFile"


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware marks tool calls as processed after execution."""
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

    assert message.tool_calls is not None
    # Tool call should be marked as processed
    assert getattr(message.tool_calls[0], "_already_processed", False) is True


@pytest.mark.asyncio
async def test_middleware_marks_tool_calls_as_processed_even_on_error(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that the middleware marks tool calls as processed even when reactor raises an error."""
    # Make the reactor raise an error
    mock_tool_call_reactor.process_tool_call.side_effect = Exception("Test error")

    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Should not raise the exception
    result = await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    assert message.tool_calls is not None
    # Tool call should still be marked as processed to avoid retry loops
    assert getattr(message.tool_calls[0], "_already_processed", False) is True
    # Should return the original response
    assert result is message


@pytest.mark.asyncio
async def test_middleware_no_duplicate_reactor_executions(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Test that reactors are not executed multiple times for the same tool call."""
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command": "ls"}'),
        type="function",
    )

    message = ChatMessage(role="assistant", tool_calls=[tool_call])
    context = {"session_id": "test_session"}

    # Process the message twice
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )
    await tool_call_reactor_middleware.process(
        response=message, session_id="test_session", context=context
    )

    # Reactor should only be called once
    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_tool_calls_deduplicated_within_same_stream(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    await tool_call_reactor_middleware.process(
        response=first_call,
        session_id="test_session",
        context=context,
        is_streaming=True,
    )
    await tool_call_reactor_middleware.process(
        response=duplicate_call,
        session_id="test_session",
        context=context,
        is_streaming=True,
    )

    mock_tool_call_reactor.process_tool_call.assert_called_once()


@pytest.mark.asyncio
async def test_tool_calls_processed_again_on_new_stream(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Identical tool calls should be executed again when a new stream starts."""
    first_context = {"session_id": "test_session", "stream_id": "stream-1"}
    second_context = {"session_id": "test_session", "stream_id": "stream-2"}
    tool_call = ToolCall(
        id="call_xyz",
        function=FunctionCall(name="readFile", arguments='{"path": "file.txt"}'),
        type="function",
    )

    await tool_call_reactor_middleware.process(
        response=ChatMessage(
            role="assistant",
            tool_calls=[tool_call],
            metadata={"finish_reason": "tool_calls"},
        ),
        session_id="test_session",
        context=first_context,
        is_streaming=True,
    )

    await tool_call_reactor_middleware.process(
        response=ChatMessage(
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
        ),
        session_id="test_session",
        context=second_context,
        is_streaming=True,
    )

    assert mock_tool_call_reactor.process_tool_call.call_count == 2


@pytest.mark.asyncio
async def test_stream_state_clears_on_done_chunk(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
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

    assert mock_tool_call_reactor.process_tool_call.call_count == 2


@pytest.mark.asyncio
async def test_process_with_tool_calls_swallowed_empty_string(
    tool_call_reactor_middleware: ToolCallReactorMiddleware,
    mock_tool_call_reactor: AsyncMock,
) -> None:
    """Handlers should be able to swallow with an empty replacement payload."""

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

    swallow_result = ToolCallReactionResult(
        should_swallow=True,
        replacement_response="",
        metadata={"handler": "test_handler"},
    )

    mock_tool_call_reactor.process_tool_call.return_value = swallow_result

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
    assert result_data["choices"][0]["message"]["content"] == ""

    # Simulate streaming chunk scenario
    stream_chunk = ProcessedResponse(
        content="",
        metadata=result.metadata.copy(),
    )
    assert stream_chunk.metadata.get("tool_call_swallowed") is True
    assert stream_chunk.metadata.get("steering_message") == ""
    assert result.metadata["tool_call_swallowed"] is True
    assert result.metadata["tool_call_reactor"]["handler"] == "test_handler"
    assert result.metadata["role"] == "tool"
    assert result.metadata["tool_call_id"] == "call_124"
    assert result.metadata["steering_message"] == ""
    assert isinstance(result.metadata["swallowed_tool_calls"], list)


@pytest.mark.asyncio
async def test_middleware_repairs_multiline_json_and_records_telemetry() -> None:
    """Ensure multiline JSON arguments are parsed via relaxed mode and telemetry is recorded."""

    class ReactorDouble(IToolCallReactor):
        def __init__(self) -> None:
            self.mock_process_tool_call = AsyncMock()
            self.record_tool_argument_repair_outcome = MagicMock()

        async def register_handler(
            self, handler: Any
        ) -> None:  # pragma: no cover - test double
            return None

        async def unregister_handler(
            self, handler_name: str
        ) -> None:  # pragma: no cover - test double
            return None

        async def process_tool_call(
            self, context: ToolCallContext
        ) -> ToolCallReactionResult | None:
            result = await self.mock_process_tool_call(context)
            return cast(ToolCallReactionResult | None, result)

        def get_registered_handlers(self) -> list[str]:
            return []

    reactor = ReactorDouble()
    middleware = ToolCallReactorMiddleware(tool_call_reactor=reactor)

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

    assert reactor.mock_process_tool_call.called
    context_arg = reactor.mock_process_tool_call.call_args[0][0]
    assert isinstance(context_arg.tool_arguments, dict)
    assert "patch_content" in context_arg.tool_arguments
    reactor.record_tool_argument_repair_outcome.assert_called()
    outcome = reactor.record_tool_argument_repair_outcome.call_args[0][0]
    assert outcome in {"success", "recovered"}


def test_maybe_fix_droid_antigravity_path_handles_single_filename_string() -> None:
    """Single-segment relative paths should be normalized with leading forward slash."""
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        ".gitignore", "gemini-oauth-antigravity", "droid"
    )
    assert fixed == "/.gitignore"
    assert modified is True


def test_maybe_fix_droid_antigravity_path_handles_single_filename_dict() -> None:
    """Dictionary arguments should also be normalized for single-segment paths."""
    args: dict[str, str] = {"file_path": "foo.txt"}
    fixed, modified = ToolCallReactorMiddleware._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "droid"
    )
    assert isinstance(fixed, dict)
    assert fixed.get("file_path") == "/foo.txt"
    assert modified is True


def test_maybe_fix_droid_antigravity_path_handles_nested_path() -> None:
    """Nested relative paths should be normalized with forward slashes."""
    args: dict[str, str] = {"file_path": "tests/behavior/some_file.py"}
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "droid"
    )
    assert isinstance(fixed, dict)
    assert fixed.get("file_path") == "/tests/behavior/some_file.py"
    assert modified is True


def test_maybe_fix_droid_antigravity_path_not_modified_for_absolute_path() -> None:
    """Paths that are already absolute should not be modified."""
    # Test with forward slash prefix
    args: dict[str, str] = {"file_path": "/src/test.py"}
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "droid"
    )
    assert fixed is args  # Same reference, unchanged
    assert modified is False

    # Test with backslash prefix
    args2: dict[str, str] = {"file_path": "\\src\\test.py"}
    fixed2, modified2 = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args2, "gemini-oauth-antigravity", "droid"
    )
    assert fixed2 is args2  # Same reference, unchanged
    assert modified2 is False


def test_maybe_fix_droid_antigravity_path_not_modified_for_drive_letter() -> None:
    """Windows drive letter paths should not be modified."""
    args: dict[str, str] = {"file_path": "C:\\Users\\test\\file.py"}
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "droid"
    )
    assert fixed is args  # Same reference, unchanged
    assert modified is False


def test_maybe_fix_droid_antigravity_path_not_modified_for_non_droid_agent() -> None:
    """Non-droid agents should not have paths modified."""
    args: dict[str, str] = {"file_path": "relative/path.py"}
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "other-agent"
    )
    assert fixed is args  # Same reference, unchanged
    assert modified is False


def test_maybe_fix_droid_antigravity_path_handles_factory_cli_agent() -> None:
    """factory-cli user agent (Droid's actual User-Agent) should have paths fixed.

    Droid agent sends User-Agent: factory-cli/X.Y.Z, so the fix should trigger
    for both 'droid' and 'factory' in the agent name.

    This test verifies the fix for the production bug where Droid sent relative
    paths with User-Agent: factory-cli/0.35.0, but the proxy didn't fix them.
    """
    args: dict[str, str] = {
        "file_path": "tests/unit/services/test_steering_leak_protection.py"
    }
    fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
        args, "gemini-oauth-antigravity", "factory-cli/0.35.0"
    )
    assert isinstance(fixed, dict)
    assert (
        fixed.get("file_path")
        == "/tests/unit/services/test_steering_leak_protection.py"
    )
    assert modified is True


def test_maybe_fix_droid_antigravity_path_handles_factory_variations() -> None:
    """Various factory-related agent names should trigger the path fix."""
    factory_agents = [
        "factory-cli/0.35.0",
        "factory-cli/1.0.0",
        "Factory",
        "FACTORY",
        "MyFactoryAgent",
    ]
    for agent_name in factory_agents:
        args: dict[str, str] = {"file_path": "src/test.py"}
        fixed, modified = ToolCallReactorFeature._maybe_fix_droid_antigravity_path(
            args, "gemini-oauth-antigravity", agent_name
        )
        assert isinstance(fixed, dict), f"Should return dict for agent: {agent_name}"
        assert (
            fixed.get("file_path") == "/src/test.py"
        ), f"Should fix path for agent: {agent_name}"
        assert modified is True, f"Should mark as modified for agent: {agent_name}"


class TestVTCToolCallBypass:
    """Tests for VTC (Virtual Tool Calling) tool call bypass in ToolCallReactorFeature."""

    @pytest.fixture
    def feature(self, mock_tool_call_reactor: AsyncMock) -> ToolCallReactorFeature:
        """Create a ToolCallReactorFeature for testing."""
        return ToolCallReactorFeature(tool_call_reactor=mock_tool_call_reactor)

    @pytest.mark.asyncio
    async def test_vtc_tool_calls_bypassed_in_feature(
        self,
        feature: ToolCallReactorFeature,
        mock_tool_call_reactor: AsyncMock,
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

        # Process through the feature
        result = await feature.process_non_streaming(response, "test-session", context)

        # Should return unchanged response (bypassed)
        assert result is response

        # Reactor should NOT be called (VTC already processed these)
        mock_tool_call_reactor.process_tool_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_vtc_tool_calls_processed_normally(
        self,
        feature: ToolCallReactorFeature,
        mock_tool_call_reactor: AsyncMock,
    ) -> None:
        """Non-VTC tool calls should be processed through the reactor."""
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
        await feature.process_non_streaming(response, "test-session", context)

        # Reactor SHOULD be called (non-VTC flow)
        mock_tool_call_reactor.process_tool_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_vtc_tool_calls_bypassed_in_legacy_middleware(
        self,
        tool_call_reactor_middleware: ToolCallReactorMiddleware,
        mock_tool_call_reactor: AsyncMock,
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

        # Process through the middleware
        result = await tool_call_reactor_middleware.process(
            response, "test-session", context
        )

        # Should return unchanged response (bypassed)
        assert result is response

        # Reactor should NOT be called
        mock_tool_call_reactor.process_tool_call.assert_not_called()

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

        result = await feature.process_non_streaming(response, "test-session", context)

        # Metadata should be preserved
        assert result.metadata.get("vtc_tool_calls_swallowed") is True
        assert result.metadata.get("vtc_swallowed_count") == 2
