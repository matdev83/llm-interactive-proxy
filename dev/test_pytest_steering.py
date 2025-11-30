"""Quick test script to demonstrate pytest full-suite steering feature.

Run this with:
    .venv\Scripts\python.exe test_pytest_steering.py
"""

import asyncio
from src.core.services.tool_call_handlers.pytest_full_suite_handler import (
    PytestFullSuiteHandler,
)
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext


async def test_steering_feature() -> None:
    """Demonstrate the pytest full-suite steering feature."""
    
    # Create handler with custom message
    handler = PytestFullSuiteHandler(
        enabled=True,
        message="⚠️ You're about to run the ENTIRE test suite! This may take a while. "
                "Consider running specific tests instead (e.g., pytest tests/unit/test_file.py). "
                "If you really need the full suite, re-send the same command."
    )
    
    print("=" * 70)
    print("PYTEST FULL-SUITE STEERING DEMONSTRATION")
    print("=" * 70)
    
    # Test 1: Full suite command (should be swallowed)
    print("\n[Test 1] LLM tries to run: pytest")
    context1 = ToolCallContext(
        session_id="demo-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest"},
    )
    
    can_handle = await handler.can_handle(context1)
    print(f"  Handler can_handle: {can_handle}")
    
    result1 = await handler.handle(context1)
    print(f"  Should swallow: {result1.should_swallow}")
    if result1.replacement_response:
        print(f"  Steering message: {result1.replacement_response[:100]}...")
    
    # Test 2: Same command again (should be allowed)
    print("\n[Test 2] LLM re-issues the same command: pytest")
    context2 = ToolCallContext(
        session_id="demo-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest"},
    )
    
    can_handle = await handler.can_handle(context2)
    print(f"  Handler can_handle: {can_handle}")
    
    result2 = await handler.handle(context2)
    print(f"  Should swallow: {result2.should_swallow}")
    print(f"  ✓ Command allowed to execute!")
    
    # Test 3: Targeted test (should pass through)
    print("\n[Test 3] LLM runs targeted test: pytest tests/unit/test_cli.py")
    context3 = ToolCallContext(
        session_id="demo-session",
        backend_name="test-backend",
        model_name="test-model",
        full_response={},
        tool_name="bash",
        tool_arguments={"command": "pytest tests/unit/test_cli.py"},
    )
    
    can_handle = await handler.can_handle(context3)
    print(f"  Handler can_handle: {can_handle}")
    
    result3 = await handler.handle(context3)
    print(f"  Should swallow: {result3.should_swallow}")
    print(f"  ✓ Targeted test passed through immediately!")
    
    # Test 4: Other variations
    print("\n[Test 4] Testing various pytest invocations:")
    test_commands = [
        ("pytest .", True, "Current directory (full suite)"),
        ("pytest -k slow", False, "With marker filter"),
        ("pytest tests", False, "Specific directory"),
        ("python -m pytest", True, "Python module invocation"),
        ("pytest --lf", False, "Last failed only"),
    ]
    
    for cmd, should_swallow, description in test_commands:
        ctx = ToolCallContext(
            session_id=f"test-{cmd}",
            backend_name="test-backend",
            model_name="test-model",
            full_response={},
            tool_name="bash",
            tool_arguments={"command": cmd},
        )
        result = await handler.handle(ctx)
        status = "🚫 SWALLOWED" if result.should_swallow else "✓ ALLOWED"
        print(f"  {status:15} | {cmd:30} | {description}")
    
    print("\n" + "=" * 70)
    print("DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(test_steering_feature())
