from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    MessageContentPartText,
)
from src.core.utils.token_count import extract_prompt_text
from src.core.utils.usage_recalculation import calculate_outbound_tokens


def test_extract_prompt_text_regression_pydantic_content_parts():
    """
    Regression test for the bug where Pydantic content parts resulted in 0 tokens.
    Verified that extract_prompt_text handles MessageContentPartText objects.
    """
    msg = ChatMessage(
        role="user",
        content=[MessageContentPartText(type="text", text="The quick brown fox")],
    )

    # Prior to fix, this returned an empty string
    text = extract_prompt_text([msg])
    assert text == "user: The quick brown fox"


def test_calculate_outbound_tokens_regression_canonical_request():
    """
    Regression test ensuring calculate_outbound_tokens correctly counts tokens
    for a CanonicalChatRequest with Pydantic-based message structures.
    """
    messages = [
        ChatMessage(role="system", content="You are a helpful assistant."),
        ChatMessage(
            role="user", content=[MessageContentPartText(type="text", text="Hello!")]
        ),
    ]
    request = CanonicalChatRequest(model="gpt-4o", messages=messages)

    tokens = calculate_outbound_tokens(request, model="gpt-4o")

    # "system: You are a helpful assistant.\nuser: Hello!"
    # Should definitely be more than 0
    assert tokens > 0
    # Heuristic check or exact check if tiktoken is available
    # system (1) + : (1) + space (1) + content (~6) + newline (1) + user (1) + ...
    assert tokens >= 10


def test_extract_prompt_text_mixed_formats():
    """
    Ensure the utility handles a mix of dicts and Pydantic objects.
    """
    messages = [
        {"role": "system", "content": "System message"},
        ChatMessage(
            role="user",
            content=[MessageContentPartText(type="text", text="User part")],
        ),
    ]

    text = extract_prompt_text(messages)
    assert "system: System message" in text
    assert "user: User part" in text


def test_calculate_outbound_tokens_includes_tool_definitions() -> None:
    """Regression: tool schemas must contribute to outbound prompt token count."""
    base_messages = [ChatMessage(role="user", content="Run tests and report status")]
    request_without_tools = CanonicalChatRequest(model="gpt-4o", messages=base_messages)

    large_schema_text = "detailed_tool_schema_token " * 400
    request_with_tools = CanonicalChatRequest(
        model="gpt-4o",
        messages=base_messages,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "run_full_validation_suite",
                    "description": large_schema_text,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {
                                "type": "string",
                                "description": large_schema_text,
                            }
                        },
                        "required": ["command"],
                    },
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {"name": "run_full_validation_suite"},
        },
    )

    tokens_without_tools = calculate_outbound_tokens(
        request_without_tools, model="gpt-4o"
    )
    tokens_with_tools = calculate_outbound_tokens(request_with_tools, model="gpt-4o")

    assert tokens_with_tools > tokens_without_tools
    assert tokens_with_tools - tokens_without_tools > 300
