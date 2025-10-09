import json

from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    ToolCall,
)
from src.core.domain.translation import Translation


def test_code_assist_stream_chunk_maps_function_call_and_forces_finish_reason() -> None:
    # Simulate a Code Assist SSE data JSON parsed into dict
    chunk = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "Read",
                                    "args": {"file_path": "CHANGELOG.md"},
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(chunk)
    assert mapped["object"] == "chat.completion.chunk"
    delta = mapped["choices"][0]["delta"]
    # Tool call is present and content omitted
    assert "tool_calls" in delta and isinstance(delta["tool_calls"], list)
    assert "content" not in delta
    # finish_reason must be tool_calls regardless of original STOP
    assert mapped["choices"][0]["finish_reason"] == "tool_calls"


def test_assistant_tool_calls_only_mapped_to_function_call_parts() -> None:
    # Assistant with tool_calls and no textual content should be accepted
    tc = ToolCall(
        id="call_1", function=FunctionCall(name="Read", arguments='{"file_path": "X"}')
    )
    req = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", tool_calls=[tc]),
            ChatMessage(role="tool", tool_call_id="call_1", content='{"ok": true}'),
        ],
    )

    gemini = Translation.from_domain_to_gemini_request(req)
    contents = gemini["contents"]
    # Expect three contents; second should contain functionCall, third functionResponse
    assert len(contents) == 3
    assert contents[1]["role"] == "model"
    parts_assistant = contents[1]["parts"]
    assert any("functionCall" in p for p in parts_assistant)
    assert contents[2]["role"] == "user"
    parts_tool = contents[2]["parts"]
    assert any("functionResponse" in p for p in parts_tool)


def test_tools_grouped_and_sanitized_for_code_assist() -> None:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "a",
                "description": "",
                "parameters": {"type": "object", "$schema": "http://json"},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "b",
                "description": "",
                "parameters": {"type": "object", "exclusiveMinimum": 1},
            },
        },
    ]

    req = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[ChatMessage(role="user", content="hi")],
        tools=tools,
    )
    gemini = Translation.from_domain_to_gemini_request(req)
    assert "tools" in gemini
    assert isinstance(gemini["tools"], list) and len(gemini["tools"]) == 1
    fdecl = gemini["tools"][0]["function_declarations"]
    assert {fd["name"] for fd in fdecl} == {"a", "b"}
    # Ensure forbidden keys removed
    for fd in fdecl:
        params = fd.get("parameters", {})
        assert "$schema" not in json.dumps(params)
        assert "exclusiveMinimum" not in json.dumps(params)
