"""Integration tests for tool call loop detection."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src.main import build_app
from src.tool_call_loop.config import ToolCallLoopConfig, ToolLoopMode


@pytest.fixture
def test_client():
    """Create a test client with tool call loop detection enabled."""
    test_config = {
        "command_prefix": "!/",
        "openai_api_keys": {"test": "test-key"},
        "tool_loop_detection_enabled": True,
        "tool_loop_max_repeats": 3,
        "tool_loop_ttl_seconds": 60,
        "tool_loop_mode": "break",
        "disable_auth": True,
    }

    test_app = build_app(test_config)
    return TestClient(test_app)


def create_chat_completion_request(tool_calls=None, stream=False):
    """Create a chat completion request with optional tool calls."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Please help me with a task."},
    ]

    request_data = {
        "model": "gpt-4",
        "messages": messages,
        "stream": stream,
    }

    if tool_calls is not None:
        request_data["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "Get the weather for a location",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "location": {
                                "type": "string",
                                "description": "The location to get weather for",
                            }
                        },
                        "required": ["location"],
                    },
                },
            }
        ]

    return request_data


def create_mock_response(tool_calls=None):
    """Create a mock response with optional tool calls."""
    response = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1677858242,
        "model": "gpt-4",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "I'll help you with that task.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }

    if tool_calls:
        response["choices"][0]["message"]["tool_calls"] = tool_calls
        response["choices"][0]["message"]["content"] = None
        response["choices"][0]["finish_reason"] = "tool_calls"

    return response


@pytest.fixture
def mock_openai_backend():
    """Mock the OpenAI backend to return a response with tool calls."""
    with patch("src.connectors.openai.OpenAIConnector.chat_completions") as mock:
        yield mock


class TestToolCallLoopDetection:
    """Integration tests for tool call loop detection."""

    def test_break_mode_blocks_repeated_tool_calls(
        self, test_client, mock_openai_backend
    ):
        """Test that break mode blocks repeated tool calls."""
        # Configure the mock to return a response with tool calls
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "New York"}',
                },
            }
        ]
        mock_response = create_mock_response(tool_calls)
        mock_openai_backend.return_value = mock_response

        # Make multiple requests with the same tool call
        for _ in range(2):  # Below threshold
            response = test_client.post(
                "/v1/chat/completions",
                json=create_chat_completion_request(tool_calls=True),
            )
            assert response.status_code == 200
            data = response.json()
            assert "tool_calls" in data["choices"][0]["message"]
            assert (
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "get_weather"
            )

        # The next request should be blocked
        response = test_client.post(
            "/v1/chat/completions",
            json=create_chat_completion_request(tool_calls=True),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have an error message instead of tool calls
        assert "tool_calls" not in data["choices"][0]["message"]
        assert "content" in data["choices"][0]["message"]
        assert "Tool call loop detected" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "error"

    def test_chance_then_break_mode_gives_warning_then_blocks(
        self, test_client, mock_openai_backend
    ):
        """Test that chance_then_break mode gives a warning and then blocks."""
        # Update the app config to use chance_then_break mode
        test_client.app.state.tool_loop_config = ToolCallLoopConfig(
            enabled=True,
            max_repeats=3,
            ttl_seconds=60,
            mode=ToolLoopMode.CHANCE_THEN_BREAK,
        )

        # Configure the mock to return a response with tool calls
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "New York"}',
                },
            }
        ]
        mock_response = create_mock_response(tool_calls)
        mock_openai_backend.return_value = mock_response

        # Make multiple requests with the same tool call
        for _ in range(2):  # Below threshold
            response = test_client.post(
                "/v1/chat/completions",
                json=create_chat_completion_request(tool_calls=True),
            )
            assert response.status_code == 200
            data = response.json()
            assert "tool_calls" in data["choices"][0]["message"]
            assert (
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "get_weather"
            )

        # The next request should trigger a warning
        response = test_client.post(
            "/v1/chat/completions",
            json=create_chat_completion_request(tool_calls=True),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have a warning message instead of tool calls
        assert "tool_calls" not in data["choices"][0]["message"]
        assert "content" in data["choices"][0]["message"]
        assert "Tool call loop warning" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "error"

        # One more request with the same tool call should be blocked
        response = test_client.post(
            "/v1/chat/completions",
            json=create_chat_completion_request(tool_calls=True),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have an error message instead of tool calls
        assert "tool_calls" not in data["choices"][0]["message"]
        assert "content" in data["choices"][0]["message"]
        assert "After guidance" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "error"

    def test_different_tool_calls_not_blocked(self, test_client, mock_openai_backend):
        """Test that different tool calls are not blocked."""
        # Configure the mock to return responses with different tool calls
        tool_calls1 = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "New York"}',
                },
            }
        ]
        mock_response1 = create_mock_response(tool_calls1)

        tool_calls2 = [
            {
                "id": "call_def456",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "London"}',
                },
            }
        ]
        mock_response2 = create_mock_response(tool_calls2)

        # Alternate between different tool calls
        mock_openai_backend.side_effect = [mock_response1, mock_response2] * 3

        # Make multiple requests with alternating tool calls
        for _ in range(6):  # Well above threshold, but alternating
            response = test_client.post(
                "/v1/chat/completions",
                json=create_chat_completion_request(tool_calls=True),
            )
            assert response.status_code == 200
            data = response.json()

            # Should not be blocked
            assert "tool_calls" in data["choices"][0]["message"]
            assert (
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "get_weather"
            )

    def test_disabled_tool_call_loop_detection(self, test_client, mock_openai_backend):
        """Test that disabled tool call loop detection doesn't block repeated tool calls."""
        # Update the app config to disable tool call loop detection
        test_client.app.state.tool_loop_config = ToolCallLoopConfig(
            enabled=False,
            max_repeats=3,
            ttl_seconds=60,
            mode=ToolLoopMode.BREAK,
        )

        # Configure the mock to return a response with tool calls
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "New York"}',
                },
            }
        ]
        mock_response = create_mock_response(tool_calls)
        mock_openai_backend.return_value = mock_response

        # Make multiple requests with the same tool call (well above threshold)
        for _ in range(6):
            response = test_client.post(
                "/v1/chat/completions",
                json=create_chat_completion_request(tool_calls=True),
            )
            assert response.status_code == 200
            data = response.json()

            # Should not be blocked
            assert "tool_calls" in data["choices"][0]["message"]
            assert (
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "get_weather"
            )

    def test_session_override_takes_precedence(self, test_client, mock_openai_backend):
        """Test that session override takes precedence over server defaults."""
        # Configure the mock to return a response with tool calls
        tool_calls = [
            {
                "id": "call_abc123",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"location": "New York"}',
                },
            }
        ]
        mock_response = create_mock_response(tool_calls)
        mock_openai_backend.return_value = mock_response

        # First, set tool loop detection to disabled for the session
        response = test_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "!/set(tool-loop-detection=false)"}
                ],
            },
        )
        assert response.status_code == 200

        # Make multiple requests with the same tool call (well above threshold)
        for _ in range(6):
            response = test_client.post(
                "/v1/chat/completions",
                json=create_chat_completion_request(tool_calls=True),
            )
            assert response.status_code == 200
            data = response.json()

            # Should not be blocked because detection is disabled for the session
            assert "tool_calls" in data["choices"][0]["message"]
            assert (
                data["choices"][0]["message"]["tool_calls"][0]["function"]["name"]
                == "get_weather"
            )

        # Now enable it again with a lower threshold
        response = test_client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "!/set(tool-loop-detection=true)"},
                    {"role": "user", "content": "!/set(tool-loop-max-repeats=2)"},
                ],
            },
        )
        assert response.status_code == 200

        # Make one request
        response = test_client.post(
            "/v1/chat/completions",
            json=create_chat_completion_request(tool_calls=True),
        )
        assert response.status_code == 200
        data = response.json()
        assert "tool_calls" in data["choices"][0]["message"]

        # The next request should be blocked due to the lower threshold
        response = test_client.post(
            "/v1/chat/completions",
            json=create_chat_completion_request(tool_calls=True),
        )
        assert response.status_code == 200
        data = response.json()

        # Should have an error message instead of tool calls
        assert "tool_calls" not in data["choices"][0]["message"]
        assert "content" in data["choices"][0]["message"]
        assert "Tool call loop detected" in data["choices"][0]["message"]["content"]
        assert data["choices"][0]["finish_reason"] == "error"
