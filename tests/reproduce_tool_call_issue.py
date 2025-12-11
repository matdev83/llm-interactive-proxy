import json
import logging

from src.core.ports.streaming_contracts import StreamingContent


def test_tool_call_preservation():
    # Simulate Gemini Antigravity tool call chunk
    content = {
        "id": "chatcmpl-test",
        "object": "chat.completion.chunk",
        "created": 1234567890,
        "model": "claude-opus-4-5-thinking",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": "grep",
                                "arguments": '{"pattern": "foo", "path": "bar"}',
                            },
                        }
                    ]
                },
                "finish_reason": "tool_calls",
            }
        ],
    }

    chunk = StreamingContent(
        content=content, metadata={"finish_reason": "tool_calls"}, is_done=True
    )

    # Serialize to bytes (SSE)
    result_bytes = chunk.to_bytes()
    result_str = result_bytes.decode("utf-8")

    print(f"Result SSE:\n{result_str}")

    # Parse SSE
    lines = result_str.strip().split("\n")
    data_line = next(
        line for line in lines if line.startswith("data: ") and "[DONE]" not in line
    )
    data = json.loads(data_line[6:])

    # Check tool calls
    tool_calls = data["choices"][0]["delta"]["tool_calls"]
    print(f"Tool calls: {tool_calls}")

    args = tool_calls[0]["function"]["arguments"]
    if args != '{"pattern": "foo", "path": "bar"}':
        print("FAIL: Arguments mismatch!")
    else:
        print("PASS: Arguments preserved.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    test_tool_call_preservation()
