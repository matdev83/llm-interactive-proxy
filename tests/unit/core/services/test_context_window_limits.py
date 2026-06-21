# isort: skip_file
from collections import deque
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from src.core.app.test_builder import build_test_app
from src.core.domain.model_capabilities import ModelLimits
from src.core.domain.model_utils import ModelDefaults
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState


class TestContextWindowLimits:
    @pytest.fixture(scope="class")
    def app(self) -> FastAPI:
        app = build_test_app()
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]
        app.state.original_app_config = app_state.get_setting("app_config")
        return app

    @pytest.fixture(autouse=True)
    def reset_app_state(self, app: FastAPI) -> None:
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]
        app_state.set_model_defaults({})
        app_state.set_setting(
            "app_config", getattr(app.state, "original_app_config", None)
        )
        app_state.set_setting("disable_auth", True)
        app.state.disable_auth = True

    def _configure_app_with_defaults(
        self, app: FastAPI, model_key: str, limits: ModelLimits
    ) -> TestClient:
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]
        # Set model defaults
        # Use model_validate to avoid static typing issues around BaseModel __init__.
        md = ModelDefaults.model_validate({"limits": limits})
        app_state.set_model_defaults({model_key: md, model_key.split(":", 1)[-1]: md})
        app_state.set_backend_type("openai")
        return TestClient(app)

    def test_output_limit_no_longer_enforced(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that max_output_tokens is no longer enforced (removed as redundant)."""
        client = self._configure_app_with_defaults(
            app, "openai:gpt-4", ModelLimits(max_output_tokens=50)
        )

        captured: deque[dict[str, Any]] = deque(maxlen=1)

        # Monkeypatch BackendRequestManager.process_backend_request to capture request
        import src.core.services.backend_request_manager_service as brm

        async def fake_process_backend_request(self, request, session_id, context=None):
            captured.append({"request": request, "session_id": session_id})
            return ResponseEnvelope(content={"ok": True})

        monkeypatch.setattr(
            brm.BackendRequestManager,
            "process_backend_request",
            fake_process_backend_request,
            raising=True,
        )

        payload = {
            "model": "openai:gpt-4",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 100,
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 200

        assert captured, "Expected backend request to be captured"
        called_req = captured[0]["request"]
        # max_tokens should no longer be capped since max_output_tokens enforcement was removed
        assert getattr(called_req, "max_tokens", None) == 100

    def test_input_limit_hard_error(self, app: FastAPI) -> None:
        client = self._configure_app_with_defaults(
            app, "openai:gpt-4", ModelLimits(max_input_tokens=1)
        )

        payload = {
            "model": "openai:gpt-4",
            "messages": [{"role": "user", "content": "This should exceed one token."}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("type") == "invalid_request_error"
        assert detail.get("code") == "context_length_exceeded"
        assert detail.get("param") == "input"
        details = detail.get("details", {})
        assert isinstance(details.get("measured"), int)
        assert isinstance(details.get("limit"), int) and details["limit"] == 1

    def test_context_window_aliases_to_input_limit_hard_error(
        self, app: FastAPI
    ) -> None:
        """Ensure context_window acts as an input limit without duplicating logic."""
        client = self._configure_app_with_defaults(
            app, "openai:gpt-4", ModelLimits(context_window=1)
        )

        payload = {
            "model": "openai:gpt-4",
            "messages": [
                {"role": "user", "content": "This should exceed one token as well."}
            ],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("type") == "invalid_request_error"
        assert detail.get("code") == "context_length_exceeded"
        assert detail.get("param") == "input"
        details = detail.get("details", {})
        assert isinstance(details.get("measured"), int)
        assert isinstance(details.get("limit"), int) and details["limit"] == 1

    def test_cli_context_window_override(self, app: FastAPI) -> None:
        """Test that CLI context window override takes precedence over config file settings."""
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]

        # Set model defaults with large context window
        large_limits = ModelLimits(context_window=100000, max_input_tokens=80000)
        md = ModelDefaults.model_validate({"limits": large_limits})
        app_state.set_model_defaults({"gpt-4": md})
        app_state.set_backend_type("openai")

        # Set CLI context window override to smaller value
        app_state.set_setting(
            "app_config", type("MockConfig", (), {"context_window_override": 5000})()
        )

        client = TestClient(app)

        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "This is a short message."}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        # Should succeed since the message is under the CLI override limit
        assert resp.status_code == 200

    def test_cli_context_window_override_enforced(self, app: FastAPI) -> None:
        """Test that CLI context window override is actually enforced when exceeded."""
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]

        # Set model defaults with very large context window
        large_limits = ModelLimits(context_window=100000, max_input_tokens=80000)
        md = ModelDefaults.model_validate({"limits": large_limits})
        app_state.set_model_defaults({"gpt-4": md})
        app_state.set_backend_type("openai")

        # Set CLI context window override to very small value
        app_state.set_setting(
            "app_config", type("MockConfig", (), {"context_window_override": 1})()
        )

        client = TestClient(app)

        # Create a message that will exceed the tiny CLI override limit
        long_content = "This is a very long message that should definitely exceed one token and trigger the CLI context window override enforcement."
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": long_content}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("type") == "invalid_request_error"
        assert detail.get("code") == "context_length_exceeded"
        assert detail.get("param") == "input"
        details = detail.get("details", {})
        assert isinstance(details.get("measured"), int)
        # The limit should be the CLI override value (1), not the config file value (100000)
        assert isinstance(details.get("limit"), int) and details["limit"] == 1

    def test_cli_context_window_override_with_no_existing_limits(
        self, app: FastAPI
    ) -> None:
        """Test CLI context window override when model has no existing limits configured."""
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]

        # Don't set any model defaults (no existing limits)
        app_state.set_model_defaults({})
        app_state.set_backend_type("openai")

        # Set CLI context window override to very small value
        app_state.set_setting(
            "app_config", type("MockConfig", (), {"context_window_override": 10})()
        )

        client = TestClient(app)

        # Create a message that will exceed the tiny CLI override limit
        # This message is definitely more than 10 tokens
        long_content = "This is a much longer message that should definitely exceed the very small CLI context window override limit of ten tokens and trigger enforcement since it contains many more words than would fit in such a tiny limit."
        payload = {
            "model": "gpt-4",
            "messages": [{"role": "user", "content": long_content}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("type") == "invalid_request_error"
        assert detail.get("code") == "context_length_exceeded"
        assert detail.get("param") == "input"
        details = detail.get("details", {})
        assert isinstance(details.get("measured"), int)
        # The limit should be the CLI override value (10)
        assert isinstance(details.get("limit"), int) and details["limit"] == 10

    def test_openai_codex_configured_limit_blocks_before_backend_dispatch(
        self, app: FastAPI, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]
        md = ModelDefaults.model_validate(
            {"limits": ModelLimits(context_window=260000, max_input_tokens=260000)}
        )
        app_state.set_model_defaults(
            {
                "openai-codex:gpt-5.5": md,
                "gpt-5.5": md,
            }
        )
        app_state.set_backend_type("openai-codex")

        import src.core.services.backend_preparer as backend_preparer
        import src.core.services.backend_request_manager_service as brm

        monkeypatch.setattr(
            backend_preparer,
            "count_tokens",
            lambda *_args, **_kwargs: 260001,
        )
        process_backend_request = AsyncMock()
        monkeypatch.setattr(
            brm.BackendRequestManager,
            "process_backend_request",
            process_backend_request,
            raising=True,
        )

        client = TestClient(app)
        payload = {
            "model": "openai-codex:gpt-5.5",
            "messages": [{"role": "user", "content": "large request"}],
        }

        resp = client.post("/v1/chat/completions", json=payload)

        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        assert detail.get("type") == "invalid_request_error"
        assert detail.get("code") == "context_length_exceeded"
        assert detail.get("param") == "input"
        assert detail.get("details", {}).get("limit") == 260000
        process_backend_request.assert_not_called()


pytestmark = pytest.mark.filterwarnings(
    "ignore:unclosed event loop <ProactorEventLoop.*:ResourceWarning"
)
