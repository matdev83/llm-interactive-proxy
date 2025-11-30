"""Integration test for pytest full-suite steering feature.

This test demonstrates the feature working in a realistic scenario
with the full proxy stack.

Run with:
    .venv\Scripts\python.exe -m pytest test_pytest_steering_integration.py -v -s
"""

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
    PytestFullSuiteHandler,
)


class TestPytestFullSuiteSteering:
    """Integration tests for pytest full-suite steering."""

    @pytest.fixture
    def handler(self) -> PytestFullSuiteHandler:
        """Create a handler with custom message."""
        return PytestFullSuiteHandler(
            enabled=True,
            message=(
                "⚠️ FULL TEST SUITE DETECTED\n\n"
                "Running the entire test suite may take several minutes.\n"
                "Consider running specific tests instead:\n"
                "  - pytest tests/unit/test_file.py\n"
                "  - pytest -k 'test_pattern'\n\n"
                "To proceed with the full suite, re-send this command."
            ),
        )

    @pytest.mark.asyncio
    async def test_realistic_workflow(self, handler: PytestFullSuiteHandler) -> None:
        """Test a realistic workflow with an LLM agent."""
        session_id = "agent-session-123"

        # Scenario 1: Agent tries to run full suite
        print("\n[Scenario 1] Agent: 'Let me run all tests to verify everything works'")
        context1 = ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4o",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )

        result1 = await handler.handle(context1)
        assert result1.should_swallow is True
        assert "FULL TEST SUITE DETECTED" in result1.replacement_response
        print(f"✓ Proxy: Swallowed command and returned steering message")
        print(f"  Message preview: {result1.replacement_response[:80]}...")

        # Scenario 2: Agent acknowledges and tries again
        print("\n[Scenario 2] Agent: 'I understand, but I really need to run all tests'")
        context2 = ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4o",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )

        result2 = await handler.handle(context2)
        assert result2.should_swallow is False
        print(f"✓ Proxy: Allowed command to execute")

        # Scenario 3: Agent learns and runs targeted test
        print("\n[Scenario 3] Agent: 'Actually, let me just test the CLI module'")
        context3 = ToolCallContext(
            session_id=session_id,
            backend_name="openai",
            model_name="gpt-4o",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest tests/unit/test_cli.py"},
        )

        result3 = await handler.handle(context3)
        assert result3.should_swallow is False
        print(f"✓ Proxy: Passed through immediately (targeted test)")

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, handler: PytestFullSuiteHandler) -> None:
        """Test that sessions are isolated."""
        print("\n[Multi-Session Test]")

        # Session 1 gets warning
        ctx1 = ToolCallContext(
            session_id="session-1",
            backend_name="openai",
            model_name="gpt-4o",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )
        result1 = await handler.handle(ctx1)
        assert result1.should_swallow is True
        print("✓ Session 1: Got steering message")

        # Session 2 also gets warning (independent)
        ctx2 = ToolCallContext(
            session_id="session-2",
            backend_name="openai",
            model_name="gpt-4o",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )
        result2 = await handler.handle(ctx2)
        assert result2.should_swallow is True
        print("✓ Session 2: Got steering message (independent)")

        # Session 1 re-issues (allowed)
        result3 = await handler.handle(ctx1)
        assert result3.should_swallow is False
        print("✓ Session 1: Re-issue allowed")

        # Session 2 still needs to re-issue
        result4 = await handler.handle(ctx2)
        assert result4.should_swallow is False
        print("✓ Session 2: Re-issue allowed")

    @pytest.mark.asyncio
    async def test_various_invocations(self, handler: PytestFullSuiteHandler) -> None:
        """Test detection of various pytest invocation styles."""
        print("\n[Invocation Style Tests]")

        test_cases = [
            # (command, should_swallow, description)
            ("pytest", True, "Plain pytest"),
            ("python -m pytest", True, "Python module"),
            ("py.test", True, "Legacy py.test"),
            (".venv/Scripts/python.exe -m pytest", True, "Full path python"),
            ("pipenv run pytest", True, "Pipenv wrapper"),
            ("poetry run pytest", True, "Poetry wrapper"),
            ("pytest .", True, "Current directory"),
            ("pytest -v", True, "With verbose flag"),
            ("pytest --maxfail=1", True, "With maxfail"),
            ("pytest tests/unit", False, "Specific directory"),
            ("pytest tests/unit/test_cli.py", False, "Specific file"),
            ("pytest -k slow", False, "With marker"),
            ("pytest --lf", False, "Last failed"),
            ("pytest tests/unit/test_cli.py::test_parse_args", False, "Node selection"),
        ]

        for command, should_swallow, description in test_cases:
            ctx = ToolCallContext(
                session_id=f"test-{command}",
                backend_name="test",
                model_name="test",
                full_response={},
                tool_name="bash",
                tool_arguments={"command": command},
            )
            result = await handler.handle(ctx)
            status = "🚫 SWALLOW" if should_swallow else "✓ ALLOW"
            actual = "🚫 SWALLOW" if result.should_swallow else "✓ ALLOW"

            assert result.should_swallow == should_swallow, (
                f"Failed for '{command}': expected {status}, got {actual}"
            )
            print(f"  {status:12} | {command:45} | {description}")

    @pytest.mark.asyncio
    async def test_disabled_handler(self) -> None:
        """Test that disabled handler passes everything through."""
        print("\n[Disabled Handler Test]")

        handler = PytestFullSuiteHandler(enabled=False)

        ctx = ToolCallContext(
            session_id="test",
            backend_name="test",
            model_name="test",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": "pytest"},
        )

        result = await handler.handle(ctx)
        assert result.should_swallow is False
        print("✓ Disabled handler passes through all commands")


if __name__ == "__main__":
    # Run with: python test_pytest_steering_integration.py
    pytest.main([__file__, "-v", "-s"])
