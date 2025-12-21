"""
Tests for session sanitization when switching backends mid-session.
"""

from src.connectors.gemini_base.backend_compatibility import (
    are_backends_compatible,
    requires_signature_cleanup,
    uses_thought_signatures,
)
from src.connectors.gemini_base.thought_signature_manager import ThoughtSignatureManager
from src.connectors.gemini_base.thought_signature_service import ThoughtSignatureService
from src.core.domain.chat import ChatMessage, FunctionCall, ToolCall
from src.core.services.session_sanitizer import SessionSanitizer


class TestBackendCompatibility:
    """Tests for backend compatibility detection."""

    def test_same_backend_is_compatible(self) -> None:
        """Same backend should always be compatible."""
        assert are_backends_compatible("gemini-oauth-plan", "gemini-oauth-plan")
        assert are_backends_compatible("antigravity-oauth", "antigravity-oauth")
        assert are_backends_compatible("openai", "openai")

    def test_none_backend_is_compatible(self) -> None:
        """None backends should be compatible (first request or unknown)."""
        assert are_backends_compatible(None, "gemini-oauth-plan")
        assert are_backends_compatible("gemini-oauth-plan", None)
        assert are_backends_compatible(None, None)

    def test_same_group_is_compatible(self) -> None:
        """Backends in the same infrastructure group should be compatible."""
        # Personal OAuth group
        assert are_backends_compatible("gemini-oauth-free", "gemini-oauth-plan")
        assert are_backends_compatible("gemini-oauth-plan", "gemini-oauth-free")

    def test_different_groups_not_compatible(self) -> None:
        """Backends in different groups should NOT be compatible."""
        assert not are_backends_compatible("gemini-oauth-plan", "antigravity-oauth")
        assert not are_backends_compatible("antigravity-oauth", "gemini-oauth-plan")

    def test_non_gemini_backend_is_compatible(self) -> None:
        """Non-Gemini backends don't use signatures, so always compatible."""
        assert are_backends_compatible("openai", "gemini-oauth-plan")
        assert are_backends_compatible("gemini-oauth-plan", "openai")
        assert are_backends_compatible("anthropic", "openai")

    def test_requires_signature_cleanup_same_backend(self) -> None:
        """Same backend never requires cleanup."""
        assert not requires_signature_cleanup("gemini-oauth-plan", "gemini-oauth-plan")

    def test_requires_signature_cleanup_different_groups(self) -> None:
        """Different Gemini groups require cleanup."""
        assert requires_signature_cleanup("gemini-oauth-plan", "antigravity-oauth")
        assert requires_signature_cleanup("antigravity-oauth", "gemini-oauth-free")

    def test_requires_signature_cleanup_non_gemini(self) -> None:
        """Non-Gemini backends never require cleanup."""
        assert not requires_signature_cleanup("openai", "gemini-oauth-plan")
        assert not requires_signature_cleanup("gemini-oauth-plan", "openai")

    def test_uses_thought_signatures(self) -> None:
        """Test thought signature detection for backends."""
        assert uses_thought_signatures("gemini-oauth-plan")
        assert uses_thought_signatures("gemini-oauth-free")
        assert uses_thought_signatures("antigravity-oauth")
        assert not uses_thought_signatures("openai")
        assert not uses_thought_signatures(None)


class TestThoughtSignatureManagerClear:
    """Tests for ThoughtSignatureManager.clear_session_cache."""

    def test_clear_session_cache_removes_entries(self) -> None:
        """Cache entries should be removed for the specified session."""
        manager = ThoughtSignatureManager()
        session_id = "test_session_123"

        # Store some signatures
        manager._cache[f"{session_id}:call_1"] = "sig_1"
        manager._cache[f"{session_id}:call_2"] = "sig_2"
        manager._by_tool_call["call_1"] = "sig_1"
        manager._by_tool_call["call_2"] = "sig_2"

        # Store for different session
        manager._cache["other_session:call_3"] = "sig_3"
        manager._by_tool_call["call_3"] = "sig_3"

        # Clear the test session
        cleared = manager.clear_session_cache(session_id)

        assert cleared == 2
        assert f"{session_id}:call_1" not in manager._cache
        assert f"{session_id}:call_2" not in manager._cache
        assert "call_1" not in manager._by_tool_call
        assert "call_2" not in manager._by_tool_call
        # Other session should be intact
        assert "other_session:call_3" in manager._cache
        assert "call_3" in manager._by_tool_call

    def test_clear_session_cache_empty_session_id(self) -> None:
        """Empty session ID should return 0."""
        manager = ThoughtSignatureManager()
        assert manager.clear_session_cache("") == 0

    def test_clear_session_cache_no_matching_entries(self) -> None:
        """No matching entries should return 0."""
        manager = ThoughtSignatureManager()
        manager._cache["other:call_1"] = "sig_1"
        assert manager.clear_session_cache("nonexistent") == 0


class TestSessionSanitizer:
    """Tests for SessionSanitizer."""

    def test_should_sanitize_incompatible_backends(self) -> None:
        """Sanitization should be required for incompatible backends."""
        sanitizer = SessionSanitizer()
        assert sanitizer.should_sanitize("gemini-oauth-plan", "antigravity-oauth")

    def test_should_not_sanitize_compatible_backends(self) -> None:
        """Sanitization should NOT be required for compatible backends."""
        sanitizer = SessionSanitizer()
        assert not sanitizer.should_sanitize("gemini-oauth-free", "gemini-oauth-plan")
        assert not sanitizer.should_sanitize("openai", "anthropic")

    def test_sanitize_messages_strips_thought_signatures(self) -> None:
        """Thought signatures should be stripped from tool calls."""
        sanitizer = SessionSanitizer()

        # Create message with thought signature
        tool_call = ToolCall(
            id="call_123",
            type="function",
            function=FunctionCall(name="test_tool", arguments="{}"),
            extra_content={"google": {"thought_signature": "secret_sig"}},
        )
        message = ChatMessage(role="assistant", tool_calls=[tool_call])

        # Sanitize
        sanitized = sanitizer.sanitize_messages([message])

        # Verify signature removed
        assert len(sanitized) == 1
        sanitized_tc = sanitized[0].tool_calls[0]
        assert (
            sanitized_tc.extra_content is None
            or "google" not in sanitized_tc.extra_content
        )

    def test_sanitize_messages_preserves_content(self) -> None:
        """Message content should be preserved after sanitization."""
        sanitizer = SessionSanitizer()

        # Create various messages
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there"),
            ChatMessage(role="user", content="Do something"),
        ]

        # Sanitize
        sanitized = sanitizer.sanitize_messages(messages)

        # Verify content preserved
        assert len(sanitized) == 3
        assert sanitized[0].content == "Hello"
        assert sanitized[1].content == "Hi there"
        assert sanitized[2].content == "Do something"

    def test_sanitize_messages_preserves_tool_call_function(self) -> None:
        """Tool call function info should be preserved after sanitization."""
        sanitizer = SessionSanitizer()

        tool_call = ToolCall(
            id="call_abc",
            type="function",
            function=FunctionCall(name="my_func", arguments='{"arg": "value"}'),
            extra_content={"google": {"thought_signature": "sig123"}},
        )
        message = ChatMessage(role="assistant", tool_calls=[tool_call])

        sanitized = sanitizer.sanitize_messages([message])

        sanitized_tc = sanitized[0].tool_calls[0]
        assert sanitized_tc.id == "call_abc"
        assert sanitized_tc.function.name == "my_func"
        assert sanitized_tc.function.arguments == '{"arg": "value"}'

    def test_sanitize_session_full_workflow(self) -> None:
        """Test the complete sanitize_session workflow."""
        # Use a fresh manager/service for isolation
        manager = ThoughtSignatureManager()
        service = ThoughtSignatureService(manager=manager)
        sanitizer = SessionSanitizer(thought_signature_service=service)

        session_id = "session_abc"

        # Pre-populate signature cache
        manager._cache[f"{session_id}:call_1"] = "sig_1"
        manager._by_tool_call["call_1"] = "sig_1"

        # Create messages with signature
        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="test", arguments="{}"),
            extra_content={"google": {"thought_signature": "sig_1"}},
        )
        messages = [
            ChatMessage(role="user", content="test"),
            ChatMessage(role="assistant", tool_calls=[tool_call]),
        ]

        # Sanitize for backend switch
        sanitized_messages, was_sanitized = sanitizer.sanitize_session(
            messages=messages,
            session_id=session_id,
            previous_backend="gemini-oauth-plan",
            new_backend="antigravity-oauth",
        )

        assert was_sanitized is True
        assert len(sanitized_messages) == 2
        # Cache should be cleared
        assert f"{session_id}:call_1" not in manager._cache
        # Signature should be stripped from message
        sanitized_tc = sanitized_messages[1].tool_calls[0]
        assert (
            sanitized_tc.extra_content is None
            or "google" not in sanitized_tc.extra_content
        )

    def test_sanitize_session_no_op_for_compatible(self) -> None:
        """Sanitization should be a no-op for compatible backends."""
        sanitizer = SessionSanitizer()

        tool_call = ToolCall(
            id="call_1",
            type="function",
            function=FunctionCall(name="test", arguments="{}"),
            extra_content={"google": {"thought_signature": "sig_1"}},
        )
        messages = [ChatMessage(role="assistant", tool_calls=[tool_call])]

        sanitized_messages, was_sanitized = sanitizer.sanitize_session(
            messages=messages,
            session_id="session_123",
            previous_backend="gemini-oauth-free",
            new_backend="gemini-oauth-plan",
        )

        assert was_sanitized is False
        # Original message should be returned (signature intact)
        assert sanitized_messages[0].tool_calls[0].extra_content is not None


class TestMultiSwitchScenarios:
    """Tests for complex multi-backend switch scenarios."""

    def test_no_signatures_to_signatures_required(self) -> None:
        """Scenario: OpenAI -> Gemini (no cleanup needed, fresh start)."""
        sanitizer = SessionSanitizer()

        # Messages from OpenAI backend (no thought signatures)
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        function=FunctionCall(name="test", arguments="{}"),
                        extra_content=None,  # No signature
                    )
                ],
            ),
        ]

        sanitized, was_sanitized = sanitizer.sanitize_session(
            messages=messages,
            session_id="session_1",
            previous_backend="openai",
            new_backend="gemini-oauth-plan",
        )

        # No sanitization needed (compatible)
        assert was_sanitized is False
        assert len(sanitized) == 2

    def test_no_signatures_to_signatures_to_no_signatures(self) -> None:
        """Scenario: OpenAI -> Gemini -> OpenAI (signature cleanup not needed on return)."""
        manager = ThoughtSignatureManager()
        service = ThoughtSignatureService(manager=manager)
        sanitizer = SessionSanitizer(thought_signature_service=service)
        session_id = "session_2"

        # Step 1: OpenAI -> Gemini (no cleanup)
        messages_step1 = [ChatMessage(role="user", content="test")]
        _, was_sanitized1 = sanitizer.sanitize_session(
            messages=messages_step1,
            session_id=session_id,
            previous_backend="openai",
            new_backend="gemini-oauth-plan",
        )
        assert was_sanitized1 is False

        # Step 2: Gemini accumulated some signatures
        manager._cache[f"{session_id}:call_gemini"] = "gemini_sig"
        manager._by_tool_call["call_gemini"] = "gemini_sig"

        # Step 3: Gemini -> OpenAI (signatures don't matter for non-Gemini)
        messages_with_sig = [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_gemini",
                        type="function",
                        function=FunctionCall(name="test", arguments="{}"),
                        extra_content={"google": {"thought_signature": "gemini_sig"}},
                    )
                ],
            ),
        ]
        _, was_sanitized2 = sanitizer.sanitize_session(
            messages=messages_with_sig,
            session_id=session_id,
            previous_backend="gemini-oauth-plan",
            new_backend="openai",
        )
        # No cleanup needed - OpenAI doesn't care about signatures
        assert was_sanitized2 is False

    def test_signatures_a_to_signatures_b_different_backends(self) -> None:
        """Scenario: Gemini Plan -> Antigravity OAuth (must clear signatures)."""
        manager = ThoughtSignatureManager()
        service = ThoughtSignatureService(manager=manager)
        sanitizer = SessionSanitizer(thought_signature_service=service)
        session_id = "session_3"

        # Gemini Plan accumulated signatures
        manager._cache[f"{session_id}:call_plan_1"] = "plan_sig_1"
        manager._cache[f"{session_id}:call_plan_2"] = "plan_sig_2"
        manager._by_tool_call["call_plan_1"] = "plan_sig_1"
        manager._by_tool_call["call_plan_2"] = "plan_sig_2"

        messages = [
            ChatMessage(role="user", content="test"),
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_plan_1",
                        type="function",
                        function=FunctionCall(name="tool1", arguments="{}"),
                        extra_content={"google": {"thought_signature": "plan_sig_1"}},
                    ),
                    ToolCall(
                        id="call_plan_2",
                        type="function",
                        function=FunctionCall(name="tool2", arguments="{}"),
                        extra_content={"google": {"thought_signature": "plan_sig_2"}},
                    ),
                ],
            ),
        ]

        sanitized, was_sanitized = sanitizer.sanitize_session(
            messages=messages,
            session_id=session_id,
            previous_backend="gemini-oauth-plan",
            new_backend="antigravity-oauth",
        )

        assert was_sanitized is True
        # Cache should be cleared
        assert f"{session_id}:call_plan_1" not in manager._cache
        assert f"{session_id}:call_plan_2" not in manager._cache
        assert "call_plan_1" not in manager._by_tool_call
        assert "call_plan_2" not in manager._by_tool_call
        # Signatures stripped from messages
        for tc in sanitized[1].tool_calls:
            assert tc.extra_content is None or "google" not in tc.extra_content

    def test_signatures_a_to_b_back_to_a(self) -> None:
        """Scenario: Plan -> Antigravity -> Plan (must clear B's sigs when returning to A)."""
        manager = ThoughtSignatureManager()
        service = ThoughtSignatureService(manager=manager)
        sanitizer = SessionSanitizer(thought_signature_service=service)
        session_id = "session_4"

        # Step 1: Start with Plan, accumulate signatures
        manager._cache[f"{session_id}:call_plan_orig"] = "plan_sig_orig"
        manager._by_tool_call["call_plan_orig"] = "plan_sig_orig"

        messages_step1 = [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_plan_orig",
                        type="function",
                        function=FunctionCall(name="tool", arguments="{}"),
                        extra_content={
                            "google": {"thought_signature": "plan_sig_orig"}
                        },
                    )
                ],
            ),
        ]

        # Step 2: Switch to Antigravity (clears Plan signatures)
        sanitized_step2, was_sanitized2 = sanitizer.sanitize_session(
            messages=messages_step1,
            session_id=session_id,
            previous_backend="gemini-oauth-plan",
            new_backend="antigravity-oauth",
        )
        assert was_sanitized2 is True
        assert f"{session_id}:call_plan_orig" not in manager._cache

        # Step 3: Antigravity accumulates its own signatures
        manager._cache[f"{session_id}:call_anti_1"] = "anti_sig_1"
        manager._by_tool_call["call_anti_1"] = "anti_sig_1"

        # Include both old sanitized messages AND new Antigravity messages
        messages_step3 = [
            *sanitized_step2,
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_anti_1",
                        type="function",
                        function=FunctionCall(name="anti_tool", arguments="{}"),
                        extra_content={"google": {"thought_signature": "anti_sig_1"}},
                    )
                ],
            ),
        ]

        # Step 4: Switch BACK to Plan (must clear Antigravity signatures)
        sanitized_step4, was_sanitized4 = sanitizer.sanitize_session(
            messages=messages_step3,
            session_id=session_id,
            previous_backend="antigravity-oauth",
            new_backend="gemini-oauth-plan",
        )

        assert was_sanitized4 is True
        # Antigravity signatures should be cleared
        assert f"{session_id}:call_anti_1" not in manager._cache
        assert "call_anti_1" not in manager._by_tool_call
        # All signatures should be stripped from messages
        for msg in sanitized_step4:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    assert tc.extra_content is None or "google" not in tc.extra_content

    def test_same_model_different_backends(self) -> None:
        """Scenario: gemini-2.5-pro on Plan -> gemini-2.5-pro on Antigravity OAuth."""
        manager = ThoughtSignatureManager()
        service = ThoughtSignatureService(manager=manager)
        sanitizer = SessionSanitizer(thought_signature_service=service)
        session_id = "session_5"

        # Same model, different backends - signatures are still incompatible
        manager._cache[f"{session_id}:call_1"] = "plan_sig"
        manager._by_tool_call["call_1"] = "plan_sig"

        messages = [
            ChatMessage(
                role="assistant",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        type="function",
                        function=FunctionCall(name="tool", arguments="{}"),
                        extra_content={"google": {"thought_signature": "plan_sig"}},
                    )
                ],
            ),
        ]

        sanitized, was_sanitized = sanitizer.sanitize_session(
            messages=messages,
            session_id=session_id,
            previous_backend="gemini-oauth-plan",  # Different backend
            new_backend="antigravity-oauth",  # Same model could be used
        )

        # Even with same model, different backends = incompatible
        assert was_sanitized is True
        assert f"{session_id}:call_1" not in manager._cache
