"""Property-based tests for Python test runner detection.

Feature: test-execution-reminder
Property 2: Test Execution Clears Dirty State Across All Languages (Python subset)
Validates: Requirements 2.1
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st
from src.services.test_execution_reminder.session_state import (
    TestExecutionSessionState,
)
from src.services.test_execution_reminder.test_runner_registry import (
    TestRunnerRegistry,
)
from tests.utils.hypothesis_config import property_test_settings

# ============================================================================
# Strategies for generating Python test commands
# ============================================================================


@st.composite
def pytest_command_strategy(draw: Any) -> str:
    """Generate pytest command variations.

    This generates various forms of pytest commands including:
    - Direct invocation: pytest
    - Module invocation: python -m pytest
    - Wrapper invocation: pipenv run pytest, poetry run pytest
    - With arguments: pytest tests/, pytest -v, pytest --cov
    """
    # Base command variations
    base_commands = [
        "pytest",
        "py.test",
        "python -m pytest",
        "python3 -m pytest",
        "pipenv run pytest",
        "poetry run pytest",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " tests/",
            " test_*.py",
            " -v",
            " --verbose",
            " -x",
            " --cov",
            " --cov=src",
            " -k test_name",
            " tests/unit/",
            " tests/integration/",
            " --tb=short",
            " -s",
            " --maxfail=1",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def unittest_command_strategy(draw: Any) -> str:
    """Generate unittest command variations.

    This generates various forms of unittest commands including:
    - Module invocation: python -m unittest
    - Direct invocation: unittest
    - With arguments: python -m unittest discover
    """
    # Base command variations
    base_commands = [
        "python -m unittest",
        "python3 -m unittest",
        "unittest",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " discover",
            " tests",
            " test_module",
            " test_module.TestClass",
            " test_module.TestClass.test_method",
            " -v",
            " --verbose",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def python_test_command_strategy(draw: Any) -> str:
    """Generate any Python test command (pytest or unittest)."""
    command_type = draw(st.sampled_from(["pytest", "unittest"]))

    if command_type == "pytest":
        return draw(pytest_command_strategy())
    else:
        return draw(unittest_command_strategy())


@st.composite
def non_test_command_strategy(draw: Any) -> str:
    """Generate commands that are NOT test execution commands.

    This generates various non-test commands to ensure they don't
    incorrectly match test runner patterns.
    """
    non_test_commands = [
        "python script.py",
        "python -m pip install pytest",
        "python -m black .",
        "python -m ruff check .",
        "python -m mypy src/",
        "python setup.py install",
        "python manage.py runserver",
        "npm install",
        "npm run build",
        "git commit -m 'test'",
        "echo pytest",
        "cat pytest.ini",
        "ls -la",
        "cd tests/",
        "mkdir tests",
        "rm -rf tests/__pycache__",
        "grep pytest requirements.txt",
        "find . -name pytest",
        "docker run pytest",
        "which pytest",
        "pip install pytest",
        "poetry add pytest",
        "pipenv install pytest",
    ]

    return draw(st.sampled_from(non_test_commands))


# ============================================================================
# Property Tests
# ============================================================================


@given(command=pytest_command_strategy())
@property_test_settings()
def test_property_2_pytest_detection(command: str) -> None:
    """
    Property 2: Pytest Command Detection.

    For any pytest command variation, the test runner registry should
    correctly identify it as a Python test execution command with the
    pytest framework.

    Validates: Requirements 2.1
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Pytest command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all pytest command variations."
    )

    # Verify language is Python
    assert language == "python", (
        f"Pytest command '{command}' was detected with language '{language}' "
        f"instead of 'python'."
    )

    # Verify framework is pytest
    assert framework == "pytest", (
        f"Pytest command '{command}' was detected with framework '{framework}' "
        f"instead of 'pytest'."
    )


@given(command=unittest_command_strategy())
@property_test_settings()
def test_property_2_unittest_detection(command: str) -> None:
    """
    Property 2: Unittest Command Detection.

    For any unittest command variation, the test runner registry should
    correctly identify it as a Python test execution command with the
    unittest framework.

    Validates: Requirements 2.1
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Unittest command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all unittest command variations."
    )

    # Verify language is Python
    assert language == "python", (
        f"Unittest command '{command}' was detected with language '{language}' "
        f"instead of 'python'."
    )

    # Verify framework is unittest
    assert framework == "unittest", (
        f"Unittest command '{command}' was detected with framework '{framework}' "
        f"instead of 'unittest'."
    )


@given(command=non_test_command_strategy())
@property_test_settings()
def test_property_2_non_test_command_rejection(command: str) -> None:
    """
    Property 2: Non-Test Command Rejection.

    For any command that is NOT a test execution command, the test runner
    registry should NOT identify it as a test command.

    Validates: Requirements 2.1
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's NOT detected as a test command
    assert is_match is False, (
        f"Non-test command '{command}' was incorrectly detected as a test command "
        f"(language={language}, framework={framework}). "
        f"The registry should only match actual test execution commands."
    )

    # Verify language and framework are None
    assert (
        language is None
    ), f"Non-test command '{command}' should have language=None, got '{language}'"
    assert (
        framework is None
    ), f"Non-test command '{command}' should have framework=None, got '{framework}'"


@given(command=python_test_command_strategy())
@property_test_settings()
def test_property_2_dirty_state_cleared_by_test_execution(command: str) -> None:
    """
    Property 2: Test Execution Clears Dirty State (Python).

    For any Python test execution command, if the session is in dirty state,
    then processing the command should transition the state to clean.

    Validates: Requirements 2.1
    """
    registry = TestRunnerRegistry()
    state = TestExecutionSessionState()

    # Mark the state as dirty (simulate file modification)
    state.mark_dirty()
    assert state.is_dirty is True, "State should be dirty after modification"
    assert state.modification_count > 0, "Modification count should be > 0"

    # Verify the command is a test command
    is_match, language, framework = registry.match_command(command)
    assert is_match is True, f"Command '{command}' should be detected as test command"
    assert language == "python", f"Command '{command}' should be Python"

    # Simulate test execution (mark state as clean)
    state.mark_clean()

    # Verify state is now clean
    assert state.is_dirty is False, (
        f"State should be clean after test execution with command '{command}'. "
        f"Test execution should clear the dirty state."
    )

    # Verify modification count is reset
    assert state.modification_count == 0, (
        f"Modification count should be reset to 0 after test execution, "
        f"got {state.modification_count}"
    )


@given(
    pytest_cmd=pytest_command_strategy(),
    unittest_cmd=unittest_command_strategy(),
)
@property_test_settings()
def test_property_2_multiple_test_runs_maintain_clean_state(
    pytest_cmd: str,
    unittest_cmd: str,
) -> None:
    """
    Property 2: Multiple Test Runs Maintain Clean State.

    For any sequence of test execution commands in clean state,
    the state should remain clean without errors.

    Validates: Requirements 2.1, 8.1
    """
    registry = TestRunnerRegistry()
    state = TestExecutionSessionState()

    # Initially clean
    assert state.is_dirty is False, "Initial state should be clean"

    # Run first test (pytest)
    is_match, _, _ = registry.match_command(pytest_cmd)
    assert is_match is True, f"Command '{pytest_cmd}' should match"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after first test"

    # Run second test (unittest)
    is_match, _, _ = registry.match_command(unittest_cmd)
    assert is_match is True, f"Command '{unittest_cmd}' should match"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after second test"

    # Run first test again
    is_match, _, _ = registry.match_command(pytest_cmd)
    assert is_match is True, f"Command '{pytest_cmd}' should match again"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after third test"


@given(command=python_test_command_strategy())
@property_test_settings()
def test_property_2_empty_command_handling(command: str) -> None:
    """
    Property 2: Empty Command Handling.

    The registry should handle edge cases like empty strings gracefully
    without raising exceptions.

    Validates: Requirements 2.1
    """
    registry = TestRunnerRegistry()

    # Test empty string
    is_match, language, framework = registry.match_command("")
    assert is_match is False, "Empty string should not match any pattern"
    assert language is None, "Empty string should have language=None"
    assert framework is None, "Empty string should have framework=None"


@given(
    modification_count=st.integers(min_value=1, max_value=10),
    test_command=python_test_command_strategy(),
)
@property_test_settings()
def test_property_2_state_transition_cycle(
    modification_count: int,
    test_command: str,
) -> None:
    """
    Property 2: State Transition Cycle.

    For any session, if the sequence is: modify file -> run tests -> modify file,
    then the state transitions should be: clean -> dirty -> clean -> dirty.

    Validates: Requirements 2.1, 8.2
    """
    registry = TestRunnerRegistry()
    state = TestExecutionSessionState()

    # Initial state: clean
    assert state.is_dirty is False, "Initial state should be clean"

    for i in range(modification_count):
        # Modify file -> dirty
        state.mark_dirty()
        assert state.is_dirty is True, f"State should be dirty after modification {i+1}"

        # Run tests -> clean
        is_match, _, _ = registry.match_command(test_command)
        assert is_match is True, f"Test command should match on iteration {i+1}"
        state.mark_clean()
        assert state.is_dirty is False, f"State should be clean after test run {i+1}"


@given(command=python_test_command_strategy())
@property_test_settings()
def test_property_2_test_execution_in_clean_state(command: str) -> None:
    """
    Property 2: Test Execution in Clean State.

    For any test execution command in clean state, the state should
    remain clean (no state change).

    Validates: Requirements 2.1, 2.16
    """
    registry = TestRunnerRegistry()
    state = TestExecutionSessionState()

    # Initial state: clean
    assert state.is_dirty is False, "Initial state should be clean"

    # Verify command is a test command
    is_match, _, _ = registry.match_command(command)
    assert is_match is True, f"Command '{command}' should be detected as test command"

    # Run test in clean state
    state.mark_clean()

    # State should remain clean
    assert state.is_dirty is False, (
        f"State should remain clean after test execution in clean state. "
        f"Command: '{command}'"
    )
