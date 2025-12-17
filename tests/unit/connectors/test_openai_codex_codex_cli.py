import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import HTTPException
from pytest_mock import MockerFixture
from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex import OpenAICodexConnector
from src.core.config.app_config import AppConfig
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    ToolCall,
)
from src.core.domain.responses import (
    ResponseEnvelope,
    StreamingResponseEnvelope,
    StreamingResponseHandle,
)
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.tool_text_renderer import (
    OverrideRenderer,
    render_tool_call,
    reset_renderer_registry,
)


@pytest_asyncio.fixture()
async def connector() -> AsyncIterator[OpenAICodexConnector]:
    reset_renderer_registry()
    client = httpx.AsyncClient()
    config = AppConfig()
    instance = OpenAICodexConnector(client=client, config=config)
    try:
        yield instance
    finally:
        await client.aclose()


def test_is_codex_model_detection(connector: OpenAICodexConnector) -> None:
    """Test that _is_codex_model only recognizes supported Codex models.

    Supported models are explicitly listed in SUPPORTED_CODEX_MODELS:
    - gpt-5.1-codex-max
    - gpt-5.1-codex
    - gpt-5.1-codex-mini
    - gpt-5.1
    """
    # Valid models (with and without vendor prefix)
    assert connector._is_codex_model("gpt-5.1-codex-max") is True
    assert connector._is_codex_model("gpt-5.1-codex") is True
    assert connector._is_codex_model("gpt-5.1-codex-mini") is True
    assert connector._is_codex_model("gpt-5.1") is True
    assert connector._is_codex_model("openai/gpt-5.1-codex-max") is True
    assert connector._is_codex_model("openai/gpt-5.1") is True

    # Invalid models
    assert (
        connector._is_codex_model("gpt-5-codex") is False
    )  # Old naming (no .1), not supported
    assert (
        connector._is_codex_model("codex-mini-latest") is False
    )  # Not a supported model
    assert connector._is_codex_model("gpt-4.1") is False
    assert connector._is_codex_model("gpt-4") is False
    assert connector._is_codex_model("claude-3") is False


@pytest.mark.asyncio
async def test_build_codex_payload_structure(connector: OpenAICodexConnector) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello Codex!")],
        model="gpt-5.1-codex",
        stream=True,
    )

    payload, conversation_id = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5.1-codex"
    )

    assert payload["model"] == "gpt-5.1-codex"
    assert payload["stream"] is True
    assert payload["prompt_cache_key"] == conversation_id

    # With the refactoring, the main system prompt is in the `instructions` field
    assert "instructions" in payload
    expected_prompt = connector._sanitize_codex_instructions(
        connector._codex_system_prompt()
    ).rstrip()
    assert payload["instructions"].rstrip() == expected_prompt

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
    assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert payload["include"] == ["reasoning.encrypted_content"]
    tools = payload["tools"]
    names_by_type = {tool["name"]: tool["type"] for tool in tools}
    assert names_by_type["shell"] == "function"
    assert names_by_type["apply_patch"] == "custom"


@pytest.mark.asyncio
async def test_build_codex_payload_custom_prompt_mode(
    connector: OpenAICodexConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[
            ChatMessage(role="system", content="Stay curious"),
            ChatMessage(role="user", content="hello"),
        ],
        model="gpt-5.1-codex",
        extra_body={
            "codex_capabilities": {
                "prompt_mode": "custom_only",
                "include_environment_context": False,
            }
        },
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5.1-codex"
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
    connector: OpenAICodexConnector,
) -> None:
    custom_prompt = "Behave like an expert pair programmer."
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hi!")],
        model="gpt-5.1-codex",
        extra_body={
            "codex_capabilities": {"prompt_mode": "merge_custom"},
            "codex_system_prompt": custom_prompt,
        },
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5.1-codex"
    )

    instructions = payload.get("instructions", "")
    assert custom_prompt in instructions
    assert "You are Codex" in instructions


@pytest.mark.asyncio
async def test_codex_default_mode_merges_client_system_prompt(
    connector: OpenAICodexConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[
            ChatMessage(role="system", content="Prioritize security fixes."),
            ChatMessage(role="user", content="hello"),
        ],
        model="gpt-5.1-codex",
    )

    payload, _ = connector._build_codex_payload(
        chat_request, chat_request.messages, "gpt-5.1-codex"
    )

    instructions = (payload.get("instructions") or "").rstrip()
    expected_prompt = connector._sanitize_codex_instructions(
        connector._codex_system_prompt()
    ).rstrip()
    assert instructions == expected_prompt

    input_items = payload["input"]
    assert len(input_items) == 3
    user_block = input_items[0]
    assert user_block["role"] == "user"
    assert user_block["content"][0]["type"] == "input_text"
    assert user_block["content"][0]["text"].startswith("<user_instructions>")
    assert "Prioritize security fixes." in user_block["content"][0]["text"]
    env_block = input_items[1]
    assert env_block["content"][0]["text"].startswith("<environment_context>")


@pytest.mark.asyncio
async def test_codex_xml_mode_handles_structured_tool_calls(
    connector: OpenAICodexConnector,
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
        model="gpt-5.1-codex",
        extra_body={"codex_capabilities": {"tool_text_format": "codex_xml"}},
    )

    items = connector._build_codex_input_items(
        chat_request, chat_request.messages, "gpt-5.1-codex"
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
async def test_config_default_capabilities_from_backend_extra() -> None:
    reset_renderer_registry()
    config = AppConfig()
    config.backends.openai_codex.extra.setdefault("codex", {}).update(
        {
            "default_capabilities": {
                "tool_text_format": "codex_xml",
                "include_environment_context": False,
            }
        }
    )
    async with httpx.AsyncClient() as client:
        connector = OpenAICodexConnector(client=client, config=config)
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="gpt-5.1-codex",
        )
        capabilities = connector._resolve_capabilities(chat_request)
        assert capabilities.tool_text_format == "codex_xml"
        assert capabilities.include_environment_context is False
    reset_renderer_registry()


@pytest.mark.asyncio
async def test_prompt_configuration_applies_prepend_append() -> None:
    reset_renderer_registry()
    config = AppConfig()
    config.backends.openai_codex.extra.setdefault("codex", {}).update(
        {
            "prompt": {
                "prepend": ["<environment constraints>"],
                "append": ["<end of rules>"],
            }
        }
    )
    async with httpx.AsyncClient() as client:
        connector = OpenAICodexConnector(client=client, config=config)
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="gpt-5.1-codex",
        )
        payload, _ = connector._build_codex_payload(
            chat_request, chat_request.messages, "gpt-5.1-codex"
        )
        instructions = payload.get("instructions", "")
        assert instructions.startswith("<environment constraints>")
        assert instructions.endswith("<end of rules>")
    reset_renderer_registry()


@pytest.mark.asyncio
async def test_tool_schema_configuration_overrides_default() -> None:
    reset_renderer_registry()
    config = AppConfig()
    config.backends.openai_codex.extra.setdefault("codex", {}).update(
        {
            "tool_schema": {
                "base_tools": [
                    {
                        "type": "function",
                        "name": "echo",
                        "description": "Echo text back",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                            "required": ["text"],
                        },
                    }
                ]
            }
        }
    )
    async with httpx.AsyncClient() as client:
        connector = OpenAICodexConnector(client=client, config=config)
        tools = connector._default_codex_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"
    reset_renderer_registry()


@pytest.mark.asyncio
async def test_tool_schema_custom_only_uses_config_defaults() -> None:
    reset_renderer_registry()
    config = AppConfig()
    config.backends.openai_codex.extra.setdefault("codex", {}).update(
        {
            "tool_schema": {
                "custom_tools": [
                    {
                        "type": "function",
                        "name": "workspace_info",
                        "description": "Returns workspace metadata",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ]
            }
        }
    )
    async with httpx.AsyncClient() as client:
        connector = OpenAICodexConnector(client=client, config=config)
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="gpt-5.1-codex",
            extra_body={"codex_capabilities": {"tool_schema_mode": "custom_only"}},
        )
        payload, _ = connector._build_codex_payload(
            chat_request, chat_request.messages, "gpt-5.1-codex"
        )
        tools = payload.get("tools", [])
        assert len(tools) == 1
        assert tools[0]["name"] == "workspace_info"
    reset_renderer_registry()


@pytest.mark.asyncio
async def test_renderer_configuration_alias_and_default() -> None:
    reset_renderer_registry()
    config = AppConfig()
    config.backends.openai_codex.extra.setdefault("codex", {}).update(
        {"renderer": {"aliases": {"cli": "xml"}, "default": "cli"}}
    )
    async with httpx.AsyncClient() as client:
        connector = OpenAICodexConnector(client=client, config=config)
        chat_request = ChatRequest(
            messages=[ChatMessage(role="user", content="hello")],
            model="gpt-5.1-codex",
        )
        capabilities = connector._resolve_capabilities(chat_request)
        renderer_key = connector._select_renderer_key(capabilities)
        assert renderer_key == "cli"
        tool_call = ToolCall(
            id="call-1",
            function=FunctionCall(name="shell", arguments='{"command":["ls"]}'),
        )
        with OverrideRenderer(renderer_key):
            rendered = render_tool_call(tool_call)
        assert rendered and rendered.startswith("<execute_command>")
    reset_renderer_registry()


@pytest.mark.asyncio
async def test_codex_passthrough_skips_translation(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    """Verify that native-like payloads bypass the translation method."""
    # This payload is structurally similar to a native Codex/Responses payload
    native_payload = {
        "model": "gpt-5.1-codex",
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
        native_payload, [], "gpt-5.1-codex", capabilities=capabilities
    )

    # The payload should be the native one, with minor adjustments
    assert payload["model"] == "gpt-5.1-codex"
    assert payload["stream"] is True
    assert payload["input"][0]["role"] == "user"

    # The key assertion: translation was bypassed
    build_input_items_mock.assert_not_called()


@pytest.mark.asyncio
async def test_codex_headers_include_expected_fields() -> None:
    client = httpx.AsyncClient()
    config = AppConfig()
    connector = OpenAICodexConnector(client=client, config=config)
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
async def test_streaming_refresh_rebuilds_authorization_header(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        model="gpt-5.1-codex",
        stream=True,
    )
    payload = {
        "model": "gpt-5.1-codex",
        "input": [],
        "tools": [],
        "prompt_cache_key": "conv-123",
        "stream": True,
    }
    mocker.patch.object(
        connector, "_build_codex_payload", return_value=(payload, "conv-123")
    )
    mocker.patch.object(
        connector, "_resolve_capabilities", return_value=CodexClientCapabilities()
    )

    connector.api_key = "token_old"
    connector._auth_credentials = {"tokens": {"access_token": "token_old"}}
    connector._stream_retry_limit = 2
    connector._stream_retry_backoff = (0.0, 0.0, 0.0)

    refresh_count = 0

    async def refresh_stub() -> bool:
        nonlocal refresh_count
        refresh_count += 1
        connector.api_key = f"token_new_{refresh_count}"
        return True

    refresh_mock = mocker.patch.object(
        connector, "_refresh_access_token", side_effect=refresh_stub
    )

    headers_seen: list[str | None] = []
    call_count = 0

    async def _successful_event_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(content={"event": "ok"})

    success_handle = StreamingResponseHandle(
        iterator=_successful_event_iterator(),
        cancel_callback=AsyncMock(),
        headers={"Authorization": "Bearer token_new_2"},
    )

    async def streaming_side_effect(
        url: str,
        request_payload: dict[str, Any],
        request_headers: dict[str, str],
        request_session_id: str,
        stream_format: str,
    ) -> StreamingResponseHandle:
        nonlocal call_count
        headers_seen.append(request_headers.get("Authorization"))
        call_count += 1
        if call_count <= 2:
            raise HTTPException(status_code=401, detail="expired")
        return success_handle

    mocker.patch.object(
        connector,
        "_handle_streaming_response",
        side_effect=streaming_side_effect,
    )

    result = await connector._call_codex_responses_api(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-5.1-codex",
        domain_request=request,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunk = await result.content.__anext__()
    assert isinstance(chunk, ProcessedResponse)
    assert chunk.content == {"event": "ok"}
    assert headers_seen == [
        "Bearer token_old",
        "Bearer token_new_1",
        "Bearer token_new_2",
    ]
    assert refresh_mock.await_count == 2


@pytest.mark.asyncio
async def test_streaming_auth_failure_chunk_triggers_retry(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        model="gpt-5.1-codex",
        stream=True,
    )
    payload = {
        "model": "gpt-5.1-codex",
        "input": [],
        "tools": [],
        "prompt_cache_key": "conv-123",
        "stream": True,
    }
    mocker.patch.object(
        connector, "_build_codex_payload", return_value=(payload, "conv-123")
    )
    mocker.patch.object(
        connector, "_resolve_capabilities", return_value=CodexClientCapabilities()
    )

    connector.api_key = "token_old"
    connector._auth_credentials = {"tokens": {"access_token": "token_old"}}
    connector._stream_retry_limit = 2
    connector._stream_retry_backoff = (0.0, 0.0, 0.0)

    refresh_count = 0

    async def refresh_stub() -> bool:
        nonlocal refresh_count
        refresh_count += 1
        connector.api_key = f"token_new_{refresh_count}"
        return True

    refresh_mock = mocker.patch.object(
        connector, "_refresh_access_token", side_effect=refresh_stub
    )

    async def failing_iterator(
        status: int, code: str
    ) -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={
                "error": "Responses stream reported failure",
                "details": {"status": status, "code": code},
            }
        )

    async def success_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={
                "choices": [
                    {"index": 0, "delta": {"content": "hello"}, "finish_reason": None}
                ]
            }
        )

    cancel_first = AsyncMock()
    cancel_second = AsyncMock()
    cancel_third = AsyncMock()
    first_handle = StreamingResponseHandle(
        iterator=failing_iterator(401, "authentication_error"),
        cancel_callback=cancel_first,
        headers={"Authorization": "Bearer token_old"},
    )
    second_handle = StreamingResponseHandle(
        iterator=failing_iterator(401, "token_expired"),
        cancel_callback=cancel_second,
        headers={"Authorization": "Bearer token_new_1"},
    )
    success_handle = StreamingResponseHandle(
        iterator=success_iterator(),
        cancel_callback=cancel_third,
        headers={"Authorization": "Bearer token_new_2"},
    )

    stream_handles = [first_handle, second_handle, success_handle]
    headers_seen: list[str | None] = []

    def handle_side_effect(
        url: str,
        request_payload: dict[str, Any],
        request_headers: dict[str, str],
        request_session_id: str,
        stream_format: str,
    ) -> StreamingResponseHandle:
        headers_seen.append(request_headers.get("Authorization"))
        return stream_handles.pop(0)

    handle_mock = mocker.patch.object(
        connector, "_handle_streaming_response", side_effect=handle_side_effect
    )

    result = await connector._call_codex_responses_api(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-5.1-codex",
        domain_request=request,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    chunk = await result.content.__anext__()
    assert isinstance(chunk, ProcessedResponse)
    assert chunk.content is not None
    assert chunk.content["choices"][0]["delta"]["content"] == "hello"
    assert headers_seen == [
        "Bearer token_old",
        "Bearer token_new_1",
        "Bearer token_new_2",
    ]
    assert refresh_mock.await_count == 2
    cancel_first.assert_awaited_once()
    cancel_second.assert_awaited_once()
    cancel_third.assert_not_called()
    assert handle_mock.call_count == 3
    # Failure chunk must not be forwarded to the caller
    with pytest.raises(StopAsyncIteration):
        await result.content.__anext__()
    assert result.headers is not None
    assert dict(result.headers) == {"Authorization": "Bearer token_new_2"}


@pytest.mark.asyncio
async def test_streaming_handshake_exceeds_retry_limit(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        model="gpt-5.1-codex",
        stream=True,
    )
    payload = {
        "model": "gpt-5.1-codex",
        "input": [],
        "tools": [],
        "prompt_cache_key": "conv-limit",
        "stream": True,
    }
    mocker.patch.object(
        connector, "_build_codex_payload", return_value=(payload, "conv-limit")
    )
    mocker.patch.object(
        connector, "_resolve_capabilities", return_value=CodexClientCapabilities()
    )

    connector.api_key = "token_old"
    connector._auth_credentials = {"tokens": {"access_token": "token_old"}}
    connector._stream_retry_limit = 1
    connector._stream_retry_backoff = (0.0,)

    async def refresh_stub() -> bool:
        connector.api_key = "token_new_1"
        return True

    refresh_mock = mocker.patch.object(
        connector, "_refresh_access_token", side_effect=refresh_stub
    )
    degrade_mock = mocker.patch.object(connector, "_degrade")

    headers_seen: list[str | None] = []

    async def streaming_side_effect(
        url: str,
        request_payload: dict[str, Any],
        request_headers: dict[str, str],
        request_session_id: str,
        stream_format: str,
    ) -> StreamingResponseHandle:
        headers_seen.append(request_headers.get("Authorization"))
        raise HTTPException(status_code=401, detail="expired")

    mocker.patch.object(
        connector, "_handle_streaming_response", side_effect=streaming_side_effect
    )

    result = await connector._call_codex_responses_api(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-5.1-codex",
        domain_request=request,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    with pytest.raises(HTTPException) as exc_info:
        await result.content.__anext__()

    assert exc_info.value.status_code == 401
    assert refresh_mock.await_count == 1
    degrade_mock.assert_called_once()
    degrade_messages = degrade_mock.call_args[0][0]
    assert any("handshake" in msg for msg in degrade_messages)
    assert headers_seen == ["Bearer token_old", "Bearer token_new_1"]


@pytest.mark.asyncio
async def test_streaming_auth_failure_chunk_unrecoverable(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="hi")],
        model="gpt-5.1-codex",
        stream=True,
    )
    payload = {
        "model": "gpt-5.1-codex",
        "input": [],
        "tools": [],
        "prompt_cache_key": "conv-321",
        "stream": True,
    }
    mocker.patch.object(
        connector, "_build_codex_payload", return_value=(payload, "conv-321")
    )
    mocker.patch.object(
        connector, "_resolve_capabilities", return_value=CodexClientCapabilities()
    )

    connector.api_key = "stale"
    connector._auth_credentials = {"tokens": {"access_token": "stale"}}
    connector._stream_retry_limit = 2
    connector._stream_retry_backoff = (0.0, 0.0)

    mocker.patch.object(
        connector, "_refresh_access_token", AsyncMock(return_value=False)
    )
    degrade_mock = mocker.patch.object(connector, "_degrade")

    async def failing_iterator() -> AsyncIterator[ProcessedResponse]:
        yield ProcessedResponse(
            content={
                "error": "Responses stream reported failure",
                "details": {"status": 401, "code": "invalid_token"},
            }
        )

    cancel_cb = AsyncMock()
    stream_handle = StreamingResponseHandle(
        iterator=failing_iterator(),
        cancel_callback=cancel_cb,
        headers={"Authorization": "Bearer stale"},
    )

    def handle_side_effect(
        url: str,
        request_payload: dict[str, Any],
        request_headers: dict[str, str],
        request_session_id: str,
        stream_format: str,
    ) -> StreamingResponseHandle:
        return stream_handle

    mocker.patch.object(
        connector, "_handle_streaming_response", side_effect=handle_side_effect
    )

    result = await connector._call_codex_responses_api(
        request_data=request,
        processed_messages=request.messages,
        effective_model="gpt-5.1-codex",
        domain_request=request,
    )

    assert isinstance(result, StreamingResponseEnvelope)
    assert result.content is not None
    with pytest.raises(HTTPException) as exc_info:
        await result.content.__anext__()

    assert exc_info.value.status_code == 401
    degrade_mock.assert_called_once()
    degrade_messages = degrade_mock.call_args[0][0]
    assert any("token refresh" in msg for msg in degrade_messages)
    cancel_cb.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_completions_routes_to_codex_api(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    mocker.patch.object(
        connector, "_validate_runtime_credentials", return_value=(True, [])
    )
    mocker.patch.object(connector, "_load_auth", AsyncMock(return_value=True))
    connector.api_key = "Bearer test-token"
    codex_mock = mocker.patch.object(
        connector, "_call_codex_responses_api", AsyncMock(return_value="codex-result")
    )
    super_cls = type(connector).__mro__[1]
    super_mock = mocker.patch.object(super_cls, "chat_completions", AsyncMock())

    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="Hello Codex!")],
        model="gpt-5.1-codex",
        stream=True,
    )

    result = await connector.chat_completions(
        chat_request, chat_request.messages, "gpt-5.1-codex"
    )

    assert result == "codex-result"
    codex_mock.assert_awaited_once()
    super_mock.assert_not_called()


@pytest.mark.asyncio
async def test_chat_completions_non_codex_falls_back_to_parent(
    connector: OpenAICodexConnector, mocker: MockerFixture
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
    connector.api_key = "Bearer test-token"
    codex_mock = mocker.patch.object(
        connector, "_call_codex_responses_api", AsyncMock(return_value="codex-result")
    )
    super_cls = type(connector).__mro__[1]
    super_mock = mocker.patch.object(
        super_cls, "chat_completions", AsyncMock(return_value="openai-result")
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


def test_resolve_capabilities_defaults(connector: OpenAICodexConnector) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
    )

    capabilities = connector._resolve_capabilities(chat_request)

    assert capabilities == CodexClientCapabilities()


def test_resolve_capabilities_from_extra_body(
    connector: OpenAICodexConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
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
    connector: OpenAICodexConnector,
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
        agent="cline",
    )

    capabilities = connector._resolve_capabilities(chat_request)

    assert capabilities.tool_text_format == "codex_xml"


@pytest.mark.asyncio
async def test_codex_retries_after_token_refresh(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
        stream=False,
    )

    mocker.patch.object(connector, "_build_codex_payload", return_value=({"input": []}, "cid-1"))  # type: ignore[arg-type]
    mocker.patch.object(connector, "_build_codex_headers", return_value={"Authorization": "Bearer test"})  # type: ignore[arg-type]
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
        "gpt-5.1-codex",
        chat_request,
    )

    assert result is second_response
    connector._handle_non_streaming_response.assert_awaited()  # type: ignore[attr-defined]
    assert connector._handle_non_streaming_response.await_count == 2  # type: ignore[attr-defined]
    refresh_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_codex_input_items_function_call_and_output(
    connector: OpenAICodexConnector,
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
            model="gpt-5.1-codex",
        ),
        [user_message, assistant_message, tool_message],
        "gpt-5.1-codex",
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
    connector: OpenAICodexConnector,
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
        model="gpt-5.1-codex",
        extra_body={"codex_capabilities": {"tool_text_format": "codex_xml"}},
    )

    items = connector._build_codex_input_items(
        chat_request,
        messages,
        "gpt-5.1-codex",
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
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
        stream=False,
    )

    mocker.patch.object(connector, "_build_codex_payload", return_value=({"input": []}, "cid-1"))  # type: ignore[arg-type]
    mocker.patch.object(connector, "_build_codex_headers", return_value={"Authorization": "Bearer test"})  # type: ignore[arg-type]
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
            "gpt-5.1-codex",
            chat_request,
        )

    refresh_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_codex_api_http_error_propagation(
    connector: OpenAICodexConnector, mocker: MockerFixture
) -> None:
    chat_request = ChatRequest(
        messages=[ChatMessage(role="user", content="hello")],
        model="gpt-5.1-codex",
        stream=False,
    )
    mocker.patch.object(
        connector, "_validate_runtime_credentials", return_value=(True, [])
    )
    mocker.patch.object(connector, "_load_auth", AsyncMock(return_value=True))
    mocker.patch.object(
        connector, "get_headers", return_value={"Authorization": "Bearer valid-token"}
    )
    connector.api_key = "Bearer valid-token"
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
            chat_request, chat_request.messages, "gpt-5.1-codex"
        )

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == {"error": "rate limit exceeded"}
