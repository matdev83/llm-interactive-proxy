"""
Property-based tests for Codebuff format conversion.

Tests Property 6: Format conversion validity
Validates: Requirements 2.2
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from src.codebuff.format_converter import FormatConverter


# Strategy for generating Codebuff message formats
@st.composite
def codebuff_message(draw):
    """Generate a valid Codebuff message."""
    message_format = draw(st.sampled_from(["role_content", "text", "message", "type"]))

    if message_format == "role_content":
        # Already in OpenAI format
        return {
            "role": draw(st.sampled_from(["user", "assistant", "system"])),
            "content": draw(st.text(min_size=0, max_size=100)),
        }
    elif message_format == "text":
        # Simple text format
        return {"text": draw(st.text(min_size=0, max_size=100))}
    elif message_format == "message":
        # Nested message format
        return {
            "message": {
                "role": draw(st.sampled_from(["user", "assistant", "system"])),
                "content": draw(st.text(min_size=0, max_size=100)),
            }
        }
    else:  # type format
        return {
            "type": draw(st.sampled_from(["user", "assistant", "system"])),
            "content": draw(st.text(min_size=0, max_size=100)),
        }


@st.composite
def codebuff_messages(draw):
    """Generate a list of Codebuff messages."""
    return draw(st.lists(codebuff_message(), min_size=0, max_size=10))


@st.composite
def session_state(draw):
    """Generate a session state dictionary."""
    return draw(
        st.fixed_dictionaries(
            {
                "conversation_history": st.lists(
                    st.dictionaries(st.text(), st.text()), max_size=5
                )
            }
        )
    )


@given(messages=codebuff_messages(), state=session_state())
def test_property_6_format_conversion_validity(messages, state):
    """
    Feature: codebuff-backend-compatibility, Property 6: Format conversion validity
    Validates: Requirements 2.2

    For any Codebuff message format, converting to OpenAI format should produce
    valid OpenAI-compatible messages.
    """
    converter = FormatConverter()

    # Convert messages
    openai_messages = converter.codebuff_to_openai(messages, state)

    # Verify all converted messages have required OpenAI fields
    for msg in openai_messages:
        assert isinstance(msg, dict), "Converted message must be a dictionary"
        assert "role" in msg, "Converted message must have 'role' field"
        assert "content" in msg, "Converted message must have 'content' field"
        assert msg["role"] in [
            "user",
            "assistant",
            "system",
        ], f"Role must be valid: {msg['role']}"
        assert isinstance(
            msg["content"], str
        ), f"Content must be a string: {type(msg['content'])}"


@given(messages=codebuff_messages(), state=session_state())
def test_property_6_conversion_preserves_count(messages, state):
    """
    Property 6 extension: Conversion should preserve message count.

    For any list of Codebuff messages, the number of converted messages
    should equal the number of input messages.
    """
    converter = FormatConverter()

    openai_messages = converter.codebuff_to_openai(messages, state)

    # Each input message should produce exactly one output message
    assert len(openai_messages) == len(
        messages
    ), f"Expected {len(messages)} messages, got {len(openai_messages)}"


@given(
    role=st.sampled_from(["user", "assistant", "system"]),
    content=st.text(min_size=0, max_size=100),
    state=session_state(),
)
def test_property_6_role_content_passthrough(role, content, state):
    """
    Property 6 extension: Messages already in OpenAI format should pass through.

    For any message already in OpenAI format (with role and content),
    the conversion should preserve the exact role and content.
    """
    converter = FormatConverter()

    messages = [{"role": role, "content": content}]
    openai_messages = converter.codebuff_to_openai(messages, state)

    assert len(openai_messages) == 1
    assert openai_messages[0]["role"] == role
    assert openai_messages[0]["content"] == content
