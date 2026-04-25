from __future__ import annotations

from src.core.common.client_compatibility import resolve_client_reasoning_policy
from src.core.config.models.session import (
    ClientCompatibilityConfig,
    ClientCompatibilityRule,
)


class TestClientCompatibility:
    def test_defaults_passthrough_but_not_meaningful(self) -> None:
        policy = resolve_client_reasoning_policy(
            headers={},
            client_config=ClientCompatibilityConfig(),
            user_agent=None,
        )
        assert policy.reasoning_mode == "passthrough"
        assert policy.reasoning_counts_as_meaningful is False

    def test_header_passthrough_implies_meaningful(self) -> None:
        policy = resolve_client_reasoning_policy(
            headers={
                "x-llmproxy-reasoning-mode": "passthrough",
            },
            client_config=ClientCompatibilityConfig(),
            user_agent=None,
        )
        assert policy.reasoning_mode == "passthrough"
        assert policy.reasoning_counts_as_meaningful is True

    def test_header_can_override_meaningful_flag(self) -> None:
        policy = resolve_client_reasoning_policy(
            headers={
                "x-llmproxy-reasoning-mode": "passthrough",
                "x-llmproxy-reasoning-meaningful": "false",
            },
            client_config=ClientCompatibilityConfig(),
            user_agent=None,
        )
        assert policy.reasoning_mode == "passthrough"
        assert policy.reasoning_counts_as_meaningful is False

    def test_user_agent_rule_applies_when_no_header(self) -> None:
        cfg = ClientCompatibilityConfig(
            user_agent_rules=[
                ClientCompatibilityRule(
                    name="test-client",
                    user_agent_regex=r"^TestClient/",
                    reasoning_mode="coerce_to_content",
                    reasoning_counts_as_meaningful=True,
                )
            ]
        )

        policy = resolve_client_reasoning_policy(
            headers={},
            client_config=cfg,
            user_agent="TestClient/1.0",
        )
        assert policy.reasoning_mode == "coerce_to_content"
        assert policy.reasoning_counts_as_meaningful is True

    def test_request_reasoning_signal_implies_meaningful_when_no_header_or_ua(self) -> None:
        policy = resolve_client_reasoning_policy(
            headers={},
            client_config=ClientCompatibilityConfig(),
            user_agent=None,
            request_indicates_reasoning_output=True,
        )
        assert policy.reasoning_mode == "passthrough"
        assert policy.reasoning_counts_as_meaningful is True

    def test_header_still_wins_over_request_reasoning_signal(self) -> None:
        policy = resolve_client_reasoning_policy(
            headers={
                "x-llmproxy-reasoning-mode": "passthrough",
                "x-llmproxy-reasoning-meaningful": "false",
            },
            client_config=ClientCompatibilityConfig(),
            user_agent=None,
            request_indicates_reasoning_output=True,
        )
        assert policy.reasoning_counts_as_meaningful is False
