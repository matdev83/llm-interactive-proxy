from __future__ import annotations

from src.core.utils.token_count import count_tokens, extract_prompt_text


def test_regression_tool_calls_accounted_in_token_count():
    """
    REGRESSION TEST: Ensures that tool_calls in assistant messages are included
    in the extracted prompt text and thus accounted for in token counting.

    This fixes a bug where tool calls were ignored, leading to severe
    under-reporting of prompt tokens for agentic workflows.
    """
    # Large payload in tool arguments to make the difference significant
    large_payload = "very_unique_token_sequence " * 100

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "write_file",
                        "arguments": f'{{"path": "test.txt", "content": "{large_payload}"}}',
                    },
                }
            ],
        },
    ]

    extracted_text = extract_prompt_text(messages)

    # 1. Verify content is actually in the extracted text
    assert (
        "write_file" in extracted_text
    ), "Tool name missing from extracted prompt text"
    assert (
        "very_unique_token_sequence" in extracted_text
    ), "Tool arguments missing from extracted prompt text"

    # 2. Verify token count reflects the large payload
    token_count = count_tokens(extracted_text)

    # "very_unique_token_sequence " * 100 is at least several hundred tokens.
    # If tool_calls are ignored, only "system: You are a helpful assistant." remains (~10 tokens).
    assert (
        token_count > 200
    ), f"Token count ({token_count}) is too low, likely ignoring tool_calls"


def test_regression_multiple_tool_calls_accounted():
    """Ensures multiple tool calls in a single message are all accounted for."""
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"function": {"name": "tool_a", "arguments": "{}"}},
                {"function": {"name": "tool_b", "arguments": "{}"}},
            ],
        }
    ]
    extracted = extract_prompt_text(messages)
    assert "tool_a" in extracted
    assert "tool_b" in extracted
    assert extracted.count("assistant (tool_call)") == 2


def test_regression_object_based_messages_with_tools():
    """Ensures tool_calls on objects (e.g. Pydantic models) are also handled."""

    class MockFunction:
        def __init__(self, name, arguments):
            self.name = name
            self.arguments = arguments

    class MockToolCall:
        def __init__(self, function):
            self.function = function

    class MockMessage:
        def __init__(self, role, content, tool_calls=None):
            self.role = role
            self.content = content
            self.tool_calls = tool_calls

    messages = [
        MockMessage(
            role="assistant",
            content=None,
            tool_calls=[MockToolCall(MockFunction("my_tool", '{"arg": 1}'))],
        )
    ]

    extracted = extract_prompt_text(messages)
    assert 'assistant (tool_call): my_tool({"arg": 1})' in extracted
