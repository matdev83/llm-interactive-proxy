"""Regression test for premature session termination with tool calls.

This test reproduces the bug where sessions were prematurely marked as completed
when finish_reason="tool_calls" was encountered, preventing the client from
sending tool results back for subsequent turns.

Bug discovered: 2026-02-27
Fixed in: src/core/services/streaming/end_of_session_stream_processor.py
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from src.core.config.models.end_of_session import EndOfSessionConfig
from src.core.database.repositories.usage_repository import SessionMetricsRepository
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.services.end_of_session_service import EndOfSessionService
from src.core.services.event_bus import EventBus
from src.core.services.streaming.end_of_session_stream_processor import (
    EndOfSessionStreamProcessor,
)


@pytest.fixture
def event_bus() -> EventBus:
    """Create a real EventBus instance."""
    return EventBus()


@pytest.fixture
def mock_session_repo() -> AsyncMock:
    """Create a mock session metrics repository."""
    repo = AsyncMock(spec=SessionMetricsRepository)
    repo.claim_eos_emission = AsyncMock(return_value=True)
    repo.has_ended = AsyncMock(return_value=False)
    repo.get_by_id = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def eos_config() -> EndOfSessionConfig:
    """Create EoS configuration."""
    return EndOfSessionConfig(
        enabled=True,
        emit_events=True,
        detect_stream_signals=True,
        detect_tool_completion=True,
        dispatch_timeout_seconds=5.0,
    )


@pytest.fixture
def eos_service(
    event_bus: EventBus,
    eos_config: EndOfSessionConfig,
    mock_session_repo: AsyncMock,
) -> EndOfSessionService:
    """Create EndOfSessionService instance."""
    return EndOfSessionService(
        event_bus=event_bus,
        config=eos_config,
        session_repository=mock_session_repo,
    )


@pytest.fixture
def stream_processor(
    eos_service: EndOfSessionService, eos_config: EndOfSessionConfig
) -> EndOfSessionStreamProcessor:
    """Create EndOfSessionStreamProcessor instance."""
    return EndOfSessionStreamProcessor(
        end_of_session_service=eos_service,
        config=eos_config,
    )


@pytest.mark.asyncio
async def test_tool_calls_response_does_not_terminate_session(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test that finish_reason=tool_calls does NOT mark session as completed.

    This is the main regression test for the bug where sessions were prematurely
    terminated when the LLM returned tool calls.

    Scenario:
    1. LLM returns response with finish_reason="tool_calls" and is_done=True
    2. Session should NOT be marked as completed
    3. Client should be able to send tool results back
    """
    session_id = "tool-call-session-123"

    # Simulate a streaming chunk with tool calls
    content = StreamingContent(
        content={
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "bash",
                                    "arguments": '{"command": "ls -la"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        },
        metadata={
            "session_id": session_id,
            "finish_reason": "tool_calls",
            "protocol": "openai",
            "backend_name": "kimi-code",
        },
        is_done=True,  # SSE stream is done, but session should continue
    )

    # Process the content
    result = await stream_processor.process(content)

    # Verify content is unchanged (pass-through)
    assert result is content

    # CRITICAL: Verify that EoS signal was NOT recorded
    mock_session_repo.claim_eos_emission.assert_not_awaited()

    # Session should still be able to accept follow-up requests
    assert not await mock_session_repo.has_ended(session_id)


@pytest.mark.asyncio
async def test_multi_turn_tool_call_session_flow(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test complete multi-turn flow with tool calls.

    Simulates a realistic agent conversation:
    1. Turn 1: LLM requests tool execution → session NOT terminated
    2. Turn 2: User provides tool results, LLM requests more tools → session NOT terminated
    3. Turn 3: LLM provides final answer with finish_reason="stop" → session IS terminated
    """
    session_id = "multi-turn-session-456"

    # Turn 1: First tool call request
    turn1_content = StreamingContent(
        content={"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        metadata={"session_id": session_id, "finish_reason": "tool_calls"},
        is_done=True,
    )

    result1 = await stream_processor.process(turn1_content)
    assert result1 is turn1_content
    mock_session_repo.claim_eos_emission.assert_not_awaited()

    # Turn 2: Another tool call request
    turn2_content = StreamingContent(
        content={"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        metadata={"session_id": session_id, "finish_reason": "tool_calls"},
        is_done=True,
    )

    result2 = await stream_processor.process(turn2_content)
    assert result2 is turn2_content
    mock_session_repo.claim_eos_emission.assert_not_awaited()

    # Turn 3: Final completion with stop
    turn3_content = StreamingContent(
        content={"choices": [{"delta": {"content": "Done!"}, "finish_reason": "stop"}]},
        metadata={"session_id": session_id, "finish_reason": "stop"},
        is_done=True,
    )

    result3 = await stream_processor.process(turn3_content)
    assert result3 is turn3_content

    # NOW the session should be terminated
    mock_session_repo.claim_eos_emission.assert_awaited_once()
    call_kwargs = mock_session_repo.claim_eos_emission.call_args.kwargs
    assert call_kwargs["session_id"] == session_id


@pytest.mark.asyncio
async def test_tool_calls_in_content_dict_does_not_terminate_session(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test that finish_reason in content.content dict also prevents EoS.

    Some backends may place finish_reason in the content dict rather than
    (or in addition to) metadata.
    """
    session_id = "content-dict-session-789"

    content = StreamingContent(
        content={
            "id": "chatcmpl-test",
            "finish_reason": "tool_calls",  # In content dict
            "choices": [{"delta": {}, "finish_reason": "tool_calls"}],
        },
        metadata={"session_id": session_id},
        is_done=True,
    )

    result = await stream_processor.process(content)

    assert result is content
    mock_session_repo.claim_eos_emission.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_finish_reasons_still_terminate_session(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test that non-tool_calls finish_reasons still terminate sessions correctly.

    Ensures our fix doesn't break normal session termination.
    """
    session_id_base = "termination-test"

    # Test each terminal finish_reason
    terminal_reasons = ["stop", "length", "content_filter", "error"]

    for idx, finish_reason in enumerate(terminal_reasons):
        session_id = f"{session_id_base}-{idx}"

        content = StreamingContent(
            content={"choices": [{"delta": {}, "finish_reason": finish_reason}]},
            metadata={"session_id": session_id, "finish_reason": finish_reason},
            is_done=True,
        )

        await stream_processor.process(content)

        # Each should have triggered EoS emission
        assert mock_session_repo.claim_eos_emission.call_count == idx + 1


@pytest.mark.asyncio
async def test_is_done_without_finish_reason_still_terminates(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test that is_done=True without finish_reason still terminates session.

    This ensures we don't break sessions that complete without explicit finish_reason.
    """
    session_id = "no-finish-reason-session"

    content = StreamingContent(
        content="Final response",
        metadata={"session_id": session_id},
        is_done=True,  # No finish_reason
    )

    await stream_processor.process(content)

    mock_session_repo.claim_eos_emission.assert_awaited_once()


@pytest.mark.asyncio
async def test_tool_calls_with_explicit_stop_still_terminates(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Test edge case: chunk has both tool_calls and stop finish_reason.

    In this case, finish_reason takes precedence. If it's "stop", session should end.
    This shouldn't happen in practice, but we handle it gracefully.
    """
    session_id = "mixed-signals-session"

    content = StreamingContent(
        content={
            "choices": [
                {
                    "delta": {"tool_calls": [{"id": "call_1"}]},
                    "finish_reason": "stop",  # stop wins over tool_calls presence
                }
            ]
        },
        metadata={
            "session_id": session_id,
            "finish_reason": "stop",
            "tool_calls": [{"id": "call_1"}],
        },
        is_done=True,
    )

    await stream_processor.process(content)

    # Should terminate because finish_reason is "stop", not "tool_calls"
    mock_session_repo.claim_eos_emission.assert_awaited_once()


@pytest.mark.asyncio
async def test_reproduce_bug_from_logs(
    stream_processor: EndOfSessionStreamProcessor,
    mock_session_repo: AsyncMock,
) -> None:
    """Reproduce the exact scenario from the bug report logs.

    From logs (line 5124-5129):
    - Tool call 'bash' was detected
    - Session llm-b2bua-d64d1946-9b23-4e8c-971d-52298cdcd322 marked as completed
    - Reason: "Stream completed (is_done=True)"

    This should NOT happen after the fix.
    """
    session_id = "llm-b2bua-d64d1946-9b23-4e8c-971d-52298cdcd322"

    # Simulate the exact scenario from logs
    tool_call_content = StreamingContent(
        content="",  # Empty content, just tool calls in metadata
        metadata={
            "session_id": session_id,
            "finish_reason": "tool_calls",
            "protocol": "openai",
            "backend_name": "kimi-code",
            "tool_calls": [
                {
                    "id": "call_bash_123",
                    "type": "function",
                    "function": {"name": "bash", "arguments": "{}"},
                }
            ],
        },
        is_done=True,
    )

    result = await stream_processor.process(tool_call_content)

    # Verify the bug is fixed
    assert result is tool_call_content
    mock_session_repo.claim_eos_emission.assert_not_awaited()

    # Verify session can accept next turn (tool results)
    assert not await mock_session_repo.has_ended(session_id)
