"""HTTP-level E2E: proxy + Nvidia backend with mocked NVIDIA NIM upstream (Step-3.5-Flash)."""

from __future__ import annotations

import pytest

pytest.importorskip("respx")

import httpx
from respx import MockRouter
from starlette.testclient import TestClient

pytestmark = [pytest.mark.no_global_mock]

_NV_MODEL = "stepfun-ai/step-3.5-flash"
_BASE = "https://integrate.api.nvidia.com/v1"


def _models_payload() -> dict:
    return {
        "object": "list",
        "data": [
            {
                "id": _NV_MODEL,
                "object": "model",
                "created": 1,
                "owned_by": "nvidia",
            },
            {
                "id": "meta/llama3-8b-instruct",
                "object": "model",
                "created": 2,
                "owned_by": "meta",
            },
        ],
    }


def _chat_payload() -> dict:
    return {
        "id": "chatcmpl-nvidia-step",
        "object": "chat.completion",
        "created": 1700000000,
        "model": _NV_MODEL,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Step-3.5-Flash via Nvidia backend OK",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 8, "total_tokens": 13},
    }


@pytest.fixture
async def app(respx_mock: MockRouter):
    """Register upstream mocks before building the app so Nvidia init hits respx, not the wire."""
    respx_mock.get(f"{_BASE}/models").mock(
        return_value=httpx.Response(200, json=_models_payload())
    )
    respx_mock.post(f"{_BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json=_chat_payload())
    )

    from src.core.app.stages import (
        BackendStage,
        CommandStage,
        ControllerStage,
        CoreServicesStage,
        InfrastructureStage,
        ProcessorStage,
    )
    from src.core.app.test_builder import ApplicationTestBuilder
    from src.core.config.app_config import (
        AppConfig,
        AuthConfig,
        BackendConfig,
        BackendSettings,
    )

    backends = BackendSettings(
        nvidia=BackendConfig(api_key="integration-test-nvidia-key")
    )
    config = AppConfig(backends=backends, auth=AuthConfig(disable_auth=True))

    builder = ApplicationTestBuilder()
    builder.add_stage(CoreServicesStage())
    builder.add_stage(InfrastructureStage())
    builder.add_stage(BackendStage())
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    return await builder.build(config)


@pytest.fixture
def client(app):
    with TestClient(app) as tc:
        yield tc


def test_nvidia_list_models_and_demo_chat_through_proxy(client: TestClient) -> None:
    """Canonical GET /v1/models uses the capability index (may be empty); chat proves the Nvidia path."""
    listed = client.get("/v1/models")
    assert listed.status_code == 200, listed.text

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": f"nvidia:{_NV_MODEL}",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 32,
            "stream": False,
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    content = data["choices"][0]["message"]["content"]
    assert "Step-3.5-Flash via Nvidia backend OK" in content
