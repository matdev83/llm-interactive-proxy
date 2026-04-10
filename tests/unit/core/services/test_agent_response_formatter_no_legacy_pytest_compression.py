from __future__ import annotations

import json

from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
from src.core.services.response_manager_service import AgentResponseFormatter


def _pytest_like_output() -> str:
    return (
        "tests/test_example.py::test_ok PASSED\n"
        "tests/test_example.py::test_fail FAILED\n"
        "========================= 1 failed, 1 passed in 0.01s ========================="
    )


def test_formatter_cline_path_keeps_pytest_output_unmodified() -> None:
    formatter = AgentResponseFormatter()
    session = Session(
        session_id="sess-formatter-cline",
        agent="cline",
        state=SessionState(),
    )
    payload = _pytest_like_output()
    result = formatter.format_command_result_for_agent(
        CommandResult(name="pytest", success=False, message=payload),
        session,
    )

    tool_call = result["choices"][0]["message"]["tool_calls"][0]
    args = json.loads(tool_call["function"]["arguments"])
    assert args["result"] == payload
    assert "PASSED" in args["result"]


def test_formatter_non_cline_path_keeps_pytest_output_unmodified() -> None:
    formatter = AgentResponseFormatter()
    session = Session(
        session_id="sess-formatter-chat",
        agent="openai",
        state=SessionState(),
    )
    payload = _pytest_like_output()
    result = formatter.format_command_result_for_agent(
        CommandResult(name="pytest", success=False, message=payload),
        session,
    )

    content = result["choices"][0]["message"]["content"]
    assert content == payload
    assert "PASSED" in content
