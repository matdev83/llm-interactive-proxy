from __future__ import annotations

from typing import Any, cast

import pytest
from src.core.common.exceptions import AuthenticationError, BackendError, RoutingError
from src.core.domain.chat import CanonicalChatRequest, ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.composite_failure_recovery_bridge import (
    CompositeFailureRecoveryBridge,
)
from src.core.services.weighted_branch_selector import WeightedBranchSelector


def _request() -> CanonicalChatRequest:
    return cast(
        CanonicalChatRequest,
        ChatRequest(
            model="openai:gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            extra_body={"backend_type": "openai", "_resolved_uri_params": {"a": "1"}},
        ),
    )


def _context() -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-composite-bridge",
        session_id="sess-composite-bridge",
    )


def _weighted_state() -> dict[str, Any]:
    return {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "openai:gpt-4", "weight": 1},
            {"selector": "anthropic:claude-3-5-sonnet", "weight": 2},
            {"selector": "gemini:gemini-2.0-flash", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "openai:gpt-4",
        "hop_count": 0,
        "max_hops": 3,
    }


def test_build_next_request_weighted_retry_excludes_failed_selector_and_rerolls() -> (
    None
):
    bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=lambda: 0.99
        )
    )
    context = _context()
    context.extensions["composite_routing_state"] = _weighted_state()

    next_request = bridge.build_next_request(
        request=_request(),
        context=context,
        content_started=False,
        error=BackendError("backend down", "openai", status_code=503),
    )

    assert next_request is not None
    assert next_request.model == "gemini:gemini-2.0-flash"
    assert next_request.extra_body is not None
    assert next_request.extra_body["backend_type"] == "gemini"
    assert next_request.extra_body["_resolved_uri_params"] == {}

    state_raw = context.extensions["composite_routing_state"]
    assert isinstance(state_raw, dict)
    assert state_raw["selected_selector"] == "gemini:gemini-2.0-flash"
    assert state_raw["excluded_selectors"] == ["openai:gpt-4"]
    assert state_raw["hop_count"] == 1


def test_build_next_request_weighted_retry_directly_routes_single_remaining_selector() -> (
    None
):
    def _unexpected_rng() -> float:
        raise AssertionError("random selection should not run for a single candidate")

    bridge = CompositeFailureRecoveryBridge(
        weighted_branch_selector=WeightedBranchSelector(
            random_value_provider=_unexpected_rng
        )
    )
    context = _context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "openai:gpt-4", "weight": 1},
            {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "openai:gpt-4",
        "hop_count": 0,
        "max_hops": 3,
    }

    next_request = bridge.build_next_request(
        request=_request(),
        context=context,
        content_started=False,
        error=BackendError("backend down", "openai", status_code=500),
    )

    assert next_request is not None
    assert next_request.model == "anthropic:claude-3-5-sonnet"
    assert next_request.extra_body is not None
    assert next_request.extra_body["backend_type"] == "anthropic"
    state_raw = context.extensions["composite_routing_state"]
    assert isinstance(state_raw, dict)
    assert state_raw["selected_selector"] == "anthropic:claude-3-5-sonnet"
    assert state_raw["excluded_selectors"] == ["openai:gpt-4"]
    assert state_raw["hop_count"] == 1


def test_build_next_request_weighted_retry_returns_none_for_authentication_errors() -> (
    None
):
    bridge = CompositeFailureRecoveryBridge()
    context = _context()
    context.extensions["composite_routing_state"] = _weighted_state()

    next_request = bridge.build_next_request(
        request=_request(),
        context=context,
        content_started=False,
        error=AuthenticationError("invalid token"),
    )

    assert next_request is None
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["selected_selector"] == "openai:gpt-4"
    assert state["excluded_selectors"] == []
    assert state["hop_count"] == 0


def test_build_next_request_weighted_retry_recycles_candidates_within_budget() -> None:
    bridge = CompositeFailureRecoveryBridge()
    context = _context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "openai:gpt-4", "weight": 1},
            {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
        ],
        "excluded_selectors": ["openai:gpt-4"],
        "selected_selector": "anthropic:claude-3-5-sonnet",
        "hop_count": 0,
        "max_hops": 3,
    }

    next_request = bridge.build_next_request(
        request=_request(),
        context=context,
        content_started=False,
        error=BackendError("secondary down", "anthropic", status_code=500),
    )

    assert next_request is not None
    assert next_request.model == "openai:gpt-4"
    assert next_request.extra_body is not None
    assert next_request.extra_body["backend_type"] == "openai"
    state = cast(dict[str, Any], context.extensions["composite_routing_state"])
    assert state["excluded_selectors"] == ["anthropic:claude-3-5-sonnet"]
    assert state["selected_selector"] == "openai:gpt-4"
    assert state["hop_count"] == 1


def test_build_next_request_weighted_retry_raises_when_budget_is_spent() -> None:
    bridge = CompositeFailureRecoveryBridge()
    context = _context()
    context.extensions["composite_routing_state"] = {
        "mode": "weighted_retry",
        "branches": [
            {"selector": "openai:gpt-4", "weight": 1},
            {"selector": "anthropic:claude-3-5-sonnet", "weight": 1},
        ],
        "excluded_selectors": [],
        "selected_selector": "openai:gpt-4",
        "hop_count": 1,
        "max_hops": 1,
    }

    with pytest.raises(RoutingError) as exc_info:
        bridge.build_next_request(
            request=_request(),
            context=context,
            content_started=False,
            error=BackendError("down", "openai", status_code=500),
        )

    assert exc_info.value.details["reason"] == "attempt_budget_exhausted"
