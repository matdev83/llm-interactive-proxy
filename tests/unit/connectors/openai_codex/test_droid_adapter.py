from __future__ import annotations

from typing import Any, cast

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.client_families.droid_adapter import (
    DroidClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def _build_context(
    *,
    tools: list[dict[str, Any]] | None = None,
    agent: str = "factory-cli/0.27.1",
    system_prompt: str | None = None,
) -> CodexRequestContext:
    messages = [ChatMessage(role="user", content="hello")]
    processed_messages = [ProcessedMessage(role="user", content="hello")]
    if system_prompt is not None:
        messages.insert(0, ChatMessage(role="system", content=system_prompt))
        processed_messages.insert(
            0, ProcessedMessage(role="system", content=system_prompt)
        )

    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=messages,
        stream=True,
        tools=tools,
        agent=agent,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=processed_messages,
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id="session-droid-1",
        metadata={
            "agent": agent,
            "headers": {"User-Agent": agent},
        },
    )


def test_droid_bridge_prompt_includes_critical_shell_and_file_rules() -> None:
    adapter = DroidClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("Read"), _tool("Execute"), _tool("Skill"), _tool("fff_grep")]
    )
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            }
        ],
        "instructions": "Base",
        "tools": [_tool("Read"), _tool("Execute")],
    }
    adapted = adapter.adapt_payload_dict(payload, context)
    instructions = cast(str, adapted["instructions"])
    assert "CRITICAL INSTRUCTION:" in instructions
    assert "NEVER run cat inside a bash command" in instructions
    assert "DO NOT use bash commands like ls for listing" in instructions
    assert "Droid agent" in instructions


def test_adapt_payload_dict_appends_droid_bridge_once() -> None:
    adapter = DroidClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("Read"), _tool("Execute"), _tool("Skill"), _tool("fff_grep")]
    )
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
        "tools": [_tool("Read"), _tool("Execute")],
    }

    first = adapter.adapt_payload_dict(payload, context)
    second = adapter.adapt_payload_dict(first, context)

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("Factory Droid compatibility mode") == 1
    assert second_instructions.count("Factory Droid compatibility mode") == 1
    assert "`Skill`" in first_instructions
    assert "`fff_grep`" in first_instructions
    assert (
        "Preserve extra already-available tools such as `Skill`, `Task`, or `fff___*`"
        in first_instructions
    )

    bridged_messages = [
        item
        for item in cast(list[dict[str, Any]], second["input"])
        if item["type"] == "message"
    ]
    assert (
        sum(
            1
            for item in bridged_messages
            if "Factory Droid compatibility mode" in str(item.get("content"))
        )
        == 1
    )


def test_detect_incompatible_tool_calls_treats_codex_aliases_as_supported() -> None:
    adapter = DroidClientFamilyAdapter()
    context = _build_context(tools=[_tool("Read"), _tool("Execute"), _tool("Edit")])
    tool_calls: list[dict[str, object]] = [
        {"function": {"name": "Read"}},
        {"function": {"name": "read_file"}},
        {"function": {"name": "shell"}},
        {"function": {"name": "bash"}},
        {"function": {"name": "apply_patch"}},
        {"function": {"name": "browser_action"}},
    ]

    incompatible = adapter.detect_incompatible_tool_calls(tool_calls, context)

    assert incompatible == ["browser_action"]


def test_append_incompatible_tool_steering_mentions_droid_tools() -> None:
    adapter = DroidClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("Read"), _tool("Execute"), _tool("Edit"), _tool("Skill")]
    )
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [],
        "instructions": "Base instructions",
    }

    adapted = adapter.append_incompatible_tool_steering(
        payload,
        ["read_file", "shell"],
        context,
    )

    instructions = cast(str, adapted["instructions"])
    assert "Factory Droid incompatible tool retry" in instructions
    assert "Read" in instructions
    assert "Execute" in instructions
    assert "Skill" in instructions
    assert (
        "Keep using any extra tools that are already available in this session"
        in instructions
    )
    assert (
        "Do not call these incompatible tools again: read_file, shell." in instructions
    )
