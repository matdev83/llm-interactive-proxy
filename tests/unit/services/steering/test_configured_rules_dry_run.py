"""Tests for ConfiguredRulesPolicy dry_run behavior."""

import pytest
from src.core.interfaces.tool_call_reactor_interface import ToolCallContext
from src.services.steering import SessionStateStore
from src.services.steering.models import SteeringRule
from src.services.steering.policies import ConfiguredRulesPolicy



@pytest.fixture
def context():
    return ToolCallContext(
        session_id="test_session",
        backend_name="test_backend",
        model_name="test_model",
        full_response={},
        tool_name="shell",
        tool_arguments={"command": "rm -rf /"},
        calling_agent="agent1",
    )


@pytest.mark.asyncio
async def test_dry_run_no_side_effects(context):
    """Test that dry_run=True does not record hits."""
    store = SessionStateStore()

    rules = [
        SteeringRule(
            name="limit_rule",
            enabled=True,
            triggers={"phrases": ["rm -rf"]},
            message="blocked",
            priority=100,
            rate_limit={"calls_per_window": 1, "window_seconds": 60},
        )
    ]


    policy = ConfiguredRulesPolicy(session_store=store, rules=rules, enabled=True)

    # 1. Evaluate with dry_run=True (e.g. can_handle check)
    result = await policy.evaluate(context, "rm -rf /", dry_run=True)
    assert result is not None
    assert result.should_block is True

    # Check that NO hits were recorded
    key = "rule_hits:limit_rule"
    hits = await store.get("test_session", key)
    assert hits is None or len(hits) == 0

    # 2. Evaluate with dry_run=False (actual handle)
    result = await policy.evaluate(context, "rm -rf /", dry_run=False)
    assert result is not None

    # Check that ONE hit was recorded
    hits = await store.get("test_session", key)
    assert len(hits) == 1

    # 3. Evaluate again with dry_run=False (should be blocked by rate limit?)
    # Wait, rate limit is "calls per window".
    # If limit is 1, and we have 1 hit, is it blocked?
    # "return len(valid_hits) < rule.calls_per_window"
    # 1 < 1 is False. So it returns None (Allowed pass through).

    # Wait, steering logic usually swallows IF match AND within limit (i.e. we are steering).
    # If we exceeded limit, we stop steering (allow pass through)?
    # "Controls how often steering messages are shown"
    # So if we show it once, we stop showing it? Yes.

    result = await policy.evaluate(context, "rm -rf /", dry_run=False)
    assert result is None  # Pass through

    # Check hits count is still 1 (because we didn't record hit if we returned None)
    # Actually, the logic is:
    # if not within_limit: return None
    # if not dry_run: record_hit
    # So if we exceed limit, we return None and DON'T record hit.
    # This prevents counting the allowed calls against the limit?
    # Or rather, we only count the STEERING actions.
    # This seems correct for "show message X times".

    hits = await store.get("test_session", key)
    assert len(hits) == 1
