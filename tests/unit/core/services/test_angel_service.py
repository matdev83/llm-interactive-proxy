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


def test_strip_override_marker() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    raw = "Result body... <override_angel>True</override_angel> trailing"
    cleaned = svc.strip_override_marker(raw)
    assert "override_angel" not in cleaned


def test_strip_override_marker_is_case_insensitive() -> None:
    svc = AngelService("openai:gpt-4o-mini")
    raw = "Payload <override_angel> true </override_angel>"
    cleaned = svc.strip_override_marker(raw)
    assert "override_angel" not in cleaned.lower()


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
    backend, model, params = svc.parse_model()
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
    assert correction.messages[-1].role == "system"
    assert "Fix the solution" in str(correction.messages[-1].content)
