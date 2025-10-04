"""
Test Pytest Compression Minimum Lines Threshold.

This test verifies that pytest compression is not applied when the output
has fewer lines than the configured threshold.
"""

import pytest
from src.core.domain.command_results import CommandResult
from src.core.domain.session import Session, SessionState
from src.core.services.response_manager_service import AgentResponseFormatter


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pytest_compression_below_threshold():
    """
    Test that compression is NOT applied when output is below the threshold.
    """

    # Arrange - Create session with compression enabled and threshold of 30 lines
    session_id = "threshold-test-session"
    session_state = SessionState(
        pytest_compression_enabled=True,
        compress_next_tool_call_reply=True,
        pytest_compression_min_lines=30,  # Set threshold to 30 lines
    )
    session = Session(session_id=session_id, agent="cline", state=session_state)
    formatter = AgentResponseFormatter()

    # Create pytest output that is BELOW the threshold (only 15 lines)
    short_pytest_output = """============================= test session starts ==============================
platform linux -- Python 3.9.0, pytest-6.2.5, py-1.10.0, pluggy-0.13.1
cachedir .pytest_cache
rootdir: /test/project
collected 1 item

test_simple.py::test_example PASSED                                        [100%]

============================== 1 passed in 0.01s ================================"""

    # Create a command result with the short pytest output
    command_result = CommandResult(
        success=True,
        message=short_pytest_output,
        name="bash",
        data={"command": "python -m pytest test_simple.py -v"},
    )

    # Act - Process through the compression formatter
    compressed_output = formatter._apply_pytest_compression_sync(
        command_result.name, command_result.message, session
    )

    # Assert - Verify NO compression was applied
    original_lines = len(short_pytest_output.split("\n"))
    compressed_lines = len(compressed_output.split("\n"))

    print(f"Original output: {original_lines} lines")
    print(f"Compressed output: {compressed_lines} lines")
    print("Threshold: 30 lines")

    # Should have same number of lines (no compression applied)
    assert (
        compressed_lines == original_lines
    ), "Output should NOT be compressed when below threshold"
    assert (
        compressed_output == short_pytest_output
    ), "Output should be identical when below threshold"
    assert (
        "PASSED" in compressed_output
    ), "PASSED lines should be preserved when below threshold"

    print(
        "PASSED: Threshold test passed - compression correctly skipped for short output"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pytest_compression_above_threshold():
    """
    Test that compression IS applied when output is above the threshold.
    """

    # Arrange - Create session with compression enabled and threshold of 10 lines
    session_id = "above-threshold-test-session"
    session_state = SessionState(
        pytest_compression_enabled=True,
        compress_next_tool_call_reply=True,
        pytest_compression_min_lines=10,  # Set low threshold of 10 lines
    )
    session = Session(session_id=session_id, agent="cline", state=session_state)
    formatter = AgentResponseFormatter()

    # Create pytest output that is ABOVE the threshold (25 lines)
    long_pytest_output = """============================= test session starts ==============================
platform linux -- Python 3.9.0, pytest-6.2.5, py-1.10.0, pluggy-0.13.1
cachedir .pytest_cache
rootdir: /test/project
collected 5 items

test_module.py::test_addition PASSED                                        [ 20%]
test_module.py::test_subtraction FAILED                                      [ 40%]
test_module.py::test_multiplication PASSED                                   [ 60%]
test_module.py::test_division FAILED                                         [ 80%]
test_module.py::test_modulo PASSED                                          [100%]

=================================== FAILURES ===================================
_____________________________ test_subtraction _____________________________

    def test_subtraction():
        result = 5 - 3
>       assert result == 3  # This fails
E       assert 2 == 3

test_module.py:8: AssertionError
___________________________ test_division ___________________________

    def test_division():
>       result = 10 / 0
E       ZeroDivisionError: division by zero

test_module.py:15: ZeroDivisionError
========================= short test summary info ==========================
FAILED test_module.py::test_subtraction - assert 2 == 3
FAILED test_module.py::test_division - ZeroDivisionError: division by zero
=================== 3 passed, 2 failed in 0.03s ===================="""

    # Create a command result with the long pytest output
    command_result = CommandResult(
        success=True,
        message=long_pytest_output,
        name="bash",
        data={"command": "python -m pytest test_module.py -v"},
    )

    # Act - Process through the compression formatter
    compressed_output = formatter._apply_pytest_compression_sync(
        command_result.name, command_result.message, session
    )

    # Assert - Verify compression WAS applied
    original_lines = len(long_pytest_output.split("\n"))
    compressed_lines = len(compressed_output.split("\n"))

    print(f"Original output: {original_lines} lines")
    print(f"Compressed output: {compressed_lines} lines")
    print("Threshold: 10 lines")

    # Should have fewer lines (compression applied)
    assert (
        compressed_lines < original_lines
    ), "Output should be compressed when above threshold"
    assert (
        compressed_output != long_pytest_output
    ), "Output should be different when compressed"

    # PASSED lines should be filtered out
    assert "PASSED [ 20%]" not in compressed_output, "PASSED lines should be filtered"
    assert "PASSED [ 60%]" not in compressed_output, "PASSED lines should be filtered"
    assert "PASSED [100%]" not in compressed_output, "PASSED lines should be filtered"

    # FAILED lines and errors should be preserved
    assert "FAILED [ 40%]" in compressed_output, "FAILED lines should be preserved"
    assert "FAILED [ 80%]" in compressed_output, "FAILED lines should be preserved"
    assert "assert 2 == 3" in compressed_output, "Error details should be preserved"
    assert "ZeroDivisionError" in compressed_output, "Error details should be preserved"

    # Summary should be preserved
    assert (
        "3 passed, 2 failed in 0.03s" in compressed_output
    ), "Summary should be preserved"

    print(
        "PASSED: Above threshold test passed - compression correctly applied for long output"
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_pytest_compression_environment_variable_override():
    """
    Test that environment variable PYTEST_COMPRESSION_MIN_LINES can override the threshold.
    """

    # Arrange - Set environment variable
    import os

    original_env = os.environ.get("PYTEST_COMPRESSION_MIN_LINES")
    os.environ["PYTEST_COMPRESSION_MIN_LINES"] = "20"  # Set threshold to 20 lines

    try:
        # Create session with different threshold in session state
        session_id = "env-override-test-session"
        session_state = SessionState(
            pytest_compression_enabled=True,
            compress_next_tool_call_reply=True,
            pytest_compression_min_lines=10,  # Session state says 10, but env var says 20
        )
        session = Session(session_id=session_id, agent="cline", state=session_state)
        formatter = AgentResponseFormatter()

        # Create pytest output with 15 lines (between session threshold and env threshold)
        medium_pytest_output = """============================= test session starts ==============================
platform linux -- Python 3.9.0, pytest-6.2.5, py-1.10.0, pluggy-0.13.1
cachedir .pytest_cache
rootdir: /test/project
collected 3 items

test_example.py::test_one PASSED                                         [ 33%]
test_example.py::test_two FAILED                                         [ 66%]
test_example.py::test_three PASSED                                       [100%]

=================================== FAILURES ===================================
_____________________________ test_two _____________________________

    def test_two():
>       assert False
E   AssertionError

test_example.py:8: AssertionError
========================= short test summary info ==========================
FAILED test_example.py::test_two - AssertionError
=================== 2 passed, 1 failed in 0.02s ===================="""

        # Create a command result
        command_result = CommandResult(
            success=True,
            message=medium_pytest_output,
            name="bash",
            data={"command": "python -m pytest test_example.py -v"},
        )

        # Act - Process through the compression formatter
        compressed_output = formatter._apply_pytest_compression_sync(
            command_result.name, command_result.message, session
        )

        # Assert - Verify compression behavior
        original_lines = len(medium_pytest_output.split("\n"))
        compressed_lines = len(compressed_output.split("\n"))

        print(f"Original output: {original_lines} lines")
        print(f"Compressed output: {compressed_lines} lines")
        print("Session threshold: 10 lines")
        print("Environment threshold: 20 lines")

        # With 15 lines:
        # - Above session threshold (10) -> would compress
        # - Below environment threshold (20) -> would not compress
        # The environment variable should take precedence

        # Environment variable should override session state
        assert (
            compressed_lines == original_lines
        ), "Environment variable threshold should override session state value"
        print(
            "PASSED: Environment variable override test passed - no compression applied due to env threshold"
        )

    finally:
        # Cleanup - restore original environment variable
        if original_env is not None:
            os.environ["PYTEST_COMPRESSION_MIN_LINES"] = original_env
        else:
            os.environ.pop("PYTEST_COMPRESSION_MIN_LINES", None)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_compression_disabled_respects_threshold():
    """
    Test that when compression is disabled, threshold is ignored.
    """

    # Arrange - Create session with compression DISABLED
    session_id = "disabled-threshold-test-session"
    session_state = SessionState(
        pytest_compression_enabled=False,  # Compression disabled
        compress_next_tool_call_reply=True,
        pytest_compression_min_lines=5,  # Low threshold
    )
    session = Session(session_id=session_id, agent="cline", state=session_state)
    formatter = AgentResponseFormatter()

    # Create pytest output with many lines (would normally be compressed)
    long_pytest_output = """============================= test session starts ==============================
platform linux -- Python 3.9.0, pytest-6.2.5, py-1.10.0, pluggy-0.13.1
cachedir .pytest_cache
rootdir: /test/project
collected 3 items

test_example.py::test_one PASSED                                         [ 33%]
test_example.py::test_two FAILED                                         [ 66%]
test_example.py::test_three PASSED                                       [100%]

=================================== FAILURES ===================================
_____________________________ test_two _____________________________

    def test_two():
>       assert False
E   AssertionError

test_example.py:8: AssertionError
========================= short test summary info ==========================
FAILED test_example.py::test_two - AssertionError
=================== 2 passed, 1 failed in 0.02s ===================="""

    # Create a command result
    command_result = CommandResult(
        success=True,
        message=long_pytest_output,
        name="bash",
        data={"command": "python -m pytest test_example.py -v"},
    )

    # Act - Process through the compression formatter
    compressed_output = formatter._apply_pytest_compression_sync(
        command_result.name, command_result.message, session
    )

    # Assert - Verify NO compression was applied (because compression is disabled)
    assert (
        compressed_output == long_pytest_output
    ), "Output should not be compressed when compression is disabled"
    assert (
        "PASSED" in compressed_output
    ), "PASSED lines should be preserved when compression is disabled"

    print(
        "PASSED: Disabled compression test passed - threshold ignored when compression disabled"
    )
