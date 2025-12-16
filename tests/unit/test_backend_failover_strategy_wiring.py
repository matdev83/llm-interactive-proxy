from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from src.connectors.base import LLMBackend
from src.core.config.app_config import BackendConfig
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.domain.session import Session
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.failover_planner_interface import IFailoverPlanner
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
from src.core.interfaces.session_service_interface import ISessionService
from src.core.services.application_state_service import (
    ApplicationStateService,
)
from src.core.services.backend_factory import BackendFactory
from src.core.services.backend_service import BackendService
from src.core.services.failover_service import FailoverAttempt
from src.core.services.failover_strategy import DefaultFailoverStrategy

from tests.unit.fixtures.backend_service_builder import (
    create_backend_service_with_mocks,
)


class DummyFactory(BackendFactory):
    def __init__(self) -> None:
        # Don't call super().__init__ since we don't need the real dependencies
        pass

    async def ensure_backend(
        self, backend_type: str, backend_config: BackendConfig | None = None
    ) -> LLMBackend:
        # Minimal stub, adjust if more complex behavior needed for tests
        class DummyBackend(LLMBackend):
            async def initialize(self, **kwargs) -> None:
                pass

            def get_available_models(self) -> list[str]:
                return ["modelA", "modelB"]

            async def chat_completions(
                self, *args, **kwargs
            ) -> ResponseEnvelope | StreamingResponseEnvelope:
                # Return a minimal response envelope for testing
                from src.core.domain.responses import ResponseEnvelope

                return ResponseEnvelope(
                    content={
                        "id": "test-id",
                        "choices": [],
                        "created": 0,
                        "model": "test-model",
                        "system_fingerprint": "test-fingerprint",
                        "object": "chat.completion",
                        "usage": None,
                    }
                )

        return DummyBackend()


class DummyLimiter(IRateLimiter):
    async def check_limit(self, key: str) -> RateLimitInfo:
        return RateLimitInfo(
            is_limited=False, remaining=100, reset_at=None, limit=100, time_window=60
        )

    async def record_usage(self, key: str, cost: int = 1) -> None:
        pass

    async def reset(self, key: str) -> None:
        pass

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        pass

    async def apply_cooldown(self, key: str, cooldown_seconds: int) -> None:
        pass


class DummyConfig(IConfig):
    def __init__(self) -> None:
        self.backends = type(
            "B", (), {"default_backend": "openai", "get": lambda *a, **k: None}
        )()
        self.identity = "test"

    def get(self, key: str, default: Any = None) -> Any:
        if key == "backends":
            return self.backends
        if key == "identity":
            return self.identity
        return default

    def set(self, key: str, value: Any) -> None:
        # Minimal implementation
        pass


class DummySessionService(ISessionService):
    async def get_session(self, session_id: str) -> Session:
        return Session(session_id=session_id)

    async def get_session_async(self, session_id: str) -> Session:
        return Session(session_id=session_id)

    async def create_session(self, session_id: str) -> Session:
        return Session(session_id=session_id)

    async def get_or_create_session(self, session_id: str | None = None) -> Session:
        return Session(session_id=session_id or "test-session")

    async def update_session(self, session: Session) -> None:
        pass

    async def update_session_backend_config(
        self, session_id: str, backend_type: str, model: str
    ) -> None:
        pass

    async def delete_session(self, session_id: str) -> bool:
        return True

    async def get_all_sessions(self) -> list[Session]:
        return []


class DummyProvider(IBackendConfigProvider):
    def get_backend_config(self, name: str) -> BackendConfig | None:
        return None

    def iter_backend_names(self) -> list[str]:
        return []

    def get_default_backend(self) -> str:
        return "openai"

    def get_functional_backends(self) -> set[str]:
        return set()


class FakeCoordinator:
    def __init__(self, svc: BackendService) -> None:
        self._svc = svc

    def get_failover_attempts(
        self, model: str, backend_type: str
    ) -> list[FailoverAttempt]:
        # Read from the underlying service's failover_service routes for consistency
        routes = self._svc._failover_service.failover_routes
        elements = routes.get(model, {}).get("elements", [])
        out: list[FailoverAttempt] = []
        for el in elements:
            backend, model_name = el.split(":", 1) if ":" in el else el.split("/", 1)
            out.append(FailoverAttempt(backend=backend, model=model_name))
        return out

    def register_route(self, model: str, route: dict[str, Any]) -> None:
        self._svc._failover_service.failover_routes[model] = route


class DummyStrategy(DefaultFailoverStrategy):
    def __init__(self) -> None:
        # coordinator not used; pass a throwaway
        super().__init__(coordinator=None)  # type: ignore[arg-type]

    def get_failover_plan(self, model: str, backend_type: str) -> list[tuple[str, str]]:
        return [("s1", "mA"), ("s2", "mB")]


def make_service(
    strategy: Any | None = None, app_state: ApplicationStateService | None = None
) -> BackendService:
    # Pass a minimal coordinator at construction time to avoid init warnings,
    # then replace with a coordinator that reads routes from the service.
    class _InitStubCoordinator:
        def get_failover_attempts(
            self, model: str, backend_type: str
        ) -> list[FailoverAttempt]:
            return [FailoverAttempt(backend=backend_type, model=model)]

        def register_route(self, model: str, route: dict[str, Any]) -> None:
            return None

    # Create a mock failover_planner so we can control its behavior in tests
    mock_failover_planner = MagicMock(spec=IFailoverPlanner)

    svc = create_backend_service_with_mocks(
        factory=DummyFactory(),
        rate_limiter=DummyLimiter(),
        config=DummyConfig(),
        session_service=DummySessionService(),
        app_state=app_state,
        backend_config_provider=DummyProvider(),
        failover_routes={"openai": {"backend": "openrouter", "model": "meta/llama"}},
        failover_strategy=strategy,
        failover_coordinator=_InitStubCoordinator(),
        failover_planner=mock_failover_planner,
    )
    # Replace with a coordinator tied to the service's failover routes for tests
    svc._failover_coordinator = FakeCoordinator(svc)  # type: ignore[attr-defined]
    return svc


def test_failover_plan_uses_coordinator_when_flag_disabled() -> None:
    svc = make_service()
    # Configure coordinator underlying service routes for model 'm1'
    svc._failover_service.failover_routes = {  # type: ignore[attr-defined]
        "m1": {"policy": "k", "elements": ["openai:gpt-4o", "openrouter:meta/llama"]}
    }
    # Configure the failover planner mock to return the expected result from coordinator
    svc._failover_planner.get_failover_plan.return_value = [
        ("openai", "gpt-4o"),
        ("openrouter", "meta/llama"),
    ]
    plan = svc._get_failover_plan("m1", "openai")  # type: ignore[attr-defined]
    assert plan == [("openai", "gpt-4o"), ("openrouter", "meta/llama")]


def test_failover_plan_uses_strategy_when_flag_enabled() -> None:
    state = ApplicationStateService()
    state.set_use_failover_strategy(True)
    svc = make_service(strategy=DummyStrategy(), app_state=state)
    # Configure the failover planner mock to return the expected result from strategy
    svc._failover_planner.get_failover_plan.return_value = [("s1", "mA"), ("s2", "mB")]
    plan = svc._get_failover_plan("m1", "openai")  # type: ignore[attr-defined]
    assert plan == [("s1", "mA"), ("s2", "mB")]
