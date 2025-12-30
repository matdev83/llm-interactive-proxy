"""
Tests for RedactionMiddleware to ensure API key redaction.

Note: Command filtering and proxy response removal are no longer handled by
RedactionMiddleware. These are now handled by the non-forwardable message tagging
system.
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
from src.core.services.redaction_cache import (
    get_global_redaction_cache,
    reset_global_redaction_cache,
)
from src.core.services.redaction_middleware import RedactionMiddleware


@pytest.fixture(autouse=True)
def reset_cache():
    """Reset the global redaction cache before and after each test."""
    reset_global_redaction_cache()
    yield
    reset_global_redaction_cache()


@pytest.mark.asyncio
async def test_redaction_middleware_redacts_text_and_parts() -> None:
    """Verify that API keys are redacted from different content shapes."""
    # Arrange
    api_keys = ["sk-TESTSECRET12345"]  # Example dummy key
    mw = RedactionMiddleware(api_keys=api_keys)

    # Request includes both string content and list-of-parts content
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
    # First message (string content) got redacted
    first = processed.messages[0].content
    assert isinstance(first, str)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in first

    # Second message (list of parts) got redacted
    second = processed.messages[1].content
    assert isinstance(second, list)
    texts = []
    for p in second:
        if isinstance(p, MessageContentPartText):
            texts.append(p.text)
        elif isinstance(p, dict) and "text" in p:
            texts.append(p["text"])
    combined = " ".join(t for t in texts if t)
    assert "(API_KEY_HAS_BEEN_REDACTED)" in combined
    # Commands are NOT filtered by RedactionMiddleware (handled by tagging system)
    assert "!/help" in combined


@pytest.mark.asyncio
async def test_redaction_middleware_preserves_commands_in_tool_responses() -> None:
    """Verify that API keys are redacted but commands are preserved in all messages.

    Commands are no longer filtered by RedactionMiddleware - they are handled
    by the non-forwardable message tagging system.
    """
    # Arrange
    api_keys = ["sk-TESTSECRET12345"]  # Example dummy key
    mw = RedactionMiddleware(api_keys=api_keys)

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
            # User sends a command (should NOT be filtered by RedactionMiddleware)
            ChatMessage(role="user", content="!/backend(openai)"),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert
    # Tool response should preserve commands and redact API keys
    tool_msg = processed.messages[2]
    assert tool_msg.role == "tool"
    assert isinstance(tool_msg.content, str)
    assert "!/backend(openai)" in tool_msg.content
    assert "!/model(gpt-4o-mini)" in tool_msg.content
    assert "!/max" in tool_msg.content
    # But API keys should still be redacted even in tool responses
    assert "(API_KEY_HAS_BEEN_REDACTED)" in tool_msg.content
    assert api_keys[0] not in tool_msg.content

    # User message should preserve commands (not filtered by RedactionMiddleware)
    user_msg = processed.messages[3]
    assert user_msg.role == "user"
    assert isinstance(user_msg.content, str)
    assert "!/backend(openai)" in user_msg.content


@pytest.mark.asyncio
async def test_redaction_middleware_preserves_function_role_messages() -> None:
    """Verify that 'function' role messages are preserved unchanged."""
    # Arrange
    mw = RedactionMiddleware(api_keys=[])

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


@pytest.mark.asyncio
async def test_redaction_middleware_does_not_remove_proxy_responses() -> None:
    """Regression: Verify that proxy responses are NOT removed by RedactionMiddleware.

    Proxy response removal is now handled by the non-forwardable message tagging system.
    """
    # Arrange
    mw = RedactionMiddleware(api_keys=[])

    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="Some previous message"),
            ChatMessage(role="user", content="!/backend(test)"),
            ChatMessage(
                role="assistant",
                content="Proxy command executed.",
                metadata={"is_proxy_response": True},
            ),
            ChatMessage(role="user", content="Now, please write a poem."),
        ],
    )

    # Act
    processed = await mw.process(req)

    # Assert
    # All messages should remain (RedactionMiddleware does not remove proxy responses)
    assert len(processed.messages) == 4
    assert processed.messages[0].content == "Some previous message"
    assert processed.messages[1].content == "!/backend(test)"
    assert processed.messages[2].content == "Proxy command executed."
    assert processed.messages[3].content == "Now, please write a poem."


@pytest.mark.asyncio
async def test_redaction_middleware_does_not_filter_commands() -> None:
    """Regression: Verify that commands are NOT filtered by RedactionMiddleware.

    Command filtering is now handled by the non-forwardable message tagging system.
    """
    mw = RedactionMiddleware(api_keys=[])

    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="!/backend(test)"),
            ChatMessage(role="user", content="#/model(gpt-4)"),
            ChatMessage(role="user", content="Follow-up task"),
        ],
    )

    processed = await mw.process(req)

    # All messages should remain with commands intact
    assert len(processed.messages) == 3
    assert processed.messages[0].content == "!/backend(test)"
    assert processed.messages[1].content == "#/model(gpt-4)"
    assert processed.messages[2].content == "Follow-up task"


# =============================================================================
# Caching behavior tests
# =============================================================================


@pytest.mark.asyncio
async def test_redaction_middleware_caches_processed_messages() -> None:
    """Verify that processed messages are cached to avoid reprocessing."""
    api_keys = ["sk-TESTSECRET12345"]
    mw = RedactionMiddleware(api_keys=api_keys)
    session_id = "test-session-cache"

    # First request with 2 messages
    req1 = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="First message"),
            ChatMessage(role="assistant", content="Response 1"),
        ],
    )

    await mw.process(req1, context={"session_id": session_id})

    # Check cache stats
    cache = get_global_redaction_cache()
    stats = cache.get_stats(session_id)
    assert stats.cached_hashes == 2
    assert stats.total_processed == 2


@pytest.mark.asyncio
async def test_redaction_middleware_skips_cached_messages() -> None:
    """Verify that already-cached messages are skipped on subsequent requests."""
    api_keys = ["sk-TESTSECRET12345"]
    mw = RedactionMiddleware(api_keys=api_keys)
    session_id = "test-session-skip"

    # First request with 2 messages
    req1 = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="First message"),
            ChatMessage(role="assistant", content="Response 1"),
        ],
    )
    await mw.process(req1, context={"session_id": session_id})

    # Second request with 3 messages (same 2 + 1 new)
    req2 = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="First message"),
            ChatMessage(role="assistant", content="Response 1"),
            ChatMessage(role="user", content="New message"),
        ],
    )
    await mw.process(req2, context={"session_id": session_id})

    # Cache should now have 3 hashes (2 original + 1 new)
    cache = get_global_redaction_cache()
    stats = cache.get_stats(session_id)
    assert stats.cached_hashes == 3
    # Total processed should be 3 (not 5) because first 2 were skipped
    assert stats.total_processed == 3


@pytest.mark.asyncio
async def test_redaction_middleware_without_session_id() -> None:
    """Verify that middleware works without session_id (no caching)."""
    api_keys = ["sk-TESTSECRET12345"]
    mw = RedactionMiddleware(api_keys=api_keys)

    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content=f"Use {api_keys[0]} for this"),
        ],
    )

    # Process without session_id
    processed = await mw.process(req, context=None)

    # Should still work and redact
    assert "(API_KEY_HAS_BEEN_REDACTED)" in str(processed.messages[0].content)


@pytest.mark.asyncio
async def test_redaction_middleware_different_sessions_isolated() -> None:
    """Verify that different sessions have isolated caches."""
    api_keys = ["sk-TESTSECRET12345"]
    mw = RedactionMiddleware(api_keys=api_keys)

    req = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="Same message"),
        ],
    )

    # Process for session 1
    await mw.process(req, context={"session_id": "session-1"})

    # Process for session 2
    await mw.process(req, context={"session_id": "session-2"})

    # Each session should have its own cache
    cache = get_global_redaction_cache()
    assert cache.get_stats("session-1").cached_hashes == 1
    assert cache.get_stats("session-2").cached_hashes == 1


@pytest.mark.asyncio
async def test_redaction_still_applies_to_new_messages_with_api_keys() -> None:
    """Verify that new messages containing API keys are still properly redacted."""
    api_keys = ["sk-TESTSECRET12345"]
    mw = RedactionMiddleware(api_keys=api_keys)
    session_id = "test-session-redact-new"

    # First request - establishes cache
    req1 = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="First message"),
        ],
    )
    await mw.process(req1, context={"session_id": session_id})

    # Second request - has a new message with API key
    req2 = ChatRequest(
        model="gpt-4o",
        messages=[
            ChatMessage(role="user", content="First message"),
            ChatMessage(role="user", content=f"Use {api_keys[0]} here"),
        ],
    )
    processed = await mw.process(req2, context={"session_id": session_id})

    # The new message should be redacted
    new_msg_content = processed.messages[1].content
    assert "(API_KEY_HAS_BEEN_REDACTED)" in str(new_msg_content)
    assert api_keys[0] not in str(new_msg_content)
