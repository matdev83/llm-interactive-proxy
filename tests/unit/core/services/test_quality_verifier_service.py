from __future__ import annotations

import pytest
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.services.quality_verifier_service import (
    QualityVerifierService,
    get_quality_verifier_prompt_loader,
)


def test_parse_quality_verifier_output_pass() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
    decision = svc.parse_quality_verifier_output("<status>NO_STEERING_NEEDED</status>")
    assert decision.decision == "pass"
    assert decision.steering_message is None


def test_parse_quality_verifier_output_steer() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
    text = """
<steering>
Use tool X instead of Y.
</steering>
"""
    decision = svc.parse_quality_verifier_output(text)
    assert decision.decision == "steer"
    assert "Use tool X" in (decision.steering_message or "")


def test_build_verification_messages_omits_tail_when_reminder_file_empty(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty ``quality_verifier_tail_reminder.md`` disables the tail user message."""
    import src.core.services.quality_verifier_service as qv_mod
    from src.core.services.quality_verifier_prompt_loader import (
        QualityVerifierPromptLoader,
    )

    (tmp_path / "quality_verifier_prompt.md").write_text(
        "Verifier system body", encoding="utf-8"
    )
    (tmp_path / "quality_verifier_tail_reminder.md").write_text(
        " \n\t ", encoding="utf-8"
    )

    loader = QualityVerifierPromptLoader(str(tmp_path))
    loader.load_prompts()
    monkeypatch.setattr(qv_mod, "get_quality_verifier_prompt_loader", lambda: loader)

    svc = QualityVerifierService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
    )
    messages = svc.build_verification_messages(request, "draft response")
    assert len(messages) == 3
    assert messages[0].role == "system"
    assert messages[0].content == "Verifier system body"
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "draft response"


def test_build_verification_messages_includes_prompt() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
        ],
    )
    messages = svc.build_verification_messages(request, "draft response")
    assert messages[0].role == "system"
    assert (
        messages[0].content
        == get_quality_verifier_prompt_loader().quality_verifier_prompt
    )
    assert messages[-2].role == "user"
    assert str(messages[-2].content).startswith("<system-reminder>")
    assert str(messages[-2].content).endswith("</system-reminder>")
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "draft response"


def test_build_verification_messages_truncates_history() -> None:
    # Explicitly set max_history to 10
    svc = QualityVerifierService("openai:gpt-4o-mini", max_history=10)
    # Create 50 messages
    history = [ChatMessage(role="user", content=str(i)) for i in range(50)]
    request = ChatRequest(model="test", messages=history)

    messages = svc.build_verification_messages(request, "response")
    # System + MAX_HISTORY (10) + tail reminder user + assistant = 13
    assert len(messages) == 13
    assert messages[0].role == "system"
    # The last history message should be the last 'user' message we added (49)
    assert messages[-3].content == "49"


def test_build_verification_messages_no_truncation_by_default() -> None:
    # Default (no max_history)
    svc = QualityVerifierService("openai:gpt-4o-mini")
    # Create 50 messages
    history = [ChatMessage(role="user", content=str(i)) for i in range(50)]
    request = ChatRequest(model="test", messages=history)

    messages = svc.build_verification_messages(request, "response")
    # System + ALL HISTORY (50) + tail reminder user + assistant = 53
    assert len(messages) == 53
    assert messages[0].role == "system"
    assert messages[-3].content == "49"


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
    svc = QualityVerifierService(spec)
    parsed = svc.parse_model()
    backend = parsed.backend_type
    model = parsed.model_name
    params = parsed.uri_params
    assert backend == expected_backend
    assert model == expected_model
    assert params == expected_params


def test_should_run_for_request_skips_first_user_turn_even_when_frequency_is_one() -> (
    None
):
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="one"),
        ],
    )
    assert QualityVerifierService.should_run_for_request(request, 1) is False


def test_should_run_for_request_runs_from_second_user_turn_when_frequency_is_one() -> (
    None
):
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[
            ChatMessage(role="user", content="one"),
            ChatMessage(role="assistant", content="a"),
            ChatMessage(role="user", content="two"),
        ],
    )
    assert QualityVerifierService.should_run_for_request(request, 1) is True


def test_should_run_for_request_every_nth_turn() -> None:
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content=str(i)) for i in range(5)],
    )
    assert QualityVerifierService.should_run_for_request(request, 5) is True
    assert QualityVerifierService.should_run_for_request(request, 6) is False


def test_build_verification_request_uses_default_backend() -> None:
    svc = QualityVerifierService("gpt-4o-mini?temperature=0.2")
    request = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="user", content="Hi")],
        stream=True,
    )
    verification = svc.build_verification_request(request, "Draft reply")
    assert verification.model == "openai:gpt-4o-mini"
    assert verification.stream is True
    assert verification.messages[0].role == "system"
    assert (
        verification.messages[0].content
        == get_quality_verifier_prompt_loader().quality_verifier_prompt
    )
    assert verification.messages[-2].role == "user"
    assert str(verification.messages[-2].content).startswith("<system-reminder>")
    assert verification.messages[-1].role == "assistant"
    assert verification.messages[-1].content == "Draft reply"


def test_build_correction_request_includes_previous_response() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
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

    svc = QualityVerifierService("openai:gpt-4o-mini")
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

    # System + 3 processed messages + tail reminder user + assistant = 6
    assert len(messages) == 6

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
    svc = QualityVerifierService("openai:gpt-4o-mini")
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
    assert (
        messages[0].content
        == get_quality_verifier_prompt_loader().quality_verifier_prompt
    )
    assert all(
        not (m.role == "system" and str(m.content) == "MAIN SYSTEM PROMPT")
        for m in messages[1:]
    )
    assert messages[-2].role == "user"
    assert "<system-reminder>" in str(messages[-2].content)
    assert messages[-1].role == "assistant"
    assert messages[-1].content == "Latest draft"


def test_build_verification_messages_strips_serialized_tool_definitions() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
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
    assert (
        messages[1].content == "[Tool definitions omitted for Quality Verifier audit.]"
    )


@pytest.mark.parametrize(
    "angel_output, is_valid, reason_fragment",
    [
        ("<status>NO_STEERING_NEEDED</status>", True, None),
        (
            "<steering>Fix it</steering>",
            True,
            None,
        ),
        (
            "I think this looks okay.",
            False,
            "Missing required <status> or <steering>",
        ),
        (
            "<steering>   </steering>",
            False,
            "empty",
        ),
    ],
)
def test_validate_quality_verifier_output_format(
    angel_output: str, is_valid: bool, reason_fragment: str | None
) -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")

    valid, reason = svc.validate_quality_verifier_output_format(angel_output)

    assert valid is is_valid
    if reason_fragment is None:
        assert reason is None
    else:
        assert reason is not None
        assert reason_fragment.lower() in reason.lower()


def test_build_invalid_format_retry_request_appends_feedback_messages() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
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

    assert retry_request.stream is True
    assert retry_request.messages[-2].role == "assistant"
    assert retry_request.messages[-2].content == "Free-form answer without tags"
    assert retry_request.messages[-1].role == "user"
    assert "FORMAT CORRECTION" in str(retry_request.messages[-1].content)
    assert "Missing decision tags" in str(retry_request.messages[-1].content)
    assert "Do not call tools" in str(retry_request.messages[-1].content)


def test_coerce_eligible_turn_floor() -> None:
    assert QualityVerifierService.coerce_eligible_turn_floor(None) is None
    assert QualityVerifierService.coerce_eligible_turn_floor("10.7") == 10
    assert QualityVerifierService.coerce_eligible_turn_floor(10.7) == 10
    assert QualityVerifierService.coerce_eligible_turn_floor(0) is None
    assert QualityVerifierService.coerce_eligible_turn_floor(True) is None
    # Scaled storage (1000 units per logical turn)
    assert QualityVerifierService.coerce_eligible_turn_floor(10_000) == 10
    assert QualityVerifierService.coerce_eligible_turn_floor(8200) == 8
    # Legacy small int = whole logical turns
    assert QualityVerifierService.coerce_eligible_turn_floor(7) == 7


def test_should_run_verification_prefers_eligible_raw() -> None:
    req = ChatRequest(
        model="x",
        messages=[ChatMessage(role="user", content="a")],
    )
    assert QualityVerifierService.should_run_verification(req, 10, eligible_turn_raw=10)
    assert not QualityVerifierService.should_run_verification(
        req, 10, eligible_turn_raw=9
    )
    assert not QualityVerifierService.should_run_verification(
        req, 1, eligible_turn_raw=1000
    )
    assert QualityVerifierService.should_run_verification(
        req, 1, eligible_turn_raw=2000
    )
    req_two_users = ChatRequest(
        model="x",
        messages=[
            ChatMessage(role="user", content="a"),
            ChatMessage(role="assistant", content="b"),
            ChatMessage(role="user", content="c"),
        ],
    )
    assert QualityVerifierService.should_run_verification(
        req_two_users, 1, eligible_turn_raw=None
    )
    assert QualityVerifierService.should_run_verification(
        req, 10, eligible_turn_raw=10_000
    )


async def test_maybe_retry_verifier_for_valid_xml_retries_once() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
    vreq = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="system", content="s")],
        stream=True,
    )
    calls: list[int] = []

    async def call_once(req: ChatRequest) -> str | None:
        # first_text is validated locally; call_once is only the format-retry round trip
        calls.append(1)
        return "<status>NO_STEERING_NEEDED</status>"

    out = await svc.maybe_retry_verifier_for_valid_xml(vreq, "not xml", call_once)
    assert out == "<status>NO_STEERING_NEEDED</status>"
    assert len(calls) == 1


async def test_maybe_retry_verifier_skips_second_call_when_first_valid() -> None:
    svc = QualityVerifierService("openai:gpt-4o-mini")
    vreq = ChatRequest(
        model="openai:gpt-4o-mini",
        messages=[ChatMessage(role="system", content="s")],
        stream=True,
    )
    calls = 0

    async def call_once(req: ChatRequest) -> str | None:
        nonlocal calls
        calls += 1
        return "<status>NO_STEERING_NEEDED</status>"

    out = await svc.maybe_retry_verifier_for_valid_xml(
        vreq, "<status>NO_STEERING_NEEDED</status>", call_once
    )
    assert out is not None and "NO_STEERING" in out
    assert calls == 0
