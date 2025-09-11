"""
Simplified integration tests for Cline tool call implementation.
"""

import json
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.stages.test_stages import CustomTestStage
from src.core.app.test_builder import ApplicationTestBuilder
from src.core.interfaces.backend_service_interface import IBackendService


@pytest.fixture
async def mock_backend_service() -> MagicMock:
    """Create a mock backend service."""
    mock_backend = MagicMock(spec=IBackendService)
    mock_backend.get_available_models = MagicMock(return_value=["gpt-4"])
    mock_backend.validate_backend = AsyncMock(return_value=(True, None))
    mock_backend.validate_backend_and_model = AsyncMock(return_value=(True, None))
    mock_backend.get_backend_status = AsyncMock(return_value={"status": "healthy"})
    return mock_backend


@pytest.fixture
async def app(mock_backend_service: MagicMock) -> AsyncGenerator[FastAPI, None]:
    """Create the application for testing."""
    from src.core.config.app_config import AppConfig

    config = AppConfig()
    config.backends.openai.api_key = ["test-api-key"]

    builder = (
        ApplicationTestBuilder()
        .add_test_stages()
        .replace_stage(
            "backends",
            CustomTestStage("backends", {IBackendService: mock_backend_service}),
        )
    )
    test_app = await builder.build(config)
    test_app.state.client_api_key = "test-proxy-key"

    yield test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


def create_tool_call_response(
    tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Helper function to create a tool call response."""
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1677858242,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_mock_id",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": json.dumps(arguments),
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 10,
            "total_tokens": 20,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command, expected_tool_name",
    [
        ("!/hello", "hello"),
        ("!/set(project=test-project)", "set"),
    ],
)
async def test_cline_commands_return_tool_calls(
    client: TestClient,
    mock_backend_service: MagicMock,
    command: str,
    expected_tool_name: str,
) -> None:
    """Test that Cline commands return tool calls."""
    mock_backend_service.call_completion = AsyncMock(
        return_value=create_tool_call_response(expected_tool_name, {"text": command})
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": command}],
            "agent": "cline",
        },
        headers={"Authorization": "Bearer test-proxy-key"},
    )

    assert response.status_code == 200
    data = response.json()

    choice = data["choices"][0]
    message = choice["message"]

    assert message.get("tool_calls") is not None
    assert len(message["tool_calls"]) == 1
    assert choice.get("finish_reason") == "tool_calls"

    tool_call = message["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == expected_tool_name


@pytest.mark.asyncio
async def test_xml_from_backend_is_converted_to_tool_calls_for_cline(
    client: TestClient, mock_backend_service: MagicMock
) -> None:
    """Test that a backend response containing <attempt_completion> XML is converted to a tool call for Cline agents."""
    mock_backend_service.call_completion = AsyncMock(
        return_value=create_tool_call_response(
            "attempt_completion", {"result": "some content"}
        )
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "This message triggers the mock to return XML. <attempt_completion><r>some content</r></attempt_completion>",
                }
            ],
            "agent": "cline",
        },
        headers={"Authorization": "Bearer test-proxy-key"},
    )

    assert response.status_code == 200
    data = response.json()

    choice = data["choices"][0]
    message = choice["message"]

    assert message.get("tool_calls") is not None
    assert choice.get("finish_reason") == "tool_calls"

    tool_call = message["tool_calls"][0]
    assert tool_call["type"] == "function"
    assert tool_call["function"]["name"] == "attempt_completion"
    args = json.loads(tool_call["function"]["arguments"])
    assert args["result"] == "some content"


def create_regular_response() -> dict[str, Any]:
    """Helper function to create a regular response."""
    return {
        "id": "chatcmpl-regular",
        "object": "chat.completion",
        "created": 1677858242,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Regular content from test backend.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


@pytest.mark.asyncio
async def test_non_cline_agents_receive_regular_content(
    client: TestClient, mock_backend_service: MagicMock
) -> None:
    """Test that non-Cline agents get regular content."""
    mock_backend_service.call_completion = AsyncMock(
        return_value=create_regular_response()
    )

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-4",
            "messages": [{"role": "user", "content": "A regular message"}],
        },
        headers={"Authorization": "Bearer test-proxy-key"},
    )

    assert response.status_code == 200
    data = response.json()

    choice = data["choices"][0]
    message = choice["message"]
    assert message.get("tool_calls") is None
    assert message.get("content") is not None
    assert choice.get("finish_reason") == "stop"
