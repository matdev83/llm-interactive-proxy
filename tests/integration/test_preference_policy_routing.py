from __future__ import annotations

from src.core.config.app_config import BackendConfig, RoutingConfig
from src.core.services.backend_routing_service import BackendRoutingService


class _PreferenceProvider:
    def __init__(self) -> None:
        self._configs = {
            "openai.1": BackendConfig(
                api_key="k1",
                models=["gpt-4o"],
                extra={"routing_cost": 1, "routing_priority": 10},
            ),
            "openai.2": BackendConfig(
                api_key="k2",
                models=["gpt-4o"],
                extra={"routing_cost": 1, "routing_priority": 10},
            ),
            "openai.3": BackendConfig(
                api_key="k3",
                models=["gpt-4o"],
                extra={"routing_cost": 5, "routing_priority": 1},
            ),
        }

    def iter_backend_names(self):
        return self._configs.keys()

    def get_backend_config(self, name: str):
        return self._configs.get(name)


def test_cost_policy_uses_round_robin_inside_top_equivalent_set() -> None:
    provider = _PreferenceProvider()
    service = BackendRoutingService(
        provider,
        RoutingConfig(model_only_preference_policy="cost"),
    )

    picks = [service.resolve_model_only_backend("gpt-4o") for _ in range(8)]
    assert set(picks).issuperset({"openai.1", "openai.2"})
    assert "openai.3" not in picks


def test_failover_exhausts_top_tie_set_before_lower_preference_bucket() -> None:
    provider = _PreferenceProvider()
    service = BackendRoutingService(
        provider,
        RoutingConfig(model_only_preference_policy="cost"),
    )

    first = service.resolve_model_only_backend("gpt-4o", excluded_backends=set())
    second = service.resolve_model_only_backend("gpt-4o", excluded_backends={first})
    third = service.resolve_model_only_backend(
        "gpt-4o", excluded_backends={first, second}
    )

    assert {first, second} == {"openai.1", "openai.2"}
    assert third == "openai.3"
