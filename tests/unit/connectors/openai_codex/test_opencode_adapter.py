from __future__ import annotations

from typing import Any, cast

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.client_families.opencode_adapter import (
    OpenCodeClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _build_context(
    *,
    tools: list[dict[str, Any]] | None = None,
    agent: str = "opencode",
) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
        tools=tools,
        agent=agent,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="user", content="hello"),
        ],
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id="session-1",
        metadata={"agent": agent},
    )


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def test_adapt_payload_dict_preserves_responses_native_structure() -> None:
    adapter = OpenCodeClientFamilyAdapter()
    context = _build_context()
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "id": "msg-1",
                "role": "developer",
                "metadata": {"source": "client"},
                "content": [{"type": "input_text", "text": "Client guidance"}],
                "item": {
                    "type": "message",
                    "id": "nested-msg-1",
                    "role": "assistant",
                },
            },
            {
                "type": "item_reference",
                "id": "ref-1",
                "metadata": {"origin": "upstream"},
            },
            {
                "type": "function_call",
                "id": "call-1",
                "call_id": "call-1",
                "name": "shell",
                "arguments": '{"command":"ls"}',
            },
            {
                "type": "function_call_output",
                "id": "out-1",
                "call_id": "call-1",
                "metadata": {"trace_id": "trace-1"},
                "output": {"status": "ok"},
            },
        ],
        "instructions": "Base instructions",
    }

    adapted = adapter.adapt_payload_dict(payload, context)
    adapted_input = cast(list[dict[str, Any]], adapted["input"])

    assert adapted_input[0]["id"] == "msg-1"
    assert adapted_input[0]["metadata"] == {"source": "client"}
    assert adapted_input[0]["item"]["id"] == "nested-msg-1"
    assert adapted_input[1]["type"] == "item_reference"
    assert adapted_input[1]["id"] == "ref-1"
    assert adapted_input[1]["metadata"] == {"origin": "upstream"}
    assert adapted_input[2]["id"] == "call-1"
    assert adapted_input[2]["name"] == "shell"
    assert adapted_input[3]["id"] == "out-1"
    assert adapted_input[3]["metadata"] == {"trace_id": "trace-1"}
    assert adapted_input[3]["output"] == {"status": "ok"}


def test_adapt_payload_dict_appends_bridge_once() -> None:
    adapter = OpenCodeClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }
        ],
        "instructions": "Base instructions",
        "tools": [_tool("bash")],
    }

    first = adapter.adapt_payload_dict(payload, context)
    second = adapter.adapt_payload_dict(first, context)

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("OpenCode compatibility mode") == 1
    assert second_instructions.count("OpenCode compatibility mode") == 1
    bridged_messages = [
        item
        for item in cast(list[dict[str, Any]], second["input"])
        if item["type"] == "message"
    ]
    assert (
        sum(
            1
            for item in bridged_messages
            if "OpenCode compatibility mode" in str(item.get("content"))
        )
        == 1
    )


def test_append_incompatible_tool_steering_is_transient_and_deduplicated() -> None:
    adapter = OpenCodeClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("apply_patch")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [],
        "instructions": "Base instructions",
    }

    first = adapter.append_incompatible_tool_steering(
        payload,
        ["browser_action"],
        context,
    )
    second = adapter.append_incompatible_tool_steering(
        first,
        ["read_file"],
        context,
    )

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("OpenCode incompatible tool retry") == 1
    assert second_instructions.count("OpenCode incompatible tool retry") == 1
    assert first_instructions == second_instructions


def test_detect_incompatible_tool_calls_honors_shell_aliases() -> None:
    adapter = OpenCodeClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("apply_patch")])
    tool_calls: list[dict[str, object]] = [
        {"function": {"name": "bash"}},
        {"function": {"name": "shell"}},
        {"function": {"name": "local_shell_call"}},
        {"function": {"name": "apply_patch"}},
        {"function": {"name": "browser_action"}},
    ]

    incompatible = adapter.detect_incompatible_tool_calls(tool_calls, context)

    assert incompatible == ["browser_action"]
