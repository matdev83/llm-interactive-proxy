from __future__ import annotations

from typing import Any

from src.core.config.app_config import BackendConfig
from src.connectors.base import LLMBackend
from src.core.domain.session import Session
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.rate_limiter_interface import IRateLimiter, RateLimitInfo
from src.core.interfaces.configuration_interface import IConfig
from src.core.interfaces.session_service_interface import ISessionService
from src.core.interfaces.backend_config_provider_interface import IBackendConfigProvider
from src.core.services.backend_factory import BackendFactory
from src.core.services.application_state_service import (
    ApplicationStateService,
)
from src.core.services.backend_service import BackendService
from src.core.services.failover_service import FailoverAttempt
from src.core.services.failover_strategy import DefaultFailoverStrategy




class DummyFactory(BackendFactory):
    def __init__(self) -> None:
        # Don't call super().__init__ since we don't need the real dependencies
        pass

    async def ensure_backend(self, backend_type: str, backend_config: BackendConfig | None = None) -> LLMBackend:
        # Minimal stub, adjust if more complex behavior needed for tests
        class DummyBackend(LLMBackend):
            async def initialize(self, **kwargs) -> None:
                pass
                
            def get_available_models(self) -> list[str]:
                return ["modelA", "modelB"]
                
            async def chat_completions(self, *args, **kwargs) -> ResponseEnvelope | StreamingResponseEnvelope:
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
                        "usage": None
                    }
                )
                
        return DummyBackend()
class DummyLimiter(IRateLimiter):
    async def check_limit(self, key: str) -> RateLimitInfo:
        return RateLimitInfo(
            is_limited=False,
            remaining=100,
            reset_at=None,
            limit=100,
            time_window=60
        )

    async def record_usage(self, key: str, cost: int = 1) -> None:
        pass

    async def reset(self, key: str) -> None:
        pass

    async def set_limit(self, key: str, limit: int, time_window: int) -> None:
        pass


class DummyConfig(IConfig):
    def __init__(self) -> None:
        self.backends = type("B", (), {"default_backend": "openai", "get": lambda *a, **k: None})()
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

    async def update_session_backend_config(self, session_id: str, backend_type: str, model: str) -> None:
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
    svc = BackendService(
        factory=DummyFactory(),
        rate_limiter=DummyLimiter(),
        config=DummyConfig(),
        session_service=DummySessionService(),
        backend_config_provider=DummyProvider(),
        failover_routes={"openai": {"backend": "openrouter", "model": "meta/llama"}},
        failover_strategy=strategy,
        app_state=app_state,
    )
    return svc


def test_failover_plan_uses_coordinator_when_flag_disabled() -> None:
    svc = make_service()
    # Configure coordinator underlying service routes for model 'm1'
    svc._failover_service.failover_routes = {  # type: ignore[attr-defined]
        "m1": {"policy": "k", "elements": ["openai:gpt-4o", "openrouter:meta/llama"]}
    }
    plan = svc._get_failover_plan("m1", "openai")  # type: ignore[attr-defined]
    assert plan == [("openai", "gpt-4o"), ("openrouter", "meta/llama")]


def test_failover_plan_uses_strategy_when_flag_enabled() -> None:
    state = ApplicationStateService()
    state.set_use_failover_strategy(True)
    svc = make_service(strategy=DummyStrategy(), app_state=state)
    # Debug prints
    print(f"use_failover_strategy setting: {state.get_setting('use_failover_strategy', False)}")
    print(f"failover_strategy is not None: {svc._failover_strategy is not None}")
    if svc._failover_strategy is not None:
        print(f"failover_strategy.get_failover_plan result: {svc._failover_strategy.get_failover_plan('m1', 'openai')}")
    plan = svc._get_failover_plan("m1", "openai")  # type: ignore[attr-defined]
    print(f"plan result: {plan}")
    assert plan == [("s1", "mA"), ("s2", "mB")]
