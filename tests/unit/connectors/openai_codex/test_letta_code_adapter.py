from __future__ import annotations

from typing import Any, cast

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.client_families.letta_code_adapter import (
    LettaCodeClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage

_LETTA_PROMPT = (
    "You are Codex, a coding agent based on GPT-5.\n"
    "You have two channels for staying in conversation with the user:\n"
    "- You share updates in `commentary` channel.\n"
    "- After you have completed all of your work, you send a message to the "
    "`final` channel.\n"
)


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def _build_context(
    *,
    tools: list[dict[str, Any]] | None = None,
    agent: str = "letta-code/0.25.8",
    include_headers: bool = True,
    system_prompt: str = _LETTA_PROMPT,
) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[
            ChatMessage(role="developer", content=system_prompt),
            ChatMessage(role="user", content="hello"),
        ],
        stream=True,
        tools=tools,
        agent=agent,
    )
    metadata: dict[str, object] = {"agent": agent}
    if include_headers:
        metadata["headers"] = {
            "User-Agent": agent,
            "X-Letta-Source": "letta-code",
        }
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="developer", content=system_prompt),
            ProcessedMessage(role="user", content="hello"),
        ],
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id="session-1",
        metadata=metadata,
    )


def test_adapt_payload_dict_strips_letta_prompt_and_injects_bridge() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("ShellCommand"), _tool("ApplyPatch"), _tool("UpdatePlan")]
    )
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": _LETTA_PROMPT}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        ],
        "instructions": "Base instructions",
        "tools": [_tool("ShellCommand"), _tool("ApplyPatch"), _tool("UpdatePlan")],
    }

    adapted = adapter.adapt_payload_dict(payload, context)
    instructions = cast(str, adapted["instructions"])
    adapted_input = cast(list[dict[str, Any]], adapted["input"])

    assert "Letta Code compatibility mode" in instructions
    assert "CRITICAL INSTRUCTION:" in instructions
    assert "NEVER run cat inside a bash command" in instructions
    assert "ShellCommand" in instructions
    assert all(
        "two channels for staying in conversation with the user"
        not in str(item.get("content"))
        for item in adapted_input
    )
    assert (
        sum(
            1
            for item in adapted_input
            if "Letta Code compatibility mode" in str(item.get("content"))
        )
        == 1
    )
    assert (
        "available in this session: `ShellCommand`, `ApplyPatch`, `UpdatePlan`."
        in str(adapted_input[0].get("content"))
    )


def test_adapt_payload_dict_is_noop_for_non_letta_requests() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("bash")],
        agent="openai/js",
        include_headers=False,
        system_prompt="You are a coding assistant.",
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
        "tools": [_tool("bash")],
    }

    adapted = adapter.adapt_payload_dict(payload, context)
    assert adapted == payload


def test_detect_incompatible_tool_calls_for_pascal_toolset() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[
            _tool("ShellCommand"),
            _tool("ApplyPatch"),
            _tool("UpdatePlan"),
            _tool("Task"),
        ]
    )
    tool_calls: list[dict[str, object]] = [
        {"function": {"name": "ShellCommand"}},
        {"function": {"name": "shell"}},
        {"function": {"name": "bash"}},
        {"function": {"name": "ApplyPatch"}},
        {"function": {"name": "apply_patch"}},
        {"function": {"name": "UpdatePlan"}},
        {"function": {"name": "read_file"}},
    ]

    incompatible = adapter.detect_incompatible_tool_calls(tool_calls, context)

    assert incompatible == ["shell", "bash", "apply_patch", "read_file"]


def test_append_incompatible_tool_steering_is_transient_and_deduplicated() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(tools=[_tool("ShellCommand"), _tool("ApplyPatch")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [],
        "instructions": "Base instructions",
    }

    first = adapter.append_incompatible_tool_steering(
        payload,
        ["shell", "read_file"],
        context,
    )
    second = adapter.append_incompatible_tool_steering(
        first,
        ["bash"],
        context,
    )

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("Letta Code incompatible tool retry") == 1
    assert second_instructions.count("Letta Code incompatible tool retry") == 1
    assert first_instructions == second_instructions
    assert (
        "Do not call these incompatible tools again: shell, read_file."
        in first_instructions
    )


def test_detection_works_from_letta_agent_with_distinctive_toolset_without_headers() -> (
    None
):
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[
            _tool("Task"),
            _tool("TaskOutput"),
            _tool("TaskStop"),
            _tool("Skill"),
            _tool("ShellCommand"),
        ],
        agent="letta-code/0.25.8",
        include_headers=False,
        system_prompt="You are a coding assistant.",
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
        "tools": [
            _tool("Task"),
            _tool("TaskOutput"),
            _tool("TaskStop"),
            _tool("Skill"),
            _tool("ShellCommand"),
        ],
    }

    adapted = adapter.adapt_payload_dict(payload, context)
    instructions = cast(str, adapted["instructions"])
    assert "Letta Code compatibility mode" in instructions


def test_distinctive_toolset_without_letta_evidence_is_noop() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[
            _tool("Task"),
            _tool("TaskOutput"),
            _tool("TaskStop"),
            _tool("Skill"),
            _tool("ShellCommand"),
        ],
        agent="openai/js",
        include_headers=False,
        system_prompt="You are a coding assistant.",
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
        "tools": [
            _tool("Task"),
            _tool("TaskOutput"),
            _tool("TaskStop"),
            _tool("Skill"),
            _tool("ShellCommand"),
        ],
    }

    adapted = adapter.adapt_payload_dict(payload, context)

    assert adapted == payload


def test_bridge_message_uses_actual_supported_tool_labels() -> None:
    adapter = LettaCodeClientFamilyAdapter()
    context = _build_context(
        tools=[_tool("ShellCommand"), _tool("Task"), _tool("Skill")]
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
        "tools": [_tool("ShellCommand"), _tool("Task"), _tool("Skill")],
    }

    adapted = adapter.adapt_payload_dict(payload, context)
    adapted_input = cast(list[dict[str, Any]], adapted["input"])
    bridge_text = str(adapted_input[0].get("content"))

    assert "available in this session: `ShellCommand`, `Task`, `Skill`." in bridge_text
