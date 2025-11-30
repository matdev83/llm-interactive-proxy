"""Property-based tests for JavaScript/TypeScript test runner detection.

Feature: test-execution-reminder
Property 2: Test Execution Clears Dirty State Across All Languages (JavaScript subset)
Validates: Requirements 2.2
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
# Strategies for generating JavaScript/TypeScript test commands
# ============================================================================


@st.composite
def jest_command_strategy(draw: Any) -> str:
    """Generate jest command variations.

    This generates various forms of jest commands including:
    - Direct invocation: jest
    - NPM invocation: npm test, npm run test, npm run jest
    - Yarn invocation: yarn test, yarn run test, yarn run jest
    - NPX invocation: npx jest
    - PNPM invocation: pnpm test, pnpm run test
    - With arguments: jest --coverage, jest tests/, jest --watch
    """
    # Base command variations
    base_commands = [
        "jest",
        "npm test",
        "npm run test",
        "npm run jest",
        "yarn test",
        "yarn run test",
        "yarn run jest",
        "npx jest",
        "pnpm test",
        "pnpm run test",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " --coverage",
            " --watch",
            " --watchAll",
            " tests/",
            " src/",
            " --verbose",
            " --silent",
            " --maxWorkers=4",
            " --testPathPattern=unit",
            " --bail",
            " --no-cache",
            " --updateSnapshot",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def vitest_command_strategy(draw: Any) -> str:
    """Generate vitest command variations.

    This generates various forms of vitest commands including:
    - Direct invocation: vitest
    - NPM invocation: npm run vitest
    - Yarn invocation: yarn run vitest
    - NPX invocation: npx vitest
    - PNPM invocation: pnpm run vitest
    - With arguments: vitest --run, vitest --coverage
    """
    # Base command variations
    base_commands = [
        "vitest",
        "npm run vitest",
        "yarn run vitest",
        "npx vitest",
        "pnpm run vitest",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " --run",
            " --coverage",
            " --watch",
            " tests/",
            " src/",
            " --reporter=verbose",
            " --silent",
            " --threads",
            " --no-threads",
            " --bail",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def mocha_command_strategy(draw: Any) -> str:
    """Generate mocha command variations.

    This generates various forms of mocha commands including:
    - Direct invocation: mocha
    - NPM invocation: npm run mocha
    - Yarn invocation: yarn run mocha
    - NPX invocation: npx mocha
    - PNPM invocation: pnpm run mocha
    - With arguments: mocha tests/, mocha --reporter spec
    """
    # Base command variations
    base_commands = [
        "mocha",
        "npm run mocha",
        "yarn run mocha",
        "npx mocha",
        "pnpm run mocha",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " tests/",
            " test/",
            " --reporter spec",
            " --reporter json",
            " --watch",
            " --recursive",
            " --grep pattern",
            " --bail",
            " --timeout 5000",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def ava_command_strategy(draw: Any) -> str:
    """Generate ava command variations.

    This generates various forms of ava commands including:
    - Direct invocation: ava
    - NPM invocation: npm run ava
    - Yarn invocation: yarn run ava
    - NPX invocation: npx ava
    - PNPM invocation: pnpm run ava
    - With arguments: ava --verbose, ava tests/
    """
    # Base command variations
    base_commands = [
        "ava",
        "npm run ava",
        "yarn run ava",
        "npx ava",
        "pnpm run ava",
    ]

    base = draw(st.sampled_from(base_commands))

    # Optional arguments
    add_args = draw(st.booleans())

    if add_args:
        args_options = [
            " --verbose",
            " --watch",
            " --fail-fast",
            " --serial",
            " --concurrency=5",
            " tests/",
            " test/",
            " --match='*unit*'",
        ]
        args = draw(st.sampled_from(args_options))
        return base + args

    return base


@st.composite
def javascript_test_command_strategy(draw: Any) -> str:
    """Generate any JavaScript/TypeScript test command."""
    command_type = draw(st.sampled_from(["jest", "vitest", "mocha", "ava"]))

    if command_type == "jest":
        return draw(jest_command_strategy())
    elif command_type == "vitest":
        return draw(vitest_command_strategy())
    elif command_type == "mocha":
        return draw(mocha_command_strategy())
    else:  # ava
        return draw(ava_command_strategy())


@st.composite
def non_test_javascript_command_strategy(draw: Any) -> str:
    """Generate JavaScript commands that are NOT test execution commands.

    This generates various non-test commands to ensure they don't
    incorrectly match test runner patterns.
    """
    non_test_commands = [
        "npm install",
        "npm run build",
        "npm run dev",
        "npm run start",
        "npm run lint",
        "npm install jest",
        "yarn install",
        "yarn add jest",
        "yarn build",
        "yarn dev",
        "pnpm install",
        "pnpm add vitest",
        "node index.js",
        "node --version",
        "npx create-react-app myapp",
        "npx eslint .",
        "tsc --build",
        "webpack --config webpack.config.js",
        "echo jest",
        "cat jest.config.js",
        "grep jest package.json",
        "which jest",
        "ls node_modules",
    ]

    return draw(st.sampled_from(non_test_commands))


# ============================================================================
# Property Tests
# ============================================================================


@given(command=jest_command_strategy())
@property_test_settings()
def test_property_2_jest_detection(command: str) -> None:
    """
    Property 2: Jest Command Detection.

    For any jest command variation, the test runner registry should
    correctly identify it as a JavaScript test execution command with the
    jest framework.

    Validates: Requirements 2.2
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Jest command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all jest command variations."
    )

    # Verify language is JavaScript
    assert language == "javascript", (
        f"Jest command '{command}' was detected with language '{language}' "
        f"instead of 'javascript'."
    )

    # Verify framework is jest
    assert framework == "jest", (
        f"Jest command '{command}' was detected with framework '{framework}' "
        f"instead of 'jest'."
    )


@given(command=vitest_command_strategy())
@property_test_settings()
def test_property_2_vitest_detection(command: str) -> None:
    """
    Property 2: Vitest Command Detection.

    For any vitest command variation, the test runner registry should
    correctly identify it as a JavaScript test execution command with the
    vitest framework.

    Validates: Requirements 2.2
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Vitest command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all vitest command variations."
    )

    # Verify language is JavaScript
    assert language == "javascript", (
        f"Vitest command '{command}' was detected with language '{language}' "
        f"instead of 'javascript'."
    )

    # Verify framework is vitest
    assert framework == "vitest", (
        f"Vitest command '{command}' was detected with framework '{framework}' "
        f"instead of 'vitest'."
    )


@given(command=mocha_command_strategy())
@property_test_settings()
def test_property_2_mocha_detection(command: str) -> None:
    """
    Property 2: Mocha Command Detection.

    For any mocha command variation, the test runner registry should
    correctly identify it as a JavaScript test execution command with the
    mocha framework.

    Validates: Requirements 2.2
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Mocha command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all mocha command variations."
    )

    # Verify language is JavaScript
    assert language == "javascript", (
        f"Mocha command '{command}' was detected with language '{language}' "
        f"instead of 'javascript'."
    )

    # Verify framework is mocha
    assert framework == "mocha", (
        f"Mocha command '{command}' was detected with framework '{framework}' "
        f"instead of 'mocha'."
    )


@given(command=ava_command_strategy())
@property_test_settings()
def test_property_2_ava_detection(command: str) -> None:
    """
    Property 2: Ava Command Detection.

    For any ava command variation, the test runner registry should
    correctly identify it as a JavaScript test execution command with the
    ava framework.

    Validates: Requirements 2.2
    """
    registry = TestRunnerRegistry()

    # Match the command
    is_match, language, framework = registry.match_command(command)

    # Verify it's detected as a test command
    assert is_match is True, (
        f"Ava command '{command}' was not detected as a test execution command. "
        f"The registry should recognize all ava command variations."
    )

    # Verify language is JavaScript
    assert language == "javascript", (
        f"Ava command '{command}' was detected with language '{language}' "
        f"instead of 'javascript'."
    )

    # Verify framework is ava
    assert framework == "ava", (
        f"Ava command '{command}' was detected with framework '{framework}' "
        f"instead of 'ava'."
    )


@given(command=non_test_javascript_command_strategy())
@property_test_settings()
def test_property_2_non_test_javascript_command_rejection(command: str) -> None:
    """
    Property 2: Non-Test JavaScript Command Rejection.

    For any JavaScript command that is NOT a test execution command, the test
    runner registry should NOT identify it as a test command.

    Validates: Requirements 2.2
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


@given(command=javascript_test_command_strategy())
@property_test_settings()
def test_property_2_dirty_state_cleared_by_javascript_test_execution(
    command: str,
) -> None:
    """
    Property 2: Test Execution Clears Dirty State (JavaScript).

    For any JavaScript test execution command, if the session is in dirty state,
    then processing the command should transition the state to clean.

    Validates: Requirements 2.2
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
    assert language == "javascript", f"Command '{command}' should be JavaScript"

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
    jest_cmd=jest_command_strategy(),
    vitest_cmd=vitest_command_strategy(),
)
@property_test_settings()
def test_property_2_multiple_javascript_test_runs_maintain_clean_state(
    jest_cmd: str,
    vitest_cmd: str,
) -> None:
    """
    Property 2: Multiple JavaScript Test Runs Maintain Clean State.

    For any sequence of JavaScript test execution commands in clean state,
    the state should remain clean without errors.

    Validates: Requirements 2.2, 8.1
    """
    registry = TestRunnerRegistry()
    state = TestExecutionSessionState()

    # Initially clean
    assert state.is_dirty is False, "Initial state should be clean"

    # Run first test (jest)
    is_match, _, _ = registry.match_command(jest_cmd)
    assert is_match is True, f"Command '{jest_cmd}' should match"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after first test"

    # Run second test (vitest)
    is_match, _, _ = registry.match_command(vitest_cmd)
    assert is_match is True, f"Command '{vitest_cmd}' should match"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after second test"

    # Run first test again
    is_match, _, _ = registry.match_command(jest_cmd)
    assert is_match is True, f"Command '{jest_cmd}' should match again"
    state.mark_clean()
    assert state.is_dirty is False, "State should remain clean after third test"


@given(
    modification_count=st.integers(min_value=1, max_value=10),
    test_command=javascript_test_command_strategy(),
)
@property_test_settings()
def test_property_2_javascript_state_transition_cycle(
    modification_count: int,
    test_command: str,
) -> None:
    """
    Property 2: JavaScript State Transition Cycle.

    For any session, if the sequence is: modify file -> run tests -> modify file,
    then the state transitions should be: clean -> dirty -> clean -> dirty.

    Validates: Requirements 2.2, 8.2
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


@given(command=javascript_test_command_strategy())
@property_test_settings()
def test_property_2_javascript_test_execution_in_clean_state(command: str) -> None:
    """
    Property 2: JavaScript Test Execution in Clean State.

    For any JavaScript test execution command in clean state, the state should
    remain clean (no state change).

    Validates: Requirements 2.2, 2.16
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
