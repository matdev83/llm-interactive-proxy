import pytest

pytest.importorskip("respx")
import httpx
from respx import MockRouter
from starlette.testclient import TestClient

pytestmark = [pytest.mark.no_global_mock]


@pytest.fixture
async def app(monkeypatch):
    """Create a test app with ZAI backend configured using real backends."""
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

    # Create backend settings with zai configured
    zai_backend = BackendConfig(api_key="test-zai-key")
    backends = BackendSettings(zai_coding_plan=zai_backend)
    auth_config = AuthConfig(disable_auth=True)

    monkeypatch.setattr(
        "src.core.services.backend_factory.get_env_value_with_windows_persistent_fallback",
        lambda *args, **kwargs: (None, "missing"),
    )
    monkeypatch.setattr(
        "src.connectors.zai_coding_plan.get_env_value_with_windows_persistent_fallback",
        lambda *args, **kwargs: (None, "missing"),
    )

    config = AppConfig(backends=backends, auth=auth_config)

    # Use ApplicationTestBuilder with real backends
    builder = ApplicationTestBuilder()
    builder.add_stage(CoreServicesStage())
    builder.add_stage(InfrastructureStage())
    builder.add_stage(BackendStage())  # Use real backends
    builder.add_stage(CommandStage())
    builder.add_stage(ProcessorStage())
    builder.add_stage(ControllerStage())

    app = await builder.build(config)
    return app


@pytest.fixture
def client(app):
    """Create a test client and ensure proper cleanup."""
    with TestClient(app) as client:
        yield client


def test_zai_coding_plan_backend_integration(
    client: TestClient, respx_mock: MockRouter
):
    """Given a successful mock API response, the backend should process it correctly."""
    # Mock the health check call to the models endpoint
    respx_mock.get("https://api.z.ai/api/coding/paas/v4/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "glm-4.6",
                        "name": "glm-4.6",
                        "object": "model",
                        "created": 1,
                        "owned_by": "zai",
                    },
                    {
                        "id": "claude-sonnet-4-20250514",
                        "name": "claude-sonnet-4-20250514",
                        "object": "model",
                        "created": 2,
                        "owned_by": "zai",
                    },
                ]
            },
        )
    )

    # Mock the chat/completions endpoint
    respx_mock.post("https://api.z.ai/api/coding/paas/v4/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-123",
                "object": "chat.completion",
                "created": 1677652288,
                "model": "glm-4.6",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Hello from ZAI!",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 8,
                    "completion_tokens": 9,
                    "total_tokens": 17,
                },
            },
        )
    )

    # Make a request to the proxy
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "zai-coding-plan:glm-4.6",
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    # Assert the response is successful and contains the translated content
    if response.status_code != 200:
        import sys

        print(f"Response status: {response.status_code}", file=sys.stderr)
        print(f"Response body: {response.text}", file=sys.stderr)
        print(f"Response headers: {dict(response.headers)}", file=sys.stderr)
    assert (
        response.status_code == 200
    ), f"Expected 200, got {response.status_code}. Response: {response.text}"
    data = response.json()

    # The content should contain the actual message
    content = data["choices"][0]["message"]["content"]
    assert "Hello from ZAI!" in content
    # The model in the response may not have the backend prefix
    assert "glm-4.6" in data["model"]


def test_zai_coding_plan_streaming_glm51_reasoning_first_succeeds(
    client: TestClient, respx_mock: MockRouter
) -> None:
    """glm-5.1 reasoning-first SSE streams must survive the full proxy path."""

    respx_mock.get("https://api.z.ai/api/coding/paas/v4/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "glm-5.1",
                        "name": "glm-5.1",
                        "object": "model",
                        "created": 1,
                        "owned_by": "zai",
                    }
                ]
            },
        )
    )

    stream_body = (
        b'data: {"id":"chatcmpl-5-1","object":"chat.completion.chunk","created":1677652288,'
        b'"model":"glm-5.1","choices":[{"index":0,"delta":{"role":"assistant","reasoning_content":"Thinking","content":""},"finish_reason":null}]}'
        b"\n\n"
        b'data: {"id":"chatcmpl-5-1","object":"chat.completion.chunk","created":1677652288,'
        b'"model":"glm-5.1","choices":[{"index":0,"delta":{"content":"Hello from glm-5.1"},"finish_reason":"stop"}]}'
        b"\n\n"
        b"data: [DONE]\n\n"
    )
    respx_mock.post("https://api.z.ai/api/coding/paas/v4/chat/completions").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/event-stream;charset=UTF-8"},
            content=stream_body,
        )
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "zai-coding-plan:glm-5.1",
            "stream": True,
            "messages": [{"role": "user", "content": "Hello"}],
        },
    )

    assert response.status_code == 200, response.text
    assert "text/event-stream" in (response.headers.get("content-type") or "")
    assert "reasoning_content" in response.text
    assert "Hello from glm-5.1" in response.text
    assert "[DONE]" in response.text
