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
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.response_processor_interface import ProcessedResponse


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


def test_zai_streaming_sse_error_keeps_429_status() -> None:
    """Transport layer must preserve 429 SSE errors for zai-coding-plan streams."""

    base_config = AppConfig.from_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        logging_cfg = LoggingConfig(cbor_capture_dir=str(Path(tmpdir)))
        backends_cfg = BackendSettings(
            default_backend="zai-coding-plan",
            zai_coding_plan=BackendConfig(api_key="test-zai-key"),
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

            async def error_stream():
                yield ProcessedResponse(
                    content=(
                        'data: {"error": {"message": "Insufficient balance", '
                        '"type": "RateLimitExceededError", "status_code": 429}}\n\n'
                    )
                )
                yield ProcessedResponse(content="data: [DONE]\n\n")

            with patch(
                "src.core.services.backend_service.BackendService.call_completion",
                return_value=StreamingResponseEnvelope(
                    content=error_stream(),
                    media_type="text/event-stream",
                    status_code=429,
                ),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    headers={"x-llmproxy-error-format": "sse"},
                    json={
                        "model": "zai-coding-plan:glm-5.1",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )

                assert resp.status_code == 429
                assert "text/event-stream" in (resp.headers.get("content-type") or "")
                assert "429" in resp.text
                assert "502" not in resp.text
        finally:
            client.close()


def test_openai_streaming_sse_error_keeps_429_status() -> None:
    """Transport layer must preserve 429 SSE errors for OpenAI streams."""

    base_config = AppConfig.from_env()

    with tempfile.TemporaryDirectory() as tmpdir:
        logging_cfg = LoggingConfig(cbor_capture_dir=str(Path(tmpdir)))
        backends_cfg = BackendSettings(
            default_backend="openai",
            openai=BackendConfig(api_key="test-openai-key"),
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

            async def error_stream():
                yield ProcessedResponse(
                    content=(
                        'data: {"id":"chatcmpl-err","object":"chat.completion.chunk",'
                        '"choices":[{"index":0,"delta":{},"finish_reason":"error"}],'
                        '"error":{"message":"Rate limit exceeded","type":"RateLimitExceededError","status_code":429}}\n\n'
                    )
                )
                yield ProcessedResponse(content="data: [DONE]\n\n")

            with patch(
                "src.core.services.backend_service.BackendService.call_completion",
                return_value=StreamingResponseEnvelope(
                    content=error_stream(),
                    media_type="text/event-stream",
                    status_code=429,
                ),
            ):
                resp = client.post(
                    "/v1/chat/completions",
                    headers={"x-llmproxy-error-format": "sse"},
                    json={
                        "model": "openai:gpt-4o-mini",
                        "messages": [{"role": "user", "content": "hi"}],
                        "stream": True,
                    },
                )

                assert resp.status_code == 429
                assert "text/event-stream" in (resp.headers.get("content-type") or "")
                assert "Backend returned 429 error" in resp.text
                assert "429" in resp.text
                assert "502" not in resp.text
        finally:
            client.close()
