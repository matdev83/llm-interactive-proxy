from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from src.core.domain.chat import (
    ChatCompletionChoice,
    ChatCompletionChoiceMessage,
    # CompletionUsage not present in domain; usage is dict in ChatResponse
    FunctionCall,
    ToolCall,
)
from src.core.domain.chat import (
    ChatResponse as ChatCompletionResponse,
)
from src.core.interfaces.backend_service_interface import IBackendService


def _dummy_openai_response() -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-123",
        object="chat.completion",
        created=1677652288,
        model="openrouter:some-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant", content="This is a test response."
                ),
                finish_reason="stop",
            )
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )


def _dummy_openai_tool_call_response(
    tool_call_dict: dict[str, Any],
) -> ChatCompletionResponse:
    return ChatCompletionResponse(
        id="chatcmpl-123",
        object="chat.completion",
        created=1677652288,
        model="openrouter:some-model",
        choices=[
            ChatCompletionChoice(
                index=0,
                message=ChatCompletionChoiceMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ToolCall(
                            id=str(tool_call_dict["id"]),
                            type=str(tool_call_dict["type"]),
                            function=FunctionCall(
                                name=str(tool_call_dict["function"]["name"]),
                                arguments=str(tool_call_dict["function"]["arguments"]),
                            ),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )


@pytest.mark.asyncio
async def test_anthropic_messages_non_streaming(test_client: TestClient):
    """Test the Anthropic API compatibility endpoint for non-streaming requests."""

    anthropic_request = {
        "model": "some-model",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello, world!"}],
    }

    # Get the backend service from the service provider
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    # Patch the backend service's call_completion method
    with patch.object(
        backend_service, "call_completion", new_callable=AsyncMock
    ) as mock_call_completion:
        # Import the ChatResponse class
        from src.core.domain.chat import ChatResponse

        # Return a proper ChatResponse object instead of a tuple
        dummy_response = _dummy_openai_response()
        mock_call_completion.return_value = ChatResponse.from_legacy_response(
            dummy_response.model_dump(exclude_none=True)
        )

        response = test_client.post(
            "/v1/messages",
            json=anthropic_request,
        )

        if response.status_code != 200:
            print(f"Response status: {response.status_code}")
            print(f"Response content: {response.text}")
            print(f"Response headers: {response.headers}")

        assert response.status_code == 200
        response_data = response.json()

        # Debug: print actual response structure
        print(f"Actual response: {response_data}")

        assert response_data["content"][0]["text"] == "This is a test response."
        assert (
            response_data["stop_reason"] == "end_turn"
        )  # OpenAI "stop" maps to Anthropic "end_turn"
        assert response_data["usage"]["input_tokens"] == 10
        assert response_data["usage"]["output_tokens"] == 20

        mock_call_completion.assert_called_once()
        # Check the call arguments for the mocked function
        args, kwargs = mock_call_completion.call_args
        # Print debug info to see what arguments were actually passed
        # print(f"Args: {args}")
        # print(f"Kwargs: {kwargs}")

        # The request should be in kwargs with key 'request'
        openai_request = kwargs.get("request")
        if openai_request is None and len(args) > 1:
            # If not in kwargs, it might be the second positional argument (first is self)
            openai_request = args[1]
        elif openai_request is None and len(args) == 1:
            # If only one arg, it might be the request
            openai_request = args[0]

        assert openai_request is not None
        assert openai_request.model == "some-model"
        assert len(openai_request.messages) == 1
        assert openai_request.messages[0].role == "user"
        assert openai_request.messages[0].content == "Hello, world!"
        assert not openai_request.stream


@pytest.mark.asyncio
async def test_anthropic_messages_with_tool_use_from_openai_tool_calls(
    test_client: TestClient,
):
    """OpenAI tool_calls should map to Anthropic tool_use content blocks."""
    anthropic_request = {
        "model": "some-model",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Hello!"}],
    }

    tool_call_dict: dict[str, Any] = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'},
    }

    # Get the backend service from the service provider
    backend_service = test_client.app.state.service_provider.get_required_service(
        IBackendService
    )

    with patch.object(
        backend_service, "call_completion", new_callable=AsyncMock
    ) as mock_call_completion:
        # Import the ChatResponse class
        from src.core.domain.chat import ChatResponse

        # Return a proper ChatResponse object instead of a tuple
        dummy_response = _dummy_openai_tool_call_response(tool_call_dict)
        mock_call_completion.return_value = ChatResponse.from_legacy_response(
            dummy_response.model_dump(exclude_none=True)
        )

        response = test_client.post(
            "/v1/messages",
            json=anthropic_request,
        )

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["content"][0]["type"] == "tool_use"
        assert response_data["content"][0]["name"] == "get_weather"
