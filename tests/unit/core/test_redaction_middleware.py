"""
Tests for RedactionMiddleware to ensure prompt redaction and command filtering.
"""

from __future__ import annotations

import pytest
from src.core.domain.chat import (
    ChatMessage,
    ChatRequest,
    FunctionCall,
    MessageContentPartText,
    ToolCall,
)
from src.core.services.redaction_middleware import RedactionMiddleware


@pytest.mark.asyncio
async def test_redaction_middleware_redacts_text_and_parts() -> None:
    """Verify that secrets and proxy commands are removed from different content shapes."""
    # Arrange
    api_keys = ["sk-TESTSECRET12345"]  # Example dummy key
    mw = RedactionMiddleware(api_keys=api_keys, command_prefix="!/")

    # Request includes both string content and list-of-parts content
    # Commands are at the END of the last message to trigger filtering
    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(
                role="user",
                content=f"Use {api_keys[0]} for this",
            ),
            ChatMessage(
                role="user",
                content=[
                    MessageContentPartText(
                        type="text", text=f"Another {api_keys[0]} here"
                    ),
                    MessageContentPartText(type="text", text="please run !/help"),
                ],
            ),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert
    # First message (string content) got redacted, but no command to remove
    first = processed.messages[0].content
    assert isinstance(first, str)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in first

    # Second message (list of parts) got redacted and command at END was removed
    second = processed.messages[1].content
    assert isinstance(second, list)
    texts = []
    for p in second:
        if hasattr(p, "text"):
            texts.append(p.text)
        elif isinstance(p, dict) and "text" in p:
            texts.append(p["text"])
    combined = " ".join(t for t in texts if t)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in combined
    # Command !/help was at the end of the last text part, so it should be filtered
    assert "!/help" not in combined


@pytest.mark.asyncio
async def test_redaction_middleware_preserves_commands_in_tool_responses() -> None:
    """Verify that tool/function responses are not filtered for proxy commands.

    Tool responses (like file reads) may legitimately contain proxy command examples
    in documentation or code comments. These should not be filtered.
    """
    # Arrange
    api_keys = ["sk-TESTSECRET12345"]  # Example dummy key
    mw = RedactionMiddleware(api_keys=api_keys, command_prefix="!/")

    # Simulate a conversation with tool responses containing command examples
    req = ChatRequest(
        model="gpt-4o",
        messages=[
            # User asks a question
            ChatMessage(role="user", content="How do I use proxy commands?"),
            # Assistant makes a tool call to read README
            ChatMessage(
                role="assistant",
                content="Let me check the documentation",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        type="function",
                        function=FunctionCall(
                            name="read_file", arguments='{"path": "README.md"}'
                        ),
                    )
                ],
            ),
            # Tool response contains command examples from README
            ChatMessage(
                role="tool",
                tool_call_id="call_123",
                content=(
                    "# Proxy Commands\n\n"
                    "Use !/backend(openai) to switch backends.\n"
                    "Use !/model(gpt-4o-mini) to change models.\n"
                    "Use !/max for high reasoning mode.\n"
                    f"API key: {api_keys[0]}"
                ),
            ),
            # User sends a command (this should be filtered)
            ChatMessage(role="user", content="!/backend(openai)"),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert
    # Tool response should preserve commands (not filtered)
    tool_msg = processed.messages[2]
    assert tool_msg.role == "tool"
    assert isinstance(tool_msg.content, str)
    assert "!/backend(openai)" in tool_msg.content
    assert "!/model(gpt-4o-mini)" in tool_msg.content
    assert "!/max" in tool_msg.content
    # But API keys should still be redacted even in tool responses
    assert "(API_KEY_HAS_BEEN_REDACTED)" in tool_msg.content
    assert api_keys[0] not in tool_msg.content

    # User message should have command filtered
    user_msg = processed.messages[3]
    assert user_msg.role == "user"
    assert isinstance(user_msg.content, str)
    assert "!/backend" not in user_msg.content


@pytest.mark.asyncio
async def test_redaction_middleware_filters_function_role_like_tool() -> None:
    """Verify that 'function' role messages are treated like 'tool' role."""
    # Arrange
    mw = RedactionMiddleware(api_keys=[], command_prefix="!/")

    req = ChatRequest(
        model="gpt-4o",
        messages=[
            # Function response (legacy role name) with commands
            ChatMessage(
                role="function",
                name="read_file",
                content="Documentation: Use !/help to get help",
            ),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert - commands in function responses should be preserved
    func_msg = processed.messages[0]
    assert func_msg.role == "function"
    assert isinstance(func_msg.content, str)
    assert "!/help" in func_msg.content
