"""Integration tests for streaming error response formats."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from src.core.app.application_builder import ApplicationBuilder
from src.core.common.exceptions import AuthenticationError
from src.core.config.app_config import AppConfig
from src.core.config.models import (
    AuthConfig,
    BackendConfig,
    BackendSettings,
    LoggingConfig,
)


def test_streaming_request_returns_json_error_by_default() -> None:
    """When stream=True and backend errors, return JSON (not SSE) by default."""

    base_config = AppConfig.from_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        logging_cfg = LoggingConfig(cbor_capture_dir=str(Path(tmpdir)))
        backends_cfg = BackendSettings(
            default_backend="openai", openai=BackendConfig(api_key="test")
        )
        config = base_config.model_copy(
            update={
                "auth": AuthConfig(disable_auth=True),
                "logging": logging_cfg,
                "backends": backends_cfg,
            }
        )

        app = ApplicationBuilder().add_default_stages().build_compat(config)
        client = TestClient(app)
        try:
            with patch(
                "src.core.services.backend_service.BackendService.call_completion",
                side_effect=AuthenticationError("Invalid token"),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )

                assert resp.status_code == 401
                assert "application/json" in (resp.headers.get("content-type") or "")
                body = resp.json()
                # FastAPI wraps HTTPException detail under "detail".
                assert "detail" in body
        finally:
            client.close()


def test_streaming_request_can_opt_in_to_sse_error_format() -> None:
    """When stream=True, SSE error format can be requested explicitly."""

    base_config = AppConfig.from_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        logging_cfg = LoggingConfig(cbor_capture_dir=str(Path(tmpdir)))
        backends_cfg = BackendSettings(
            default_backend="openai", openai=BackendConfig(api_key="test")
        )
        config = base_config.model_copy(
            update={
                "auth": AuthConfig(disable_auth=True),
                "logging": logging_cfg,
                "backends": backends_cfg,
            }
        )

        app = ApplicationBuilder().add_default_stages().build_compat(config)
        client = TestClient(app)
        try:
            with patch(
                "src.core.services.backend_service.BackendService.call_completion",
                side_effect=AuthenticationError("Invalid token"),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    headers={"x-llmproxy-error-format": "sse"},
                    json={
                        "model": "gpt-4",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )

                assert resp.status_code == 401
                assert "text/event-stream" in (resp.headers.get("content-type") or "")
                assert "data:" in resp.text
        finally:
            client.close()
