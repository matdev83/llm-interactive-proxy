from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.angel_service import AngelService, get_prompt_loader


def test_parse_angel_output_pass() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    decision = svc.parse_angel_output("<angels_decision>Pass</angels_decision>")
    assert decision.decision == "pass"
    assert decision.steering_message is None


def test_parse_angel_output_steer() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    text = """
<angels_steering_message>
Use tool X instead of Y.
</angels_steering_message>
"""
    decision = svc.parse_angel_output(text)
    assert decision.decision == "steer"
    assert "Use tool X" in (decision.steering_message or "")


def test_build_verification_messages_includes_prompt() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ],
    )
    messages = svc.build_verification_messages(request, "draft response")
    assert messages[0].role == "system"
    assert messages[0].content == get_prompt_loader().angel_prompt
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "draft response"


def test_build_verification_messages_truncates_history() -> None:
    # Explicitly set max_history to 10
    svc = AngelService("openai:gpt-4o-mini", max_history=10)
    # Create 50 messages
    history = [ChatMessage(role="user", content=str(i)) for i in range(50)]
    request = ChatRequest(model="test", messages=history)

    messages = svc.build_verification_messages(request, "response")
    # System prompt + MAX_HISTORY (10) + Assistant Response = 12
    assert len(messages) == 12
    assert messages[0].role == "system"
    # The last history message should be the last 'user' message we added (49)
    assert messages[-2].content == "49"


def test_build_verification_messages_no_truncation_by_default() -> None:
    # Default (no max_history)
    svc = AngelService("openai:gpt-4o-mini")
    # Create 50 messages
    history = [ChatMessage(role="user", content=str(i)) for i in range(50)]
    request = ChatRequest(model="test", messages=history)

    messages = svc.build_verification_messages(request, "response")
    # System prompt + ALL HISTORY (50) + Assistant Response = 52
    assert len(messages) == 52
    assert messages[0].role == "system"
    assert messages[-2].content == "49"


@pytest.mark.parametrize(
    "spec, expected_backend, expected_model, expected_params",
    [
        (
            "anthropic:claude-3-5-sonnet?temperature=1&reasoning_effort=high",
            "anthropic",
            "claude-3-5-sonnet",
            {"temperature": "1", "reasoning_effort": "high"},
        ),
        (
            "openrouter:anthropic/claude-3?temperature=0.5",
            "openrouter",
            "anthropic/claude-3",
            {"temperature": "0.5"},
        ),
        ("gpt-4o-mini?temperature=0.2", "", "gpt-4o-mini", {"temperature": "0.2"}),
    ],
)
def test_parse_model_with_params(
    spec: str,
    expected_backend: str,
    expected_model: str,
    expected_params: dict[str, str],
) -> None:
    svc = AngelService(spec)
    parsed = svc.parse_model()
    backend = parsed.backend_type
    model = parsed.model_name
    params = parsed.uri_params
    assert backend == expected_backend
    assert model == expected_model
    assert params == expected_params


def test_should_run_for_request_every_turn() -> None:
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="one"),
        ],
    )
    assert AngelService.should_run_for_request(request, 1) is True


def test_should_run_for_request_every_nth_turn() -> None:
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content=str(i)) for i in range(5)],
    )
    assert AngelService.should_run_for_request(request, 5) is True
    assert AngelService.should_run_for_request(request, 6) is False


def test_build_verification_request_uses_default_backend() -> None:
    svc = AngelService("gpt-4o-mini?temperature=0.2")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )
    verification = svc.build_verification_request(request, "Draft reply")
    assert verification.model == "openai:gpt-4o-mini"
    assert verification.stream is False
    assert verification.messages[0].role == "system"
    assert verification.messages[0].content == get_prompt_loader().angel_prompt
    assert verification.messages[-1].role == "assistant"
    assert verification.messages[-1].content == "Draft reply"


def test_build_correction_request_includes_previous_response() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )
    correction = svc.build_correction_request(request, "Bad output", "Fix the solution")
    assert correction.model == "openai:gpt-4o-mini"
    assert correction.stream is False
    assert correction.messages[-2].role == "assistant"
    assert correction.messages[-2].content == "Bad output"
    assert correction.messages[-1].role == "user"
    assert "VERIFICATION FEEDBACK" in str(correction.messages[-1].content)
    assert "Fix the solution" in str(correction.messages[-1].content)


def test_build_verification_messages_stringifies_tools() -> None:
    from src.core.domain.chat import FunctionCall, ToolCall

    svc = AngelService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="Search for something"),
            ChatMessage(
                role="assistant",
                content="I will search",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function=FunctionCall(name="search", arguments='{"q": "test"}'),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                content="found results",
                tool_call_id="call_1",
            ),
        ],
    )
    messages = svc.build_verification_messages(request, "final answer")

    # System prompt + 3 processed messages + 1 assistant message = 5
    assert len(messages) == 5

    # Assistant message should be stringified
    assert messages[2].role == "assistant"
    assert messages[2].tool_calls is None
    assert "I will search" in str(messages[2].content)
    assert '[Tool Call: search({"q": "test"})]' in str(messages[2].content)

    # Tool message should be stringified to a user message
    assert messages[3].role == "user"
    assert "Tool result (tool_call_id=call_1): found results" in str(
        messages[3].content
    )


def test_build_verification_messages_strips_main_system_messages() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="system", content="MAIN SYSTEM PROMPT"),
            ChatMessage(role="user", content="User task"),
            ChatMessage(role="assistant", content="Draft answer"),
        ],
    )

    messages = svc.build_verification_messages(request, "Latest draft")

    assert messages[0].role == "system"
    assert messages[0].content == get_prompt_loader().angel_prompt
    assert all(
        not (m.role == "system" and str(m.content) == "MAIN SYSTEM PROMPT")
        for m in messages[1:]
    )
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "Latest draft"


def test_build_verification_messages_strips_serialized_tool_definitions() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(
                role="user",
                content='{"tools":[{"type":"function","function":{"name":"search","parameters":{"type":"object"}}}]}',
            ),
        ],
    )

    messages = svc.build_verification_messages(request, "draft")

    assert messages[1].role == "user"
    assert messages[1].content == "[Tool definitions omitted for Angel audit.]"


@pytest.mark.parametrize(
    "angel_output, is_valid, reason_fragment",
    [
        ("<angels_decision>Pass</angels_decision>", True, None),
        (
            "<angels_decision>Steer</angels_decision><angels_steering_message>Fix it</angels_steering_message>",
            True,
            None,
        ),
        ("I think this looks okay.", False, "Missing required XML decision tags"),
        (
            "<angels_decision>Steer</angels_decision>",
            False,
            "missing <angels_steering_message>",
        ),
    ],
)
def test_validate_angel_output_format(
    angel_output: str, is_valid: bool, reason_fragment: str | None
) -> None:
    svc = AngelService("openai:gpt-4o-mini")

    valid, reason = svc.validate_angel_output_format(angel_output)

    assert valid is is_valid
    if reason_fragment is None:
        assert reason is None
    else:
        assert reason is not None
        assert reason_fragment.lower() in reason.lower()


def test_build_invalid_format_retry_request_appends_feedback_messages() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    verification_request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="system", content="Angel system"),
            ChatMessage(role="user", content="Task"),
            ChatMessage(role="assistant", content="Draft"),
        ],
        stream=False,
    )

    retry_request = svc.build_invalid_format_retry_request(
        verification_request,
        "Free-form answer without tags",
        "Missing decision tags",
    )

    assert retry_request.stream is False
    assert retry_request.messages[-2].role == "assistant"
    assert retry_request.messages[-2].content == "Free-form answer without tags"
    assert retry_request.messages[-1].role == "user"
    assert "FORMAT CORRECTION" in str(retry_request.messages[-1].content)
    assert "Missing decision tags" in str(retry_request.messages[-1].content)
