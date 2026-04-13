"""Tests for UnifiedSteeringHandler."""

import logging
from unittest.mock import AsyncMock

import pytest
from src.core.interfaces.tool_call_reactor_interface import (
    ToolCallContext,
)
from src.services.steering import (
    ISteeringPolicy,
    SteeringResult,
    UnifiedSteeringHandler,
)


class MockPolicy(ISteeringPolicy):
    def __init__(self, name, priority, result=None, trigger=False):
        self._name = name
        self._priority = priority
        self._result = result
        self._trigger = trigger
        self.evaluate = AsyncMock(side_effect=self._evaluate_impl)

    @property
    def name(self):
        return self._name

    @property
    def priority(self):
        return self._priority

    # Define abstract method to satisfy ABC
    async def evaluate(self, context, command, dry_run=False):
        # This will be shadowed by the instance attribute in __init__
        # But we need it here for ABC instantiation check.
        pass

    async def _evaluate_impl(self, context, command, dry_run=False):
        if self._trigger:
            return self._result
        return None


@pytest.fixture
def context():
    return ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="shell",
        tool_arguments={"command": "echo test"},
        calling_agent="agent1",
    )


@pytest.mark.asyncio
async def test_policy_ordering(context):
    """Test that policies are evaluated in priority order."""
    p1 = MockPolicy("low_prio", priority=10, trigger=True, result=SteeringResult("low"))
    p2 = MockPolicy(
        "high_prio", priority=90, trigger=True, result=SteeringResult("high")
    )

    handler = UnifiedSteeringHandler(policies=[p1, p2])

    result = await handler.handle(context)

    assert result.should_swallow is True
    assert result.replacement_response == "high"
    assert result.metadata["matched_policy"] == "high_prio"

    # Verify p2 was called first
    # We can't strict verify call order on mocks easily without manager,
    # but the result proves p2 won despite both triggering.


@pytest.mark.asyncio
async def test_policy_ordering_with_overrides(context):
    """Test that policy priorities can be overridden."""
    # p1 normally low (10), p2 normally high (90)
    p1 = MockPolicy("p1", priority=10, trigger=True, result=SteeringResult("p1"))
    p2 = MockPolicy("p2", priority=90, trigger=True, result=SteeringResult("p2"))

    # Override p1 to be 100 (higher than p2)
    overrides = {"p1": 100}

    handler = UnifiedSteeringHandler(policies=[p1, p2], priority_overrides=overrides)

    result = await handler.handle(context)

    # p1 should win now
    assert result.should_swallow is True
    assert result.replacement_response == "p1"
    assert result.metadata["matched_policy"] == "p1"


@pytest.mark.asyncio
async def test_short_circuit(context):
    """Test that evaluation stops after first match."""
    p1 = MockPolicy("high_prio", 100, trigger=True, result=SteeringResult("match"))
    p2 = MockPolicy("lower_prio", 50, trigger=True, result=SteeringResult("ignored"))

    handler = UnifiedSteeringHandler(policies=[p1, p2])

    await handler.handle(context)

    # p1 called with dry_run=False
    p1.evaluate.assert_called_with(context, "echo test", dry_run=False)
    p2.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_no_match_pass_through(context):
    """Test that if no policy matches, result passes through."""
    p1 = MockPolicy("p1", 10, trigger=False)

    handler = UnifiedSteeringHandler(policies=[p1])

    result = await handler.handle(context)

    assert result.should_swallow is False
    assert result.replacement_response is None


@pytest.mark.asyncio
async def test_policy_error_handling(context, caplog):
    """Test that policy errors are caught and logged, continuing to next policy."""
    p1 = MockPolicy("error_policy", 100)
    p1.evaluate.side_effect = Exception("Boom")

    p2 = MockPolicy("backup_policy", 50, trigger=True, result=SteeringResult("safe"))

    handler = UnifiedSteeringHandler(policies=[p1, p2])

    with caplog.at_level(logging.ERROR):
        result = await handler.handle(context)

    assert result.should_swallow is True
    assert result.replacement_response == "safe"
    assert "Policy error_policy raised exception" in caplog.text


@pytest.mark.asyncio
async def test_telemetry_structured_log_on_steering(context, caplog):
    """Structured unified steering telemetry is logged on a steering outcome."""
    p1 = MockPolicy("match_policy", 50, trigger=True, result=SteeringResult("steered"))

    handler = UnifiedSteeringHandler(policies=[p1])

    with caplog.at_level(logging.INFO):
        await handler.handle(context)

    assert "Unified steering evaluation" in caplog.text
    assert "'matched_policy': 'match_policy'" in caplog.text
    assert (
        "Steering via rule 'match_policy' for tool 'shell' in session test_session"
        not in caplog.text
    )
