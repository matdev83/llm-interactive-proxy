from __future__ import annotations

import pytest
import src.core.app.controllers as controllers
from fastapi import FastAPI, HTTPException
from src.core.app.controllers import get_service_provider_dependency
from src.core.common.exceptions import ConfigurationError, ServiceResolutionError
from src.core.persistence import ConfigManager


@pytest.mark.parametrize(
    "strict_env, expect",
    [
        ("false", pytest.raises(HTTPException)),
        ("true", pytest.raises(ServiceResolutionError)),
    ],
)
@pytest.mark.asyncio
async def test_strict_controller_dependency_behavior(monkeypatch, strict_env, expect):
    monkeypatch.setenv("STRICT_CONTROLLER_ERRORS", strict_env)
    # Also override the imported module flag since it's read at import time
    monkeypatch.setattr(
        controllers,
        "_STRICT_CONTROLLER_ERRORS",
        strict_env.lower() in ("true", "1", "yes"),
        raising=False,
    )
    # Request is synthesized; app is not required here

    class DummyRequest:  # minimal shim to mimic Request.app.state
        class _App:
            class _State:
                pass

            state = _State()

        app = _App()

    request = DummyRequest()

    with expect:
        # When strict is false, function should raise HTTPException (handled by FastAPI in real app),
        # but here we simply call and expect no ServiceResolutionError.
        # When strict is true, it should raise ServiceResolutionError due to missing service_provider.
        await get_service_provider_dependency(request)  # type: ignore[arg-type]


def test_strict_persistence_save_errors(monkeypatch, tmp_path):
    # Force save to attempt writing into a directory path to trigger OSError
    monkeypatch.setenv("STRICT_PERSISTENCE_ERRORS", "true")
    app = FastAPI()
    # Create path to a directory, then pass that as file path to trigger write failure
    dir_path = tmp_path / "cfgdir"
    dir_path.mkdir()
    # Use the directory path as a file to cause OSError when opening for write
    mgr = ConfigManager(app, str(dir_path))
    with pytest.raises(ConfigurationError):
        mgr.save()
