"""Debug script to understand the mock backend patching issue."""

import asyncio
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from src.core.app.test_builder import build_test_app
from src.core.config.app_config import AppConfig, AuthConfig, BackendSettings, BackendConfig
from src.core.interfaces.backend_service_interface import IBackendService
from src.core.domain.responses import ResponseEnvelope

# Create test app with proper configuration
config = AppConfig(
    auth=AuthConfig(disable_auth=True),
    backends=BackendSettings(
        default_backend="openai",
        openai=BackendConfig(api_key=["test-openai-key"]),
    ),
)
app = build_test_app(config)

# Check what backend service we get
backend_service = app.state.service_provider.get_required_service(IBackendService)
print(f"Backend service type: {type(backend_service)}")
print(f"Backend service class: {backend_service.__class__}")

# Try monkeypatch instead
async def fake_call_completion(request, stream=False, allow_failover=True, context=None):
    mock_response = {
        "id": "mock-real-response",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "This is a real response",
                },
                "finish_reason": "stop",
                "index": 0,
            }
        ],
        "model": "gpt-3.5-turbo",
        "created": 1619432555,
        "object": "chat.completion",
        "usage": {"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19},
    }
    return ResponseEnvelope(content=mock_response, headers={})

import types
backend_service.call_completion = types.MethodType(fake_call_completion, backend_service)

with TestClient(app) as client:
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": "Say 'This is a real response'"}
            ],
        },
    )
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")
