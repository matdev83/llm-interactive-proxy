from __future__ import annotations

from typing import Any, cast

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.client_families.pi_adapter import (
    PiClientFamilyAdapter,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage

_PI_PROMPT = (
    "You are an expert coding assistant operating inside pi, a coding agent harness.\n"
    "Available tools:\n"
    "- bash: Execute bash commands (ls, grep, find, etc.)\n"
    "Current working directory: C:/Users/Mateusz/source/repos/llm-interactive-proxy\n"
)


def _build_context(
    *,
    tools: list[dict[str, Any]] | None = None,
    agent: str = "OpenAI/JS 6.26.0",
) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model="gpt-5.1-codex",
        messages=[
            ChatMessage(role="developer", content=_PI_PROMPT),
            ChatMessage(role="user", content="hello"),
        ],
        stream=True,
        tools=tools,
        agent=agent,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[
            ProcessedMessage(role="developer", content=_PI_PROMPT),
            ProcessedMessage(role="user", content="hello"),
        ],
        effective_model="gpt-5.1-codex",
        capabilities=CodexClientCapabilities(),
        session_id="session-1",
        metadata={"agent": agent},
    )


def _tool(name: str) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name}}


def test_pi_bridge_prompt_includes_critical_shell_and_file_rules() -> None:
    adapter = PiClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("read"), _tool("edit")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": _PI_PROMPT}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        ],
        "instructions": "Base",
        "tools": [_tool("bash"), _tool("read"), _tool("edit")],
    }
    adapted = adapter.adapt_payload_dict(payload, context)
    instructions = cast(str, adapted["instructions"])
    assert "CRITICAL INSTRUCTION:" in instructions
    assert "NEVER run cat inside a bash command" in instructions
    assert "DO NOT use bash commands like ls for listing" in instructions
    assert "pi agent" in instructions


def test_adapt_payload_dict_removes_pi_prompt_and_inserts_bridge_once() -> None:
    adapter = PiClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("read"), _tool("edit")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": _PI_PROMPT}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hello"}],
            },
        ],
        "instructions": "Base instructions",
        "tools": [_tool("bash"), _tool("read"), _tool("edit")],
    }

    first = adapter.adapt_payload_dict(payload, context)
    second = adapter.adapt_payload_dict(first, context)

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("Pi compatibility mode") == 1
    assert second_instructions.count("Pi compatibility mode") == 1

    adapted_input = cast(list[dict[str, Any]], second["input"])
    assert adapted_input[0]["role"] == "developer"
    assert "Pi compatibility mode" in str(adapted_input[0]["content"])
    normalized_text = "\n".join(str(item.get("content")) for item in adapted_input)
    assert "operating inside pi" not in normalized_text.lower()


def test_detect_incompatible_tool_calls_uses_pi_tool_allowlist() -> None:
    adapter = PiClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("read"), _tool("edit")])
    tool_calls: list[dict[str, object]] = [
        {"function": {"name": "bash"}},
        {"function": {"name": "read"}},
        {"function": {"name": "edit"}},
        {"function": {"name": "apply_patch"}},
        {"function": {"name": "shell"}},
    ]

    incompatible = adapter.detect_incompatible_tool_calls(tool_calls, context)

    assert incompatible == ["apply_patch", "shell"]


def test_append_incompatible_tool_steering_is_deduplicated() -> None:
    adapter = PiClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash"), _tool("read"), _tool("edit")])
    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [],
        "instructions": "Base instructions",
    }

    first = adapter.append_incompatible_tool_steering(
        payload,
        ["apply_patch"],
        context,
    )
    second = adapter.append_incompatible_tool_steering(
        first,
        ["shell"],
        context,
    )

    first_instructions = cast(str, first["instructions"])
    second_instructions = cast(str, second["instructions"])
    assert first_instructions.count("Pi incompatible tool retry") == 1
    assert second_instructions.count("Pi incompatible tool retry") == 1
    assert first_instructions == second_instructions


def test_pi_detection_requires_multiple_prompt_markers() -> None:
    adapter = PiClientFamilyAdapter()
    context = _build_context(tools=[_tool("bash")])
    context.processed_messages = [
        ProcessedMessage(
            role="developer",
            content="Current working directory: C:/Users/Mateusz/source/repos/llm-interactive-proxy",
        ),
        ProcessedMessage(role="user", content="hello"),
    ]
    object.__setattr__(
        context.request,
        "messages",
        [
            ChatMessage(
                role="developer",
                content="Current working directory: C:/Users/Mateusz/source/repos/llm-interactive-proxy",
            ),
            ChatMessage(role="user", content="hello"),
        ],
    )

    payload: dict[str, object] = {
        "model": "gpt-5.1-codex",
        "input": [],
        "instructions": "Base instructions",
        "tools": [_tool("bash")],
    }

    adapted = adapter.adapt_payload_dict(payload, context)

    assert adapted == payload
