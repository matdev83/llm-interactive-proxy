from src.core.domain.chat import ChatMessage, ChatRequest, FunctionCall, ToolCall
from src.core.domain.tool_progress_loop import ToolProgressLoopAction
from src.core.services.tool_progress_loop_guard import ToolProgressLoopGuard


def _request_with_tool_result(output: str, *, tool_name: str = "read") -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="inspect logs"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(
                            name=tool_name,
                            arguments='{"filePath":"var/logs/proxy.log","limit":20}',
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", content=output, tool_call_id="call_1"),
        ],
    )


async def test_guard_blocks_repeated_same_tool_output() -> None:
    guard = ToolProgressLoopGuard(max_repeated_tool_output=3)

    for _ in range(2):
        decision = await guard.evaluate_request(
            session_id="stable-session",
            request=_request_with_tool_result("same output"),
        )
        assert decision.action == ToolProgressLoopAction.ALLOW

    decision = await guard.evaluate_request(
        session_id="stable-session",
        request=_request_with_tool_result("same output"),
    )

    assert decision.action == ToolProgressLoopAction.BLOCK
    assert decision.repeated_output_count == 3


async def test_guard_blocks_repeated_same_tool_parameters() -> None:
    guard = ToolProgressLoopGuard(max_repeated_tool_call_signature=3)

    for _ in range(2):
        decision = await guard.evaluate_request(
            session_id="stable-session",
            request=_request_with_tool_result(f"output {_}"),
        )
        assert decision.action == ToolProgressLoopAction.ALLOW

    decision = await guard.evaluate_request(
        session_id="stable-session",
        request=_request_with_tool_result("different output"),
    )

    assert decision.action == ToolProgressLoopAction.BLOCK
    assert decision.repeated_call_count == 3


async def test_guard_blocks_consecutive_tool_followups_even_when_values_change() -> (
    None
):
    guard = ToolProgressLoopGuard(
        max_consecutive_tool_followups=3,
        max_repeated_tool_call_signature=99,
        max_repeated_tool_output=99,
    )

    for idx in range(2):
        decision = await guard.evaluate_request(
            session_id="stable-session",
            request=_request_with_tool_result(f"output {idx}"),
        )
        assert decision.action == ToolProgressLoopAction.ALLOW

    decision = await guard.evaluate_request(
        session_id="stable-session",
        request=_request_with_tool_result("output 3"),
    )

    assert decision.action == ToolProgressLoopAction.BLOCK
    assert decision.reason == "consecutive_tool_followups"


async def test_guard_resets_on_new_user_message_after_tool_result() -> None:
    guard = ToolProgressLoopGuard(max_consecutive_tool_followups=2)

    assert (
        await guard.evaluate_request(
            session_id="stable-session",
            request=_request_with_tool_result("first"),
        )
    ).allow

    new_user_request = ChatRequest(
        model="gpt-4",
        messages=[
            *_request_with_tool_result("first").messages,
            ChatMessage(role="user", content="stop and summarize"),
        ],
    )

    assert (
        await guard.evaluate_request(
            session_id="stable-session",
            request=new_user_request,
        )
    ).allow
    assert (
        await guard.evaluate_request(
            session_id="stable-session",
            request=_request_with_tool_result("second"),
        )
    ).allow


async def test_guard_finds_assistant_tool_calls_when_last_assistant_has_none() -> None:
    guard = ToolProgressLoopGuard()
    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="inspect logs"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(
                            name="read", arguments='{"filePath":"one.log"}'
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", content="result 1", tool_call_id="call_1"),
            ChatMessage(role="assistant", content="thinking...", tool_calls=None),
        ],
    )

    decision = await guard.evaluate_request(
        session_id="stable-session", request=request
    )

    assert decision.repeated_call_count == 1


async def test_guard_counts_only_latest_tool_result_batch() -> None:
    guard = ToolProgressLoopGuard(max_repeated_tool_output=3)
    request = ChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="user", content="inspect logs"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(
                            name="read", arguments='{"filePath":"one.log"}'
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", content="old repeated", tool_call_id="call_1"),
            ChatMessage(
                role="assistant",
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_2",
                        function=FunctionCall(
                            name="read", arguments='{"filePath":"two.log"}'
                        ),
                    )
                ],
            ),
            ChatMessage(role="tool", content="latest", tool_call_id="call_2"),
        ],
    )

    assert (
        await guard.evaluate_request(session_id="stable-session", request=request)
    ).allow
    assert (
        await guard.evaluate_request(session_id="stable-session", request=request)
    ).allow
    decision = await guard.evaluate_request(
        session_id="stable-session", request=request
    )

    assert decision.action == ToolProgressLoopAction.BLOCK
    assert decision.repeated_output_count == 3
