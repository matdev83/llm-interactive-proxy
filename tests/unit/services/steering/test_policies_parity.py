"""Tests for Steering Policies Parity."""

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.steering import SessionStateStore
from src.services.steering.models import SteeringRule
from src.services.steering.policies import (
    ConfiguredRulesPolicy,
    InlinePythonPolicy,
    PytestFullSuitePolicy,
)


@pytest.fixture
def context():
    return ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="shell",
        tool_arguments={"command": ""},
        calling_agent="agent1",
    )


@pytest.mark.asyncio
async def test_inline_python_policy(context):
    """Verify inline python blocking logic."""
    policy = InlinePythonPolicy(enabled=True)

    # Test matching command
    context.tool_arguments = {"command": 'python -c "import os"'}
    result = await policy.evaluate(context, 'python -c "import os"')

    assert result is not None
    assert result.should_block is True
    assert "inline Python" in result.message

    # Test safe command
    context.tool_arguments = {"command": "python script.py"}
    result = await policy.evaluate(context, "python script.py")
    assert result is None


@pytest.mark.asyncio
async def test_pytest_full_suite_policy():
    """Verify pytest full suite warning logic."""
    store = SessionStateStore()
    policy = PytestFullSuitePolicy(session_store=store, enabled=True)

    ctx = ToolCallContext(
        session_id="s1",
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="shell",
        tool_arguments={"command": "pytest"},
        calling_agent="a1",
    )

    # First attempt: should warn
    result = await policy.evaluate(ctx, "pytest")
    assert result is not None
    assert result.should_block is True
    assert "whole test suite" in result.message

    # Second attempt (same command): should allow
    result = await policy.evaluate(ctx, "pytest")
    assert result is None

    # Different command (full suite): should warn again?
    # Logic is: if last_command == current, allow.
    # So if I run pytest again, it allows.
    # If I run pytest . it's different string, so warns.

    result = await policy.evaluate(ctx, "pytest .")
    assert result is not None
    assert result.should_block is True


@pytest.mark.asyncio
async def test_configured_rules_policy(context):
    """Verify configured rules application."""
    rules = [
        SteeringRule(
            name="no_rm_rf",
            enabled=True,
            triggers={"phrases": ["rm -rf /"]},
            message="Do not delete root",
            priority=100,
            rate_limit={"calls_per_window": 1, "window_seconds": 60},
        )
    ]

    policy = ConfiguredRulesPolicy(
        session_store=SessionStateStore(), rules=rules, enabled=True
    )

    # Test trigger
    context.tool_arguments = {"command": "sudo rm -rf /"}
    result = await policy.evaluate(context, "sudo rm -rf /")

    assert result is not None
    assert result.should_block is True
    assert result.message == "Do not delete root"

    # Test rate limit (swallows first call, checks second call)
    # The policy implementation checks rate limit BEFORE returning result.
    # Wait, the implementation returns None if rate limit exceeded?
    # No, usually rate limiting allows X calls per window.
    # For STEERING, usually we want to SHOW the message (block) X times?
    # Or show the message at most X times?
    # If we block, we show the message.
    # If rate limit exceeded (i.e. we steered too much recently), do we STOP steering (allow)?
    # ConfigSteeringHandler logic:
    # return self._within_rate_limit(rule, context.session_id)
    # If within limit: record hit, return result (Block).
    # If NOT within limit (limit exceeded): return False (Allow/Pass through).

    # So if calls_per_window=1:
    # 1st call: within limit -> Block.
    # 2nd call: limit exceeded -> Allow.

    result2 = await policy.evaluate(context, "sudo rm -rf /")
    assert result2 is None  # Allowed because rate limit (1 per 60s) exceeded
