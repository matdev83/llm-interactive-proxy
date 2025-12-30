import pytest

pytest.importorskip("respx")
import httpx
from respx import MockRouter
from starlette.testclient import TestClient

pytestmark = [pytest.mark.no_global_mock]


@pytest.fixture
async def app():
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
    zai_backend = BackendConfig(api_key=["test-zai-key"])
    backends = BackendSettings(zai_coding_plan=zai_backend)
    auth_config = AuthConfig(disable_auth=True)

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
    assert response.status_code == 200, f"Expected 200, got {response.status_code}. Response: {response.text}"
    data = response.json()

    # The content should contain the actual message
    content = data["choices"][0]["message"]["content"]
    assert "Hello from ZAI!" in content
    # The model in the response may not have the backend prefix
    assert "glm-4.6" in data["model"]
