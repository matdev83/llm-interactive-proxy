import json
from typing import Any, cast

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
                                    "args": {"file_path": "CHQUALITY_VERIFIEROG.md"},
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
    assert delta["tool_calls"][0]["index"] == 0
    assert "content" not in delta
    # finish_reason must be tool_calls regardless of original STOP
    assert mapped["choices"][0]["finish_reason"] == "tool_calls"


def test_code_assist_stream_chunk_passes_through_openai_format_with_empty_choices() -> (
    None
):
    """Test that OpenAI-format chunks with empty choices (like usage-only chunks) are preserved.

    This is a regression test for a bug where usage-only chunks were incorrectly
    processed as native Code Assist format because the condition checked truthiness
    of choices (empty list is falsy) instead of key existence.
    """
    # Simulate an OpenAI-format usage-only chunk (empty choices, but has usage data)
    usage_chunk = {
        "id": "chatcmpl-test-123",
        "object": "chat.completion.chunk",
        "created": 1699000000,
        "model": "gemini-2.5-pro-latest",
        "choices": [],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150,
        },
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(usage_chunk)

    # Must preserve the original structure - NOT create a new chunk with "code-assist-model"
    assert mapped["id"] == "chatcmpl-test-123"
    assert mapped["model"] == "gemini-2.5-pro-latest"
    assert mapped["choices"] == []  # Empty choices preserved
    assert mapped["usage"]["prompt_tokens"] == 100
    assert mapped["usage"]["completion_tokens"] == 50
    assert mapped["usage"]["total_tokens"] == 150


def test_code_assist_stream_chunk_passes_through_openai_format_with_content() -> None:
    """Test that OpenAI-format chunks with content are passed through correctly."""
    # Simulate an OpenAI-format content chunk
    content_chunk = {
        "id": "chatcmpl-test-456",
        "object": "chat.completion.chunk",
        "created": 1699000000,
        "model": "gemini-2.5-pro-latest",
        "choices": [
            {
                "index": 0,
                "delta": {"content": "Hello, world!"},
                "finish_reason": None,
            }
        ],
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(content_chunk)

    # Must preserve the original structure
    assert mapped["id"] == "chatcmpl-test-456"
    assert mapped["model"] == "gemini-2.5-pro-latest"
    assert mapped["choices"][0]["delta"]["content"] == "Hello, world!"


def test_code_assist_stream_chunk_repairs_textual_tool_calls() -> None:
    chunk = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    "I will run checks.\n"
                                    "tool_call: bash for '.venv\\Scripts\\python.exe -m pytest tests/unit -v'\n"
                                    "tool_call: read for absolute_path 'C:\\Users\\Mateusz\\source\\repos\\demo\\client.py' offset 500 limit 20"
                                )
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(chunk)
    choice = mapped["choices"][0]
    delta = choice["delta"]
    tool_calls = delta.get("tool_calls")

    assert isinstance(tool_calls, list)
    assert len(tool_calls) == 2
    assert tool_calls[0]["function"]["name"] == "bash"
    assert json.loads(tool_calls[0]["function"]["arguments"]) == {
        "command": ".venv\\Scripts\\python.exe -m pytest tests/unit -v"
    }
    assert tool_calls[1]["function"]["name"] == "read"
    assert json.loads(tool_calls[1]["function"]["arguments"]) == {
        "absolute_path": "C:\\Users\\Mateusz\\source\\repos\\demo\\client.py",
        "offset": 500,
        "limit": 20,
    }
    assert delta.get("content") == "I will run checks."
    assert choice["finish_reason"] == "tool_calls"


def test_code_assist_stream_chunk_deduplicates_textual_tool_calls() -> None:
    chunk = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    "tool_call: bash for '.venv\\Scripts\\python.exe -m pytest tests/unit -v'\n"
                                    "tool_call: bash for '.venv\\Scripts\\python.exe -m pytest tests/unit -v'\n"
                                    "tool_call: read for absolute_path 'C:\\Users\\Mateusz\\source\\repos\\demo\\client.py' offset 500 limit 20\n"
                                    "tool_call: read for absolute_path 'C:\\Users\\Mateusz\\source\\repos\\demo\\client.py' offset 500 limit 20"
                                )
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(chunk)
    tool_calls = mapped["choices"][0]["delta"].get("tool_calls")

    assert isinstance(tool_calls, list)
    assert len(tool_calls) == 2
    assert tool_calls[0]["function"]["name"] == "bash"
    assert tool_calls[1]["function"]["name"] == "read"


def test_code_assist_stream_chunk_preserves_trailing_space_without_tool_calls() -> None:
    """Regression: content-only chunks must preserve trailing whitespace."""
    chunk = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "This project is a ",
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(chunk)
    content = mapped["choices"][0]["delta"].get("content")
    assert content == "This project is a "


def test_code_assist_stream_chunk_preserves_leading_newline_without_tool_calls() -> (
    None
):
    """Regression: content-only chunks must preserve leading newlines."""
    chunk = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": "\nThe project follows a modular architecture.",
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    mapped = Translation.code_assist_to_domain_stream_chunk(chunk)
    content = mapped["choices"][0]["delta"].get("content")
    assert content == "\nThe project follows a modular architecture."


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


def test_tool_result_message_only_has_function_response_not_text() -> None:
    """Tool messages should only produce functionResponse parts, not text parts.

    This prevents errors like "number of function response parts not equal to function call parts"
    that can occur if both text and functionResponse are in the same message.
    """
    tc = ToolCall(
        id="call_abc123",
        function=FunctionCall(name="TodoWrite", arguments='{"todos": []}'),
    )
    req = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(role="user", content="Create a TODO list"),
            ChatMessage(role="assistant", tool_calls=[tc]),
            ChatMessage(
                role="tool",
                tool_call_id="call_abc123",
                content="TODO List Updated",  # Plain string content
            ),
        ],
    )

    gemini = Translation.from_domain_to_gemini_request(req)
    contents = gemini["contents"]

    # Find the tool result message (should be role="user" with functionResponse)
    tool_result_content = contents[2]
    assert tool_result_content["role"] == "user"

    # Verify: ONLY functionResponse parts, NO text parts
    parts = tool_result_content["parts"]
    assert len(parts) == 1, "Tool result should have exactly one part"
    assert "functionResponse" in parts[0], "Part should be functionResponse"
    assert "text" not in parts[0], "Part should NOT have text key"

    # Verify the functionResponse has correct structure
    func_resp = parts[0]["functionResponse"]
    assert func_resp["name"] == "TodoWrite"
    # Response should wrap the string content
    assert "text" in func_resp["response"]
    assert func_resp["response"]["text"] == "TODO List Updated"


def test_thought_signature_server_side_injection() -> None:
    """Test that thought_signature can be injected server-side for clients that strip it.

    Some clients like Droid don't preserve extra_content when storing tool calls.
    The server must store and inject the signature from cache.
    """
    from src.connectors.gemini_base.thought_signature_service import (
        ThoughtSignatureService,
    )

    # Create a fresh service for testing (not using global)
    service = ThoughtSignatureService(use_global_cache=False)

    # Simulate a tool call without extra_content (as Droid would send)
    tc_without_sig = ToolCall(
        id="call_test123",
        type="function",
        function=FunctionCall(name="get_weather", arguments='{"city": "Paris"}'),
        extra_content=None,  # No signature - client stripped it
    )

    # Store a signature in the cache (simulating what happens when we receive a response)
    session_id = "test_session_abc"
    cache_key = f"{session_id}:{tc_without_sig.id}"
    # Use update() method to properly set cache entries (direct assignment doesn't work through property)
    service._manager.update({cache_key: "cached_signature_xyz"})

    # Create a request with the tool call
    req = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(role="user", content="What's the weather?"),
            ChatMessage(role="assistant", tool_calls=[tc_without_sig]),
        ],
    )

    # Inject signatures using the service
    service.inject_signatures(req, session_id)

    # Verify the signature was injected
    tool_calls = cast(list[ToolCall], req.messages[1].tool_calls)
    injected_tc = tool_calls[0]
    assert injected_tc.extra_content is not None
    assert "google" in injected_tc.extra_content
    assert (
        injected_tc.extra_content["google"]["thought_signature"]
        == "cached_signature_xyz"
    )


def test_thought_signature_preserved_in_function_call_round_trip() -> None:
    """Thought signature must be preserved when converting Gemini -> OpenAI -> Gemini.

    Gemini API requires thoughtSignature in functionCall parts for multi-turn
    conversations with tool use. This signature must be preserved through
    the OpenAI format conversion.
    """
    # Simulate a Gemini response part with functionCall and thoughtSignature
    gemini_part: dict[str, Any] = {
        "functionCall": {"name": "get_weather", "args": {"city": "Paris"}},
        "thoughtSignature": "test_signature_abc123",
    }

    # Process into ToolCall (should preserve signature)
    tool_call = Translation.process_gemini_function_call(
        cast(dict[str, Any], gemini_part["functionCall"]), part=gemini_part
    )

    # Verify extra_content contains the signature
    assert tool_call.extra_content is not None
    assert "google" in tool_call.extra_content
    assert (
        tool_call.extra_content["google"]["thought_signature"]
        == "test_signature_abc123"
    )

    # Now create a request with this tool call and convert back to Gemini
    req = CanonicalChatRequest(
        model="gemini-2.5-pro",
        messages=[
            ChatMessage(role="user", content="What's the weather?"),
            ChatMessage(role="assistant", tool_calls=[tool_call]),
        ],
    )

    gemini = Translation.from_domain_to_gemini_request(req)
    contents = gemini["contents"]

    # Find the assistant message with functionCall
    assistant_content = contents[1]
    assert assistant_content["role"] == "model"

    # Verify the thoughtSignature is preserved in the output
    parts = assistant_content["parts"]
    assert len(parts) == 1
    assert "functionCall" in parts[0]
    assert "thoughtSignature" in parts[0]
    assert parts[0]["thoughtSignature"] == "test_signature_abc123"


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
