from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    ToolCall,
)
from src.core.domain.translators.code_assist.streaming import (
    code_assist_to_domain_stream_chunk,
)
from src.core.domain.translators.gemini.request import from_domain_to_gemini_request


def test_gemini_request_excludes_assistant_text_with_tools():
    # Regression test for: assistant text must be excluded when tool calls are present
    req = CanonicalChatRequest(
        model="gemini-2.0-pro",
        messages=[
            ChatMessage(
                role="assistant",
                content="I will read the files now.",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        function=FunctionCall(
                            name="read_file",
                            arguments='{"path": "test.txt"}',
                        ),
                    )
                ],
            )
        ],
    )
    translated = from_domain_to_gemini_request(req)

    # Check that both text and functionCall parts are present in the same content item
    parts = translated["contents"][0]["parts"]
    has_text = any(
        "text" in p and p["text"] == "I will read the files now." for p in parts
    )
    has_tool = any("functionCall" in p for p in parts)

    assert not has_text, "Assistant text content should be excluded"
    assert has_tool, "Tool call was stripped"


def test_code_assist_streaming_finish_reason_wait():
    # Regression test for: premature finish_reason stopping stream accumulation

    # Chunk 1: Tool call but NO finishReason from backend
    chunk1 = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "read_file",
                                    "args": {"path": "file1.txt"},
                                    "id": "call_1",
                                }
                            }
                        ]
                    }
                }
            ]
        }
    }

    # Chunk 2: Another tool call AND finishReason from backend
    chunk2 = {
        "response": {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "read_file",
                                    "args": {"path": "file2.txt"},
                                    "id": "call_2",
                                }
                            }
                        ]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    }

    translated1 = code_assist_to_domain_stream_chunk(chunk1)
    translated2 = code_assist_to_domain_stream_chunk(chunk2)

    # Chunk 1 should have NO finish_reason, allowing clients to continue reading
    assert translated1["choices"][0]["finish_reason"] is None

    # Chunk 2 should have "tool_calls" (mapped from Gemini STOP when tool calls are present)
    assert translated2["choices"][0]["finish_reason"] == "tool_calls"


if __name__ == "__main__":
    # Allow running directly for quick verification
    try:
        test_gemini_request_excludes_assistant_text_with_tools()
        test_code_assist_streaming_finish_reason_wait()
        print("All regression tests PASSED")
    except Exception as e:
        print(f"Regression tests FAILED: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
