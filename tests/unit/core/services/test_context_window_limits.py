# isort: skip_file
from collections import deque
from typing import Any

from fastapi.testclient import TestClient
import pytest
from src.core.app.test_builder import build_test_app
from src.core.domain.model_capabilities import ModelLimits
from src.core.domain.model_utils import ModelDefaults
from src.core.domain.responses import ResponseEnvelope
from src.core.interfaces.application_state_interface import IApplicationState


class TestContextWindowLimits:
    def _setup_app_with_defaults(
        self, model_key: str, limits: ModelLimits
    ) -> TestClient:
        app = build_test_app()
        sp = app.state.service_provider
        app_state = sp.get_required_service(IApplicationState)  # type: ignore[attr-defined]
        # Set model defaults
        md = ModelDefaults(limits=limits)
        app_state.set_model_defaults({model_key: md, model_key.split(":", 1)[-1]: md})
        app_state.set_backend_type("openai")
        # Disable auth for tests (both DI and app.state fallbacks)
        app_state.set_setting("disable_auth", True)
        app.state.disable_auth = True
        return TestClient(app)

    def test_output_limit_caps_max_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._setup_app_with_defaults(
            "openai:gpt-4", ModelLimits(max_output_tokens=50)
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
        assert getattr(called_req, "max_tokens", None) == 50

    def test_input_limit_hard_error(self) -> None:
        client = self._setup_app_with_defaults(
            "openai:gpt-4", ModelLimits(max_input_tokens=1)
        )

        payload = {
            "model": "openai:gpt-4",
            "messages": [{"role": "user", "content": "This should exceed one token."}],
        }
        resp = client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        body = resp.json()
        detail = body.get("detail", {})
        err = detail.get("error", {}) if isinstance(detail, dict) else {}
        assert err.get("code") == "input_limit_exceeded"
        details = err.get("details", {})
        assert isinstance(details.get("measured"), int)
        assert isinstance(details.get("limit"), int) and details["limit"] == 1

    def test_context_window_aliases_to_input_limit_hard_error(self) -> None:
        """Ensure context_window acts as an input limit without duplicating logic."""
        client = self._setup_app_with_defaults(
            "openai:gpt-4", ModelLimits(context_window=1)
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
        err = detail.get("error", {}) if isinstance(detail, dict) else {}
        assert err.get("code") == "input_limit_exceeded"
        details = err.get("details", {})
        assert isinstance(details.get("measured"), int)
        assert isinstance(details.get("limit"), int) and details["limit"] == 1
