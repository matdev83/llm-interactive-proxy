import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pytest_mock import MockerFixture
from src.connectors._openai_oauth_capabilities import CodexClientCapabilities
from src.connectors.openai_oauth import OpenAIOAuthConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
)
from src.core.domain.responses import ResponseEnvelope


@pytest_asyncio.fixture()
async def connector() -> AsyncIterator[OpenAIOAuthConnector]:
    client = httpx.AsyncClient()
    config = AppConfig()
    instance = OpenAIOAuthConnector(client=client, config=config)
    try:
        yield instance
    finally:
        await client.aclose()


def test_is_codex_model_detection(connector: OpenAIOAuthConnector) -> None:
    assert connector._is_codex_model("gpt-5-codex") is True
    assert connector._is_codex_model("codex-mini-latest") is True
    assert connector._is_codex_model("gpt-4.1") is False


@pytest.mark.asyncio
async def test_build_codex_payload_structure(connector: OpenAIOAuthConnector) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello Codex!")],
        model="gpt-5-codex",
        stream=True,
    )

    payload, conversation_id = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    assert payload["model"] == "gpt-5-codex"
    assert payload["stream"] is True
    assert payload["prompt_cache_key"] == conversation_id

    # With the refactoring, the main system prompt is in the `instructions` field
    assert "instructions" in payload
    assert payload["instructions"] == connector._codex_system_prompt()

    # The input items should contain the environment context and the user message
    input_items = payload["input"]
    assert len(input_items) == 2
    env_block = input_items[0]["content"][0]["text"]
    assert env_block.startswith("<environment_context>")
    assert "<model>" not in env_block
    assert "<approval_policy>never</approval_policy>" in env_block
    assert "<sandbox_mode>read-only</sandbox_mode>" in env_block
    assert "<network_access>restricted</network_access>" in env_block
    assert input_items[1]["role"] == "user"
    assert input_items[1]["content"][0]["type"] == "input_text"
    assert input_items[1]["content"][0]["text"] == "Hello Codex!"
    assert payload["reasoning"] == {"effort": "high", "summary": "auto"}
    assert payload["include"] == ["reasoning.encrypted_content"]
    tools = payload["tools"]
    names_by_type = {tool["name"]: tool["type"] for tool in tools}
    assert names_by_type["shell"] == "function"
    assert names_by_type["apply_patch"] == "custom"


@pytest.mark.asyncio
async def test_build_codex_payload_custom_prompt_mode(
    connector: OpenAIOAuthConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[
            ChatMessage(role="system", content="Stay curious"),
            ChatMessage(role="user", content="hello"),
        ],
        model="gpt-5-codex",
        extra_body={
            "codex_capabilities": {
                "prompt_mode": "custom_only",
                "include_environment_context": False,
            }
        },
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    assert payload.get("instructions") == "Stay curious"
    input_items = payload["input"]
    # There should only be one message, the user message
    assert len(input_items) == 1
    # First entry is the system message passed through as-is
    assert input_items[0]["role"] == "user"
    assert input_items[0]["content"][0]["text"] == "hello"
    # No environment block injected
    assert all(
        "<environment_context>" not in part["text"]
        for item in input_items
        for part in item.get("content", [])
        if part.get("type") == "input_text"
    )


@pytest.mark.asyncio
async def test_build_codex_payload_merge_custom_prompt(
    connector: OpenAIOAuthConnector,
) -> None:
    custom_prompt = "Behave like an expert pair programmer."
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hi!")],
        model="gpt-5-codex",
        extra_body={
            "codex_capabilities": {"prompt_mode": "merge_custom"},
            "codex_system_prompt": custom_prompt,
        },
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    instructions = payload.get("instructions", "")
    assert custom_prompt in instructions
    assert "You are Codex" in instructions


@pytest.mark.asyncio
async def test_codex_default_mode_merges_client_system_prompt(
    connector: OpenAIOAuthConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[
            ChatMessage(role="system", content="Prioritize security fixes."),
            ChatMessage(role="user", content="hello"),
        ],
        model="gpt-5-codex",
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    instructions = payload.get("instructions") or ""
    assert "You are Codex" in instructions
    assert "Prioritize security fixes." in instructions
    assert instructions.index("You are Codex") < instructions.index(
        "Prioritize security fixes."
    )


@pytest.mark.asyncio
async def test_codex_xml_mode_handles_structured_tool_calls(
    connector: OpenAIOAuthConnector,
) -> None:
    tool_call = ToolCall(
        id="call_structured",
        function=FunctionCall(name="shell", arguments='{"command":["ls"]}'),
    )
    assistant_msg = ChatMessage(role="assistant", tool_calls=[tool_call])
    tool_msg = ChatMessage(
        role="tool",
        content='{"output": "files", "exit_code": 0}',
        tool_call_id="call_structured",
    )
    user_msg = ChatMessage(role="user", content="List files")
    chat_request = ChatRequest(
        messages=[user_msg, assistant_msg, tool_msg],
        model="gpt-5-codex",
        extra_body={"codex_capabilities": {"tool_text_format": "codex_xml"}},
    )

    items = connector._build_codex_input_items(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    function_calls = [item for item in items if item["type"] == "function_call"]
    outputs = [item for item in items if item["type"] == "function_call_output"]

    assert len(function_calls) == 1
    assert len(outputs) == 1

    call_entry = function_calls[0]
    output_entry = outputs[0]

    assert call_entry["call_id"] == "call_structured"
    assert call_entry["name"] == "shell"
    assert json.loads(call_entry["arguments"])["command"] == ["ls"]

    parsed_output = json.loads(output_entry["output"])
    assert parsed_output["output"] == '{"output": "files", "exit_code": 0}'


@pytest.mark.asyncio
async def test_codex_passthrough_skips_translation(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    """Verify that native-like payloads bypass the translation method."""
    # This payload is structurally similar to a native Codex/Responses payload
    native_payload = {
        "model": "gpt-5-codex",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "hi"}]}],
        "stream": True,
    }

    # Mock the method that would be called if translation were to occur
    build_input_items_mock = mocker.patch.object(
        connector, "_build_codex_input_items", return_value=[]
    )

    # Simulate a passthrough scenario by directly passing the native payload
    # and setting the capabilities.
    capabilities = CodexClientCapabilities(codex_passthrough=True)
    payload, _ = connector._build_codex_payload(
        native_payload, [], "gpt-5-codex", capabilities=capabilities
    )

    # The payload should be the native one, with minor adjustments
    assert payload["model"] == "gpt-5-codex"
    assert payload["stream"] is True
    assert payload["input"][0]["role"] == "user"

    # The key assertion: translation was bypassed
    build_input_items_mock.assert_not_called()


@pytest.mark.asyncio
async def test_codex_headers_include_expected_fields() -> None:
    client = httpx.AsyncClient()
    config = AppConfig()
    connector = OpenAIOAuthConnector(client=client, config=config)
    headers = connector._build_codex_headers("conversation-id")
    assert headers["OpenAI-Beta"] == "responses=experimental"
    assert headers["conversation_id"] == "conversation-id"
    assert headers["session_id"] == "conversation-id"
    assert headers["Codex-Task-Type"] == "standard"
    assert headers["originator"] == connector.CODEX_ORIGINATOR
    assert headers["version"] == connector.CODEX_VERSION_HEADER
    assert "User-Agent" in headers
    await client.aclose()


@pytest.mark.asyncio
async def test_chat_completions_routes_to_codex_api(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        connector, "_validate_runtime_credentials", return_value=(True, [])
    )
    mocker.patch.object(connector, "_load_auth", AsyncMock(return_value=True))
    codex_mock = mocker.patch.object(
        connector, "_call_codex_responses_api", AsyncMock(return_value="codex-result")
    )
    super_mock = mocker.patch(
        "src.connectors.openai.OpenAIConnector.chat_completions", AsyncMock()
    )

    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello Codex!")],
        model="gpt-5-codex",
        stream=True,
    )

    result = await connector.chat_completions(
        chat_request, chat_request.messages, "gpt-5-codex"
    )

    assert result == "codex-result"
    codex_mock.assert_awaited_once()
    super_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chat_completions_non_codex_falls_back_to_parent(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        connector, "_validate_runtime_credentials", return_value=(True, [])
    )
    mocker.patch.object(connector, "_load_auth", AsyncMock(return_value=True))
    # Mock the authentication method to provide valid headers
    mocker.patch.object(
        connector,
        "get_headers",
        return_value={"Authorization": "Bearer test-token"},
    )
    codex_mock = mocker.patch.object(
        connector, "_call_codex_responses_api", AsyncMock(return_value="codex-result")
    )
    super_mock = mocker.patch(
        "src.connectors.openai.OpenAIConnector.chat_completions",
        AsyncMock(return_value="openai-result"),
    )

    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello classic OpenAI!")],
        model="gpt-4.1-mini",
        stream=False,
    )

    result = await connector.chat_completions(
        chat_request, chat_request.messages, "gpt-4.1-mini"
    )

    assert result == "openai-result"
    codex_mock.assert_not_called()
    super_mock.assert_awaited_once()


def test_resolve_capabilities_defaults(connector: OpenAIOAuthConnector) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
    )

    capabilities = connector._resolve_capabilities(chat_request)

    assert capabilities == CodexClientCapabilities()


def test_resolve_capabilities_from_extra_body(
    connector: OpenAIOAuthConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
        extra_body={
            "client_capabilities": {
                "protocol": "openai-responses",
                "codex_passthrough": True,
                "tool_text_format": "none",
            }
        },
    )

    capabilities = connector._resolve_capabilities(chat_request)

    assert capabilities.protocol == "openai-responses"
    assert capabilities.codex_passthrough is True
    # Fields not overridden should keep defaults
    assert capabilities.prompt_mode == CodexClientCapabilities().prompt_mode
    assert capabilities.tool_schema_mode == CodexClientCapabilities().tool_schema_mode
    # Explicit override respected
    assert capabilities.tool_text_format == "none"


def test_resolve_capabilities_for_cline_agent(
    connector: OpenAIOAuthConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
        agent="cline",
    )

    capabilities = connector._resolve_capabilities(chat_request)

    assert capabilities.tool_text_format == "codex_xml"


@pytest.mark.asyncio
async def test_codex_retries_after_token_refresh(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
        stream=False,
    )

    connector._build_codex_payload = mocker.Mock(return_value=({"input": []}, "cid-1"))  # type: ignore[attr-defined]
    connector._build_codex_headers = mocker.Mock(return_value={"Authorization": "Bearer test"})  # type: ignore[attr-defined]
    first_error = HTTPException(status_code=401, detail={"message": "unauthorized"})
    second_response = ResponseEnvelope(content={"ok": True})
    mocker.patch.object(
        connector,
        "_handle_non_streaming_response",
        AsyncMock(side_effect=[first_error, second_response]),
    )
    refresh_mock = mocker.patch.object(
        connector,
        "_refresh_access_token",
        AsyncMock(return_value=True),
    )

    result = await connector._call_codex_responses_api(
        chat_request,
        chat_request.messages,
        "gpt-5-codex",
        chat_request,
    )

    assert result is second_response
    connector._handle_non_streaming_response.assert_awaited()  # type: ignore[attr-defined]
    assert connector._handle_non_streaming_response.await_count == 2  # type: ignore[attr-defined]
    refresh_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_codex_input_items_function_call_and_output(
    connector: OpenAIOAuthConnector,
) -> None:
    tool_call = ToolCall(
        id="call_123",
        function=FunctionCall(name="shell", arguments='{"command":["ls"]}'),
    )
    assistant_message = ChatMessage(role="assistant", tool_calls=[tool_call])
    tool_message = ChatMessage(
        role="tool",
        content="exit code: 0",
        tool_call_id="call_123",
    )
    user_message = ChatMessage(role="user", content="List files")

    items = connector._build_codex_input_items(
        ChatRequest(
            messages=[user_message, assistant_message, tool_message],
            model="gpt-5-codex",
        ),
        [user_message, assistant_message, tool_message],
        "gpt-5-codex",
    )

    # env context + user + function call + output
    assert len(items) == 4
    assert items[0]["content"][0]["text"].startswith("<environment_context>")
    assert items[1]["role"] == "user"
    assert items[2]["type"] == "function_call"
    assert items[2]["call_id"] == "call_123"
    assert items[2]["name"] == "shell"
    assert items[2]["arguments"] == '{"command":["ls"]}'
    assert items[3]["type"] == "function_call_output"
    assert items[3]["call_id"] == "call_123"
    assert items[3]["output"] == '{"output": "exit code: 0"}'


@pytest.mark.asyncio
async def test_build_codex_input_items_textual_tool_flow(
    connector: OpenAIOAuthConnector,
) -> None:
    assistant_text = (
        "<execute_command>"
        "<command>bash -lc ls</command>"
        "<cwd>/workspace</cwd>"
        "</execute_command>"
    )
    user_text = (
        "[execute_command for 'bash -lc ls'] Result:\n"
        "Command executed in terminal  within working directory '/workspace'. Exit code: 0\n"
        "Output:\n\nfile_one\nfile_two\n"
    )
    messages = [
        ChatMessage(role="user", content="List project files"),
        ChatMessage(role="assistant", content=assistant_text),
        ChatMessage(role="user", content=user_text),
    ]

    chat_request = ChatRequest(
        messages=messages,
        model="gpt-5-codex",
        extra_body={"codex_capabilities": {"tool_text_format": "codex_xml"}},
    )

    items = connector._build_codex_input_items(
        chat_request,
        messages,
        "gpt-5-codex",
    )

    function_calls = [item for item in items if item["type"] == "function_call"]
    outputs = [item for item in items if item["type"] == "function_call_output"]

    assert len(function_calls) == 1
    assert len(outputs) == 1

    call_entry = function_calls[0]
    output_entry = outputs[0]

    assert call_entry["name"] == "shell"
    parsed_args = json.loads(call_entry["arguments"])
    assert parsed_args["command"] == ["bash", "-lc", "ls"]
    assert parsed_args["workdir"] == "/workspace"

    assert call_entry["call_id"] == output_entry["call_id"]
    parsed_output = json.loads(output_entry["output"])
    assert parsed_output["output"].startswith("file_one")
    assert parsed_output["exit_code"] == 0
    assert parsed_output["workdir"] == "/workspace"


@pytest.mark.asyncio
async def test_codex_refresh_failure_propagates(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
        stream=False,
    )

    connector._build_codex_payload = mocker.Mock(return_value=({"input": []}, "cid-1"))  # type: ignore[attr-defined]
    connector._build_codex_headers = mocker.Mock(return_value={"Authorization": "Bearer test"})  # type: ignore[attr-defined]
    first_error = HTTPException(status_code=401, detail={"message": "unauthorized"})
    mocker.patch.object(
        connector,
        "_handle_non_streaming_response",
        AsyncMock(side_effect=[first_error]),
    )
    refresh_mock = mocker.patch.object(
        connector,
        "_refresh_access_token",
        AsyncMock(return_value=False),
    )

    with pytest.raises(HTTPException):
        await connector._call_codex_responses_api(
            chat_request,
            chat_request.messages,
            "gpt-5-codex",
            chat_request,
        )

    refresh_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_api_http_error_propagation(
    connector: OpenAIOAuthConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5-codex",
        stream=False,
    )
    mocker.patch.object(
        connector, "_validate_runtime_credentials", return_value=(True, [])
    )
    mocker.patch.object(connector, "_load_auth", AsyncMock(return_value=True))
    mocker.patch.object(
        connector, "get_headers", return_value={"Authorization": "Bearer valid-token"}
    )
    error_response = httpx.Response(
        status_code=429,
        json={"error": "rate limit exceeded"},
        request=httpx.Request("POST", "https://example.com"),
    )
    mocker.patch.object(
        connector.client,
        "post",
        AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "Too Many Requests",
                response=error_response,
                request=error_response.request,
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await connector.chat_completions(
            chat_request, chat_request.messages, "gpt-5-codex"
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == {"error": "rate limit exceeded"}
