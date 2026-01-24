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
        ChatMessage(role="user", content=[{"type": "text", "text": "User part"}]),
    ]

    text = extract_prompt_text(messages)
    assert "system: System message" in text
    assert "user: User part" in text
