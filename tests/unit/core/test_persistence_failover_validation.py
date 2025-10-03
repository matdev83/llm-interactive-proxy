import sys
import types
import asyncio

from fastapi import FastAPI

# Provide lightweight stubs for optional dependencies used during module import.
if "json_repair" not in sys.modules:
    json_repair_module = types.ModuleType("json_repair")
    json_repair_module.repair_json = lambda value: value
    sys.modules["json_repair"] = json_repair_module

if "watchdog" not in sys.modules:
    watchdog_module = types.ModuleType("watchdog")
    sys.modules["watchdog"] = watchdog_module

    observers_module = types.ModuleType("watchdog.observers")
    events_module = types.ModuleType("watchdog.events")

    class _Observer:
        def schedule(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def start(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def stop(self):  # type: ignore[no-untyped-def]
            raise NotImplementedError

        def join(self, timeout=None):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    class _FileSystemEventHandler:
        def on_any_event(self, event):  # type: ignore[no-untyped-def]
            pass

    observers_module.Observer = _Observer  # type: ignore[attr-defined]
    events_module.FileSystemEventHandler = _FileSystemEventHandler  # type: ignore[attr-defined]

    sys.modules["watchdog.observers"] = observers_module
    sys.modules["watchdog.events"] = events_module


from src.core.persistence import ConfigManager


class _DummyAppState:
    """Minimal application state stub for failover validation tests."""

    def __init__(self, functional_backends: list[str]) -> None:
        self._functional_backends = functional_backends

    def get_functional_backends(self) -> list[str]:
        return self._functional_backends


class _DummyBackendService:
    async def validate_backend_and_model(
        self, backend: str, model: str
    ) -> tuple[bool, str | None]:
        return True, None


class _DummyServiceProvider:
    def get_required_service(self, _interface):
        return _DummyBackendService()


def test_failover_validation_during_running_event_loop() -> None:
    """Validate that failover entries remain intact when loop is running."""

    async def _run_validation() -> tuple[str | None, str | None]:
        config_manager = ConfigManager(
            FastAPI(),
            "dummy.json",
            service_provider=_DummyServiceProvider(),
            app_state=_DummyAppState(["backend"]),
        )

        return config_manager._parse_and_validate_failover_element(
            "backend:model", "route"
        )

    result, warning = asyncio.run(_run_validation())

    assert result == "backend:model"
    assert warning is None
