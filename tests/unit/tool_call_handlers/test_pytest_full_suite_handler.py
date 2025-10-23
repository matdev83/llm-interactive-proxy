import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
    PytestFullSuiteHandler,
    _looks_like_full_suite,
)


@pytest.mark.parametrize(
    "command, expected",
    [
        # Positive cases (should be detected as full suite)
        ("pytest", True),
        ("py.test", True),
        ("python -m pytest", True),
        ("python3 -m pytest", True),
        (r".\.venv\Scripts\python.exe -m pytest", True),
        ("pytest --ignore=some_path", True),  # --ignore is not a filter flag
        ("pipenv run pytest", True),
        ("pipenv --python 3 run pytest", True),
        ("env PYTEST_ADDOPTS='-k smoke' pytest", True),
        # Negative cases (should NOT be detected as full suite)
        ("pytest tests/unit/test_cli.py", False),
        ("python -m pytest tests/unit/test_cli.py", False),
        ("pytest -k my_test", False),
        ("python -m pytest -k my_test", False),
        ("pytest --ff", False),
        ("python -m pytest --ff", False),
        ("pytest /path/to/tests", False),
        ("python -m pytest /path/to/tests", False),
        ("pytest tests/unit/test_cli.py::test_something", False),
        ("python -m pytest tests/unit/test_cli.py::test_something", False),
        ("pytest --lf", False),
        ("pip install pytest", False),
        ("pip install pytest-cov", False),
        ("echo pytest", False),
    ],
)
def test_looks_like_full_suite(command, expected):
    """
    Tests the _looks_like_full_suite function with various command formats,
    including direct calls and module invocations.
    """
    assert _looks_like_full_suite(command) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_name, tool_arguments, expected",
    [
        # Positive cases - recognized shell execution tools
        ("execute_command", {"command": "python -m pytest"}, True),
        ("execute_command", {"command": "pytest"}, True),
        ("exec", {"command": "pytest"}, True),
        ("execute", {"command": "pytest"}, True),
        ("shell", {"command": "pytest"}, True),
        ("bash", {"command": "pytest"}, True),
        ("run_terminal_cmd", {"command": "pytest"}, True),
        ("python", {"command": "python -m pytest"}, True),
        # Negative cases
        ("execute_command", {"command": "python -m pytest -k test_foo"}, False),
        ("execute_command", {"command": "pytest tests/my_test.py"}, False),
        # Should NOT handle if not a recognized shell tool - CRITICAL TEST
        ("other_tool", {"command": "pytest"}, False),
        ("random_function", {"command": "pytest"}, False),
        ("my_custom_tool", {"command": "python -m pytest"}, False),
        # Should not handle if not a shell tool and pytest not in name/args
        ("other_tool", {"args": "test"}, False),
        # Should handle if pytest is in the tool name
        ("pytest", {}, True),
        ("pytest", {"args": "-v"}, True),
        # Should not handle if filtered
        ("pytest", {"args": "-k foo"}, False),
    ],
)
async def test_handler_can_handle(tool_name, tool_arguments, expected):
    """Tests the can_handle method of the handler with different contexts."""
    handler = PytestFullSuiteHandler(enabled=True)
    context = ToolCallContext(
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        session_id="test_session",
        backend_name="dummy_backend",
        model_name="dummy_model",
        full_response={},
    )

    result = await handler.can_handle(context)
    assert result == expected
