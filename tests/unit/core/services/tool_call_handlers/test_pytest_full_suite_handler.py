from __future__ import annotations

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
    PytestFullSuiteHandler,
    _looks_like_full_suite,
)


@pytest.mark.parametrize(
    "command,expected",
    [
        ("pytest", True),
        ("python -m pytest", True),
        ("py.test", True),
        ("pytest -q", True),
        ("pytest --maxfail=1", True),
        ("pytest tests/unit", False),
        ("pytest tests/unit/test_example.py", False),
        ("pytest some/test/path", False),
        ("pytest some/test/path::TestSuite::test_case", False),
        ("pytest .", False),
        ("pytest ./tests", False),
    ],
)
def test_full_suite_detection(command: str, expected: bool) -> None:
    assert _looks_like_full_suite(command) is expected


def _build_context(command: str, session_id: str = "session-1") -> ToolCallContext:
    return ToolCallContext(
        session_id=session_id,
        backend_name="backend",
        model_name="model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": command},
    )


def _build_context_with_input(
    command: str, session_id: str = "session-1"
) -> ToolCallContext:
    return ToolCallContext(
        session_id=session_id,
        backend_name="backend",
        model_name="model",
        full_response={},
        tool_name="bash",
        tool_arguments={"input": command},
    )


def _build_python_context(args: list[str], session_id: str = "session-1") -> ToolCallContext:
    return ToolCallContext(
        session_id=session_id,
        backend_name="backend",
        model_name="model",
        full_response={},
        tool_name="python",
        tool_arguments={"args": args},
    )


@pytest.mark.asyncio
async def test_handler_swallow_first_full_suite_command() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_context("pytest")

    assert await handler.can_handle(context) is True
    result = await handler.handle(context)

    assert result.should_swallow is True
    assert result.replacement_response is not None


@pytest.mark.asyncio
async def test_handler_allows_same_command_after_warning() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_context("pytest")

    assert await handler.can_handle(context) is True
    await handler.handle(context)

    assert await handler.can_handle(context) is False
    result = await handler.handle(context)
    assert result.should_swallow is False


@pytest.mark.asyncio
async def test_handler_allows_second_session_immediately() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    first = _build_context("pytest", session_id="session-1")
    second = _build_context("pytest", session_id="session-2")

    assert await handler.can_handle(first) is True
    await handler.handle(first)

    assert await handler.can_handle(second) is True


@pytest.mark.asyncio
async def test_handler_passes_through_targeted_pytest() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_context("pytest tests/unit/test_example.py")

    assert await handler.can_handle(context) is False
    result = await handler.handle(context)
    assert result.should_swallow is False


@pytest.mark.asyncio
async def test_handler_detects_list_based_command() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = ToolCallContext(
        session_id="session-list",
        backend_name="backend",
        model_name="model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": ["pytest", "-q"]},
    )

    assert await handler.can_handle(context) is True
    result = await handler.handle(context)

    assert result.should_swallow is True


@pytest.mark.asyncio
async def test_handler_enabled_flag_controls_behavior() -> None:
    handler = PytestFullSuiteHandler(enabled=False)
    context = _build_context("pytest")

    assert await handler.can_handle(context) is False
    result = await handler.handle(context)
    assert result.should_swallow is False


@pytest.mark.asyncio
async def test_handler_detects_command_from_input_string() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_context_with_input("pytest")

    assert await handler.can_handle(context) is True
    result = await handler.handle(context)

    assert result.should_swallow is True


@pytest.mark.asyncio
async def test_handler_detects_python_pytest_invocation() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_python_context(["-m", "pytest"])

    assert await handler.can_handle(context) is True
    result = await handler.handle(context)

    assert result.should_swallow is True


@pytest.mark.asyncio
async def test_handler_allows_targeted_python_pytest_invocation() -> None:
    handler = PytestFullSuiteHandler(enabled=True)
    context = _build_python_context(["-m", "pytest", "tests/unit/test_example.py"])

    assert await handler.can_handle(context) is False
    result = await handler.handle(context)

    assert result.should_swallow is False
