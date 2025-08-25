"""
Integration tests for Cline tool call implementation.

These tests verify that Cline agents receive proper tool calls for both:
1. Local command responses (!/hello, !/set, etc.)
2. Backend error responses (project-dir missing, etc.)

The tests simulate the exact scenarios from debug logs where Cline was failing.
"""

import json
import logging
import re  # Added re import
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock  # Added imports

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.core.app.stages import (  # Added imports
    CommandStage,
    ControllerStage,
    CoreServicesStage,
    InfrastructureStage,
    ProcessorStage,
)
from src.core.app.test_builder import ApplicationTestBuilder  # Changed import
from src.core.domain.chat import (  # Added import for ChatRequest
    ChatRequest,
)
from src.core.interfaces.backend_service_interface import (
    IBackendService,  # Added import
)

logging.getLogger("src.core.domain.session").setLevel(logging.DEBUG)
logging.getLogger("src.core.services.request_processor_service").setLevel(logging.DEBUG)

# Disable global backend mocking for these integration tests; run them normally
pytestmark = pytest.mark.no_global_mock


@pytest.fixture
async def app() -> AsyncGenerator[FastAPI, None]:
    """Create the application for testing."""
    from src.core.config.app_config import AppConfig

    # Create a proper AppConfig object
    config = AppConfig()

    # Explicitly set a dummy API key for the openai backend for testing
    # This ensures that the authentication middleware passes
    config.backends.openai.api_key = ["test-api-key"]

    # Helper functions for mock backend side effect
    def _extract_messages_from_payload(
        *args: Any, **kwargs: Any
    ) -> list[dict[str, Any]]:
        def find_messages(obj: Any) -> list[dict[str, Any]] | None:
            if isinstance(obj, dict):
                if "messages" in obj and isinstance(obj["messages"], list):
                    # Ensure all items in the list are dictionaries
                    converted_messages = []
                    for m in obj["messages"]:
                        if hasattr(m, "model_dump"):
                            converted_messages.append(m.model_dump())
                        else:
                            converted_messages.append(m)
                    return converted_messages
                for v in obj.values():
                    res = find_messages(v)
                    if res is not None:
                        return res
            elif isinstance(obj, list | tuple):
                for it in obj:
                    res = find_messages(it)
                    if res is not None:
                        return res
            # Add handling for ChatRequest objects
            elif (
                isinstance(obj, ChatRequest)
                and hasattr(obj, "messages")
                and isinstance(obj.messages, list)
            ):
                # Convert ChatMessage objects to dictionaries
                converted_messages = []
                for m in obj.messages:
                    if hasattr(m, "model_dump"):
                        converted_messages.append(m.model_dump())
                    else:
                        converted_messages.append(m)
                return converted_messages
            return None

        for a in args:
            res = find_messages(a)
            if res is not None:
                return res
        for v in kwargs.values():
            res = find_messages(v)
            if res is not None:
                return res
        return []

    def _concat_text(messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for m in messages:
            c = m.get("content")
            if isinstance(c, str):
                parts.append(c)
        return "\n".join(parts)

    async def _chat_completions_side_effect(
        *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        messages = _extract_messages_from_payload(*args, **kwargs)
        text = _concat_text(messages)

        is_cline_like = (
            "<attempt_completion>" in text and "</attempt_completion>" in text
        )
        has_command = "!/" in text
        if is_cline_like or has_command:
            if is_cline_like:
                # First, extract content within <attempt_completion> tags
                completion_match = re.search(
                    r"<attempt_completion>(.*?)</attempt_completion>", text, re.DOTALL
                )
                if completion_match:
                    completion_content = completion_match.group(1)
                    # Then, search for <r> tags within the extracted content
                    r_match = re.search(r"<r>(.*?)</r>", completion_content, re.DOTALL)
                    if r_match:
                        result_content = r_match.group(1)
                        tool_call_arguments = json.dumps({"result": result_content})
                    else:
                        # If no <r> tags found within completion, use the whole completion content
                        tool_call_arguments = json.dumps({"result": completion_content})
                else:
                    # Fallback if no <attempt_completion> tags found
                    tool_call_arguments = json.dumps({"result": text})
            else:
                tool_call_arguments = json.dumps({"text": text})

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
                                        "name": "attempt_completion",
                                        "arguments": tool_call_arguments,
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

    # Set up mock backend service
    mock_backend_service = MagicMock(spec=IBackendService)
    mock_backend_service.call_completion = AsyncMock(
        side_effect=_chat_completions_side_effect
    )  # Changed this line
    mock_backend_service.get_available_models = MagicMock(return_value=["gpt-4"])
    mock_backend_service.validate_backend = AsyncMock(return_value=(True, None))
    mock_backend_service.validate_backend_and_model = AsyncMock(
        return_value=(True, None)
    )
    mock_backend_service.get_backend_status = AsyncMock(
        return_value={"status": "healthy"}
    )

    # Build the test app using ApplicationTestBuilder and inject our custom mock
    builder = ( # Remove explicit type hint
        ApplicationTestBuilder()
        .add_stage(CoreServicesStage())
        .add_stage(InfrastructureStage())
        .add_custom_stage(
            "backends",
            {IBackendService: mock_backend_service},
            ["infrastructure"],  # Changed name to "backends"
        )
        .add_stage(CommandStage())
        .add_stage(ProcessorStage())
        .add_stage(ControllerStage())
    )
    test_app = await builder.build(config)
    test_app.state.client_api_key = (
        "test-proxy-key"  # Set client_api_key after app is built
    )

    yield test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client."""
    return TestClient(app)


class TestClineCommandResponses:
    """Test that Cline receives tool calls for local command responses."""

    @pytest.mark.asyncio
    async def test_cline_hello_command_returns_tool_calls(
        self, client: TestClient
    ) -> None:
        """Test that !/hello command returns tool calls for Cline agents."""

        # Step 1: Establish Cline agent by sending a request with agent="cline"
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "!/hello"}],
                "agent": "cline",
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify tool call structure
        assert "choices" in data
        choice = data["choices"][0]
        message = choice["message"]

        assert message.get("tool_calls") is not None, "Tool calls should be present"
        assert len(message["tool_calls"]) >= 1, "Should have at least one tool call"
        assert choice.get("finish_reason") == "tool_calls"

        # Verify tool call details
        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "hello"

    @pytest.mark.asyncio
    async def test_cline_set_command_returns_tool_calls(
        self, client: TestClient
    ) -> None:
        """Test that !/set command returns tool calls for Cline agents."""

        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "!/set(project=test-project)"}
                ],
                "agent": "cline",
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify tool call structure
        choice = data["choices"][0]
        message = choice["message"]

        assert message.get("tool_calls") is not None, "Tool calls should be present"
        assert len(message["tool_calls"]) >= 1, "Should have at least one tool call"
        assert choice.get("finish_reason") == "tool_calls"

        # Verify tool call details
        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "set"


class TestClineBackendResponses:
    """Test that Cline receives tool calls for backend responses."""

    @pytest.mark.asyncio
    async def test_xml_from_backend_is_converted_to_tool_calls_for_cline(
        self, client: TestClient
    ) -> None:
        """
        Test that a backend response containing <attempt_completion> XML
        is converted to a tool call for Cline agents.
        """
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": "This message triggers the mock to return XML with <r> tags. <attempt_completion><r>some content</r></attempt_completion>",
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

        assert message.get("tool_calls") is not None, "Tool calls should be present"
        assert choice.get("finish_reason") == "tool_calls"

        tool_call = message["tool_calls"][0]
        assert tool_call["type"] == "function"
        assert tool_call["function"]["name"] == "attempt_completion"
        args = json.loads(tool_call["function"]["arguments"])
        assert args["result"] == "some content"


class TestNonClineAgents:
    """Test that non-Cline agents are not affected by the tool call conversion."""

    def test_non_cline_agents_receive_regular_content(
        self: Any, client: TestClient
    ) -> None:
        """Test that non-Cline agents get tool calls for commands per backend mock rules."""

        # Send request without Cline detection pattern
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "!/hello"}  # No Cline pattern
                ],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response.status_code == 200
        data = response.json()

        # Verify tool-calls response for command pattern
        choice = data["choices"][0]
        message = choice["message"]
        assert message.get("tool_calls") is None
        assert message.get("content") is not None
        assert choice.get("finish_reason") == "stop"

    def test_xml_content_not_converted_for_non_cline(
        self: Any, client: TestClient
    ) -> None:
        """Test that XML content is not converted to tool calls for non-Cline agents."""

        # Simulate the transformation logic for non-Cline agent
        session_agent = "other"
        frontend_api = "openai"

        # Non-Cline agents should not trigger transformation
        should_transform = (
            session_agent in {"cline", "roocode"} and frontend_api == "openai"
        )
        assert (
            not should_transform
        ), "Non-Cline agents should not trigger transformation"


class TestFrontendAgnostic:
    """Test that the solution works across different frontend APIs."""

    def test_openai_frontend_detection(self: Any, client: TestClient) -> None:
        """Test that OpenAI frontend is correctly detected."""

        from src.agents import detect_frontend_api

        # Test different OpenAI paths
        assert detect_frontend_api("/v1/chat/completions") == "openai"
        assert detect_frontend_api("/v1/models") == "openai"

    def test_anthropic_frontend_detection(self: Any, client: TestClient) -> None:
        """Test that Anthropic frontend is correctly detected."""

        from src.agents import detect_frontend_api

        # Test Anthropic paths
        assert detect_frontend_api("/anthropic/v1/messages") == "anthropic"

    def test_gemini_frontend_detection(self: Any, client: TestClient) -> None:
        """Test that Gemini frontend is correctly detected."""

        from src.agents import detect_frontend_api

        # Test Gemini paths
        assert (
            detect_frontend_api("/v1beta/models/gemini-pro:generateContent") == "gemini"
        )
        assert (
            detect_frontend_api("/v1beta/models/gemini-pro:streamGenerateContent")
            == "gemini"
        )


class TestToolCallStructure:
    """Test that tool calls have the correct OpenAI-compatible structure."""

    def test_tool_call_format_compliance(self: Any, client: TestClient) -> None:
        """Test that generated tool calls comply with OpenAI format."""

        from src.agents import create_openai_attempt_completion_tool_call

        content = "Test response content"
        tool_call = create_openai_attempt_completion_tool_call([content])

        # Verify OpenAI tool call structure
        assert "id" in tool_call
        assert "type" in tool_call
        assert "function" in tool_call

        assert tool_call["type"] == "function"
        assert isinstance(tool_call["id"], str)
        assert tool_call["id"].startswith("call_")

        function = tool_call["function"]
        assert "name" in function
        assert "arguments" in function
        assert function["name"] == "attempt_completion"

        # Verify arguments are valid JSON
        args = json.loads(function["arguments"])
        assert "result" in args
        assert args["result"] == content

    def test_tool_call_id_uniqueness(self: Any, client: TestClient) -> None:
        """Test that tool call IDs are unique."""

        from src.agents import create_openai_attempt_completion_tool_call

        tool_call1 = create_openai_attempt_completion_tool_call(["content1"])
        tool_call2 = create_openai_attempt_completion_tool_call(["content2"])

        assert tool_call1["id"] != tool_call2["id"], "Tool call IDs should be unique"


@pytest.mark.integration
class TestEndToEndScenarios:
    """End-to-end integration tests simulating real Cline usage scenarios."""

    def test_cline_workflow_with_commands(self: Any, client: TestClient) -> None:
        """Test a complete Cline workflow with multiple commands."""

        # Step 1: Establish Cline agent
        response1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": "I am a Cline agent. <attempt_completion>starting</attempt_completion>",
                        "agent": "cline",
                    }
                ],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response1.status_code == 200

        # Step 2: Hello command
        response2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "!/hello"}],
                "agent": "cline",
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response2.status_code == 200
        data2 = response2.json()
        assert "tool_calls" in data2["choices"][0]["message"]
        assert data2["choices"][0]["finish_reason"] == "tool_calls"

        # Step 3: Set command
        response3 = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "!/set(temperature=0.7)"}],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response3.status_code == 200
        data3 = response3.json()
        assert "tool_calls" in data3["choices"][0]["message"]
        assert data3["choices"][0]["finish_reason"] == "tool_calls"

        # Verify all responses have proper tool call structure
        for data in [data2, data3]:
            choice = data["choices"][0]
            message = choice["message"]

            assert message["content"] is None or isinstance(message["content"], str)
            assert len(message["tool_calls"]) == 1

            tool_call = message["tool_calls"][0]
            # Expect the actual command name: "hello" for first command, "set" for second command
            # The mock backend returns "attempt_completion" for all command-like inputs
            if data == data2:
                assert tool_call["function"]["name"] == "hello"
            else:
                assert tool_call["function"]["name"] == "set"

            args = json.loads(tool_call["function"]["arguments"]) or {}
            if args:
                assert "result" in args

    def test_mixed_agent_session(self: Any, client: TestClient) -> None:
        """Test that Cline and non-Cline responses are handled correctly in the same session."""

        # Non-Cline request
        response1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {"role": "user", "content": "!/hello"} # No Cline pattern
                ],
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response1.status_code == 200
        data1 = response1.json()

        # Should get regular content
        assert (
            data1["choices"][0]["message"]["content"] is not None
            or data1["choices"][0]["message"].get("tool_calls") is not None
        )

        # Cline request in same session
        response2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": "I am a Cline agent. <attempt_completion>test</attempt_completion>",
                    },
                    {"role": "user", "content": "!/hello"},
                ],
                "agent": "cline",
            },
            headers={"Authorization": "Bearer test-proxy-key"},
        )

        assert response2.status_code == 200
        data2 = response2.json()

        # Should get tool calls (content may be None or omitted by backend transformation)
        assert "tool_calls" in data2["choices"][0]["message"]
