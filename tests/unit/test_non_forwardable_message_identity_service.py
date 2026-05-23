"""
Unit tests for NonForwardableMessageIdentityService.

Tests coverage for:
- Deterministic identity computation
- Metadata exclusion
- Tool result stability across content rewrites
- Content normalization (line endings)
- Edge cases

Requirements: 1.2, 1.9, 1.10, 1.12, 1.13, 5.2, 9.1
"""

from __future__ import annotations

import contextvars

from src.core.domain.chat import (
    ChatMessage,
    FunctionCall,
    ImageURL,
    MessageContentPartImage,
    MessageContentPartText,
    ToolCall,
)
from src.core.interfaces.non_forwardable_interface import (
    INonForwardableMessageIdentityService,
)
from src.core.services.non_forwardable_message_identity_service import (
    NonForwardableMessageIdentityService,
    _identity_cache,
)


class TestNonForwardableMessageIdentityService:
    """Tests for NonForwardableMessageIdentityService implementation."""

    def test_service_implements_interface(self) -> None:
        """Service implements INonForwardableMessageIdentityService."""
        service = NonForwardableMessageIdentityService()
        assert isinstance(service, INonForwardableMessageIdentityService)

    def test_compute_identity_returns_string(self) -> None:
        """compute_identity returns a string (MessageIdentity)."""
        service = NonForwardableMessageIdentityService()
        message = ChatMessage(role="user", content="Hello")
        identity = service.compute_identity(message)
        assert isinstance(identity, str)
        assert len(identity) == 64  # SHA-256 hex is 64 chars

    def test_determinism_same_message(self) -> None:
        """Same message produces same identity across multiple calls."""
        service = NonForwardableMessageIdentityService()
        message = ChatMessage(role="user", content="Hello")
        identity1 = service.compute_identity(message)
        identity2 = service.compute_identity(message)
        assert identity1 == identity2

    def test_determinism_equivalent_messages(self) -> None:
        """Equivalent messages produce same identity."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="user", content="Hello")
        assert service.compute_identity(msg1) == service.compute_identity(msg2)

    def test_different_messages_different_identities(self) -> None:
        """Different messages produce different identities."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="user", content="World")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_metadata_excluded_from_identity(self) -> None:
        """Messages with different metadata produce same identity."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello", metadata={"key": "value1"})
        msg2 = ChatMessage(role="user", content="Hello", metadata={"key": "value2"})
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 == identity2

    def test_metadata_none_vs_present(self) -> None:
        """Message with metadata=None produces same identity as without metadata."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello", metadata=None)
        msg2 = ChatMessage(role="user", content="Hello")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 == identity2

    def test_tool_result_identity_stable_across_content_rewrite(self) -> None:
        """Tool result identity unchanged when content is rewritten."""
        service = NonForwardableMessageIdentityService()
        # Same tool_call_id, different content (simulating truncation/rewrite)
        msg1 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            content="Original tool output with detailed results",
        )
        msg2 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            content="[Tool output truncated]",
        )
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 == identity2
        ), "Tool result identity must be stable across content rewrites"

    def test_tool_result_identity_includes_tool_call_id(self) -> None:
        """Tool result identity changes when tool_call_id changes."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            content="Same content",
        )
        msg2 = ChatMessage(
            role="tool",
            tool_call_id="call_456",
            content="Same content",
        )
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_result_identity_includes_name(self) -> None:
        """Tool result identity includes name when present."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            name="function_a",
            content="Same content",
        )
        msg2 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            name="function_b",
            content="Same content",
        )
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_result_identity_name_none_vs_present(self) -> None:
        """Tool result identity changes when name is added."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            name=None,
            content="Same content",
        )
        msg2 = ChatMessage(
            role="tool",
            tool_call_id="call_123",
            name="function_a",
            content="Same content",
        )
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_line_ending_normalization_crlf(self) -> None:
        """Line endings CRLF normalized to LF."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Line1\r\nLine2")
        msg2 = ChatMessage(role="user", content="Line1\nLine2")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 == identity2

    def test_line_ending_normalization_cr(self) -> None:
        """Line endings CR normalized to LF."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Line1\rLine2")
        msg2 = ChatMessage(role="user", content="Line1\nLine2")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 == identity2

    def test_whitespace_preserved(self) -> None:
        """Whitespace is preserved (not trimmed)."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="  Hello  ")
        msg2 = ChatMessage(role="user", content="Hello")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2, "Whitespace must be preserved"

    def test_multimodal_content_parts_order_preserved(self) -> None:
        """Multimodal content parts order is preserved."""
        service = NonForwardableMessageIdentityService()
        part1 = MessageContentPartText(type="text", text="First")
        part2 = MessageContentPartText(type="text", text="Second")
        msg1 = ChatMessage(role="user", content=[part1, part2])
        msg2 = ChatMessage(role="user", content=[part2, part1])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2, "Content parts order must be preserved"

    def test_role_included_in_identity(self) -> None:
        """Role is included in identity computation."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="assistant", content="Hello")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_content_included_in_identity(self) -> None:
        """Content is included in identity computation."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="user", content="World")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_reasoning_content_included_in_identity(self) -> None:
        """Reasoning content is included in identity computation."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(
            role="assistant", content="Hello", reasoning_content="Reason1"
        )
        msg2 = ChatMessage(
            role="assistant", content="Hello", reasoning_content="Reason2"
        )
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_name_included_in_identity(self) -> None:
        """Name is included in identity computation."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello", name="Alice")
        msg2 = ChatMessage(role="user", content="Hello", name="Bob")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_calls_included_in_identity(self) -> None:
        """Tool calls are included in identity computation."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        tool_call2 = ToolCall(
            id="call_2",
            type="function",
            function=FunctionCall(name="func2", arguments='{"arg": "value"}'),
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_call_id_included_in_identity(self) -> None:
        """Tool call ID is included in identity computation."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello", tool_call_id="call_123")
        msg2 = ChatMessage(role="user", content="Hello", tool_call_id="call_456")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_edge_case_content_none(self) -> None:
        """Message with content=None produces valid identity."""
        service = NonForwardableMessageIdentityService()
        msg = ChatMessage(role="system", content=None)
        identity = service.compute_identity(msg)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_edge_case_empty_string(self) -> None:
        """Message with empty string content produces valid identity."""
        service = NonForwardableMessageIdentityService()
        msg = ChatMessage(role="user", content="")
        identity = service.compute_identity(msg)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_edge_case_only_role(self) -> None:
        """Message with only role set produces valid identity."""
        service = NonForwardableMessageIdentityService()
        msg = ChatMessage(role="user")
        identity = service.compute_identity(msg)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_edge_case_tool_calls_no_tool_call_id(self) -> None:
        """Message with tool_calls but no tool_call_id produces valid identity."""
        service = NonForwardableMessageIdentityService()
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        msg = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call])
        identity = service.compute_identity(msg)
        assert isinstance(identity, str)
        assert len(identity) == 64

    def test_tool_result_role_tool_without_tool_call_id(self) -> None:
        """Message with role='tool' but no tool_call_id is treated as regular message."""
        service = NonForwardableMessageIdentityService()
        # This should include content in identity (not treated as tool result)
        msg1 = ChatMessage(role="tool", content="Content1")
        msg2 = ChatMessage(role="tool", content="Content2")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_result_role_tool_with_tool_call_id(self) -> None:
        """Message with role='tool' and tool_call_id excludes content from identity."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="tool", tool_call_id="call_123", content="Content1")
        msg2 = ChatMessage(role="tool", tool_call_id="call_123", content="Content2")
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 == identity2
        ), "Tool result with same tool_call_id must have same identity regardless of content"

    def test_identity_is_lowercase_hex(self) -> None:
        """Identity is lowercase hexadecimal string."""
        service = NonForwardableMessageIdentityService()
        msg = ChatMessage(role="user", content="Hello")
        identity = service.compute_identity(msg)
        assert identity.islower()
        assert all(c in "0123456789abcdef" for c in identity)

    def test_tool_call_function_arguments_included(self) -> None:
        """Tool call function arguments are included in identity."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value1"}'),
        )
        tool_call2 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value2"}'),
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_call_id_field_included(self) -> None:
        """Tool call id field is included in identity."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        tool_call2 = ToolCall(
            id="call_2",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_call_type_included(self) -> None:
        """Tool call type field is included in identity."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        tool_call2 = ToolCall(
            id="call_1",
            type="other",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2

    def test_tool_call_extra_content_included(self) -> None:
        """Tool call provider-specific extra fields (extra_content) are included in identity."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
            extra_content={"thought_signature": "sig1"},
        )
        tool_call2 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
            extra_content={"thought_signature": "sig2"},
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 != identity2
        ), "Provider-specific extra fields must be included in identity"

    def test_tool_call_extra_content_none_vs_present(self) -> None:
        """Tool call identity changes when extra_content is added."""
        service = NonForwardableMessageIdentityService()
        tool_call1 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
            extra_content=None,
        )
        tool_call2 = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="func1", arguments='{"arg": "value"}'),
            extra_content={"key": "value"},
        )
        msg1 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call1])
        msg2 = ChatMessage(role="assistant", content="Hello", tool_calls=[tool_call2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert identity1 != identity2, "extra_content must affect identity when present"

    def test_request_local_cache_same_message(self) -> None:
        """Request-local cache returns cached identity for same message."""
        service = NonForwardableMessageIdentityService()
        message = ChatMessage(role="user", content="Hello")

        # First call - should compute and cache
        identity1 = service.compute_identity(message)

        # Second call with same message - should return cached value
        identity2 = service.compute_identity(message)

        assert identity1 == identity2

        # Verify cache was used (check cache is populated)
        cache = _identity_cache.get({})
        assert len(cache) > 0, "Cache should contain at least one entry"

    def test_request_local_cache_equivalent_messages(self) -> None:
        """Request-local cache returns cached identity for equivalent messages."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(
            role="user", content="Hello"
        )  # Equivalent but different object

        # First call - should compute and cache
        identity1 = service.compute_identity(msg1)

        # Second call with equivalent message - should return cached value
        identity2 = service.compute_identity(msg2)

        assert identity1 == identity2

    def test_request_local_cache_different_messages(self) -> None:
        """Request-local cache stores different identities for different messages."""
        service = NonForwardableMessageIdentityService()
        msg1 = ChatMessage(role="user", content="Hello")
        msg2 = ChatMessage(role="user", content="World")

        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)

        assert identity1 != identity2

        # Verify both are cached
        cache = _identity_cache.get({})
        assert len(cache) >= 2, "Cache should contain entries for both messages"

    def test_request_local_cache_isolation(self) -> None:
        """Request-local cache is isolated between different async contexts."""
        service = NonForwardableMessageIdentityService()
        message = ChatMessage(role="user", content="Hello")

        # Clear any existing cache first
        _identity_cache.set({})

        # Compute identity in first context
        ctx1 = contextvars.copy_context()
        # Reset cache in context 1
        ctx1.run(_identity_cache.set, {})
        identity1 = ctx1.run(service.compute_identity, message)

        # Compute identity in second context (should be isolated)
        ctx2 = contextvars.copy_context()
        # Reset cache in context 2
        ctx2.run(_identity_cache.set, {})
        identity2 = ctx2.run(service.compute_identity, message)

        # Identities should be the same (deterministic)
        assert identity1 == identity2

        # But caches should be isolated (each context has its own cache)
        cache1 = ctx1.run(_identity_cache.get, {})
        cache2 = ctx2.run(_identity_cache.get, {})

        # Each context should have its own cache entry
        assert (
            len(cache1) == 1
        ), f"Context 1 cache should have one entry, got {len(cache1)}: {cache1}"
        assert (
            len(cache2) == 1
        ), f"Context 2 cache should have one entry, got {len(cache2)}: {cache2}"

        # Cache keys should be the same (same message)
        assert list(cache1.keys()) == list(cache2.keys())

        # But they are separate cache instances
        assert cache1 is not cache2, "Caches should be separate instances"

    def test_cache_control_excluded_from_identity(self) -> None:
        """Transport-specific cache_control field is excluded from identity computation."""
        service = NonForwardableMessageIdentityService()
        # Create messages with different cache_control values
        part1 = MessageContentPartText(type="text", text="Hello")
        part1.cache_control = {"key": "value1"}  # type: ignore[assignment]
        part2 = MessageContentPartText(type="text", text="Hello")
        part2.cache_control = {"key": "value2"}  # type: ignore[assignment]
        msg1 = ChatMessage(role="user", content=[part1])
        msg2 = ChatMessage(role="user", content=[part2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 == identity2
        ), "cache_control is transport-specific and must not affect identity"

    def test_image_content_part_included_in_identity(self) -> None:
        """Image content parts are included in identity computation."""
        service = NonForwardableMessageIdentityService()
        img1 = MessageContentPartImage(
            type="image_url",
            image_url=ImageURL(url="data:image/png;base64,abc", detail="auto"),
        )
        img2 = MessageContentPartImage(
            type="image_url",
            image_url=ImageURL(url="data:image/png;base64,xyz", detail="auto"),
        )
        msg1 = ChatMessage(role="user", content=[img1])
        msg2 = ChatMessage(role="user", content=[img2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 != identity2
        ), "Different image URLs must produce different identities"

    def test_image_content_part_cache_control_excluded(self) -> None:
        """Image content part cache_control is excluded from identity."""
        service = NonForwardableMessageIdentityService()
        img1 = MessageContentPartImage(
            type="image_url",
            image_url=ImageURL(url="data:image/png;base64,test", detail="auto"),
        )
        img1.cache_control = {"key": "value1"}  # type: ignore[assignment]
        img2 = MessageContentPartImage(
            type="image_url",
            image_url=ImageURL(url="data:image/png;base64,test", detail="auto"),
        )
        img2.cache_control = {"key": "value2"}  # type: ignore[assignment]
        msg1 = ChatMessage(role="user", content=[img1])
        msg2 = ChatMessage(role="user", content=[img2])
        identity1 = service.compute_identity(msg1)
        identity2 = service.compute_identity(msg2)
        assert (
            identity1 == identity2
        ), "cache_control is transport-specific and must not affect identity"
