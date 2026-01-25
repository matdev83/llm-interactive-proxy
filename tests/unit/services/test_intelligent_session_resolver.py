"""Unit tests for IntelligentSessionResolver."""

from __future__ import annotations

import pytest
from src.core.config.app_config import AppConfig
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.session import Session
from src.core.repositories.in_memory_session_repository import (
    InMemorySessionRepository,
)
from src.core.services.conversation_fingerprint_service import (
    ConversationFingerprintService,
)
from src.core.services.intelligent_session_resolver import IntelligentSessionResolver


class TestIntelligentSessionResolver:
    """Tests for intelligent session resolution."""

    @pytest.fixture
    def config(self) -> AppConfig:
        """Create minimal app config."""
        return AppConfig()

    @pytest.fixture
    def session_repository(self) -> InMemorySessionRepository:
        """Create in-memory session repository."""
        return InMemorySessionRepository()

    @pytest.fixture
    def fingerprint_service(self) -> ConversationFingerprintService:
        """Create fingerprint service."""
        return ConversationFingerprintService()

    @pytest.fixture
    def resolver(
        self,
        config: AppConfig,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
    ) -> IntelligentSessionResolver:
        """Create intelligent session resolver."""
        return IntelligentSessionResolver(
            config=config,
            session_repository=session_repository,
            fingerprint_service=fingerprint_service,
        )

    def create_context(
        self,
        config: AppConfig,
        headers: dict[str, str] | None = None,
        client_host: str = "127.0.0.1",
        domain_request: ChatRequest | None = None,
    ) -> RequestContext:
        """Helper to create RequestContext."""
        context = RequestContext(
            headers=headers or {},
            cookies={},
            state=None,
            app_state=None,
            client_host=client_host,
        )
        if domain_request:
            context.domain_request = domain_request  # type: ignore
        return context

    @pytest.mark.asyncio
    async def test_resolve_with_explicit_session_id(
        self,
        resolver: IntelligentSessionResolver,
        config: AppConfig,
    ) -> None:
        """Test that explicit x-session-id header is respected."""
        context = self.create_context(
            config, headers={"x-session-id": "explicit-session-123"}
        )

        session_id = await resolver.resolve_session_id(context)

        assert session_id == "explicit-session-123"

    @pytest.mark.asyncio
    async def test_resolve_new_session_no_messages(
        self,
        resolver: IntelligentSessionResolver,
        config: AppConfig,
    ) -> None:
        """Test that new session is created when no messages provided."""
        context = self.create_context(config)

        session_id = await resolver.resolve_session_id(context)

        # Should create new session
        assert session_id is not None
        assert len(session_id) > 0

    @pytest.mark.asyncio
    async def test_resolve_new_session_single_message(
        self,
        resolver: IntelligentSessionResolver,
        config: AppConfig,
    ) -> None:
        """Test that new session is created for single message (first turn)."""
        messages = [ChatMessage(role="user", content="Hello")]
        request = ChatRequest(model="test-model", messages=messages)

        context = self.create_context(config, domain_request=request)

        session_id = await resolver.resolve_session_id(context)

        # Should create new session (only 1 message = new conversation)
        assert session_id is not None
        assert len(session_id) > 0

    @pytest.mark.asyncio
    async def test_resolve_continuation_exact_match(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: AppConfig,
    ) -> None:
        """Test session continuation via exact fingerprint match."""
        # Create initial messages
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        # First request - should create new session
        request1 = ChatRequest(model="test-model", messages=messages)
        context1 = self.create_context(config, domain_request=request1)

        session_id1 = await resolver.resolve_session_id(context1)

        # Manually create and persist the session (simulating what session service would do)
        session = Session(session_id=session_id1)
        await session_repository.add(session)

        # Compute and store fingerprint (simulating what session manager would do)
        fp_bundle = fingerprint_service.compute_fingerprint_bundle(messages)
        await session_repository.update_fingerprint(
            session_id1, fp_bundle.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(session_id1, fp_bundle)

        # Second request with same messages from same client - should reuse session
        request2 = ChatRequest(model="test-model", messages=messages)
        context2 = self.create_context(config, domain_request=request2)

        session_id2 = await resolver.resolve_session_id(context2)

        # Should reuse same session
        assert session_id2 == session_id1

    @pytest.mark.asyncio
    async def test_resolve_continuation_fuzzy_match(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: AppConfig,
    ) -> None:
        """Test session continuation via fuzzy matching."""
        # Original conversation
        original_messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
            ChatMessage(role="user", content="How are you?"),
        ]

        # First request with original messages
        request1 = ChatRequest(model="test-model", messages=original_messages)
        context1 = self.create_context(config, domain_request=request1)

        session_id1 = await resolver.resolve_session_id(context1)

        # Persist session and fingerprint
        session = Session(session_id=session_id1)
        await session_repository.add(session)
        fp_original_bundle = fingerprint_service.compute_fingerprint_bundle(
            original_messages
        )
        await session_repository.update_fingerprint(
            session_id1, fp_original_bundle.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(
            session_id1, fp_original_bundle
        )

        # Extended conversation (continuation)
        extended_messages = [
            *original_messages,
            ChatMessage(role="assistant", content="I'm doing well!"),
            ChatMessage(role="user", content="That's great!"),
        ]

        # Second request with extended conversation - should fuzzy match original session
        request2 = ChatRequest(model="test-model", messages=extended_messages)
        context2 = self.create_context(config, domain_request=request2)

        session_id2 = await resolver.resolve_session_id(context2)

        # Should match via fuzzy matching (extended conversation contains original)
        assert session_id2 == session_id1

    @pytest.mark.asyncio
    async def test_resolve_continuation_after_condensed_history_with_explicit_id(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: AppConfig,
    ) -> None:
        """Condensed history should use explicit session ID for continuation.

        When clients condense/summarize history (e.g., Claude's context management),
        the message structure changes completely, removing all structural evidence
        for fuzzy matching. Clients must send explicit x-session-id header to
        continue the same session.

        This test was updated to fix a critical bug where topic similarity alone
        (without structural evidence) incorrectly merged separate agent sessions.
        """
        original_messages = [
            ChatMessage(
                role="user",
                content="Diagnose why the project root detection chooses the wrong directory.",
            ),
            ChatMessage(
                role="assistant",
                content="Reviewing the logs to understand the project directory detection behavior.",
            ),
            ChatMessage(
                role="user",
                content="Check logs/proxy.log for entries about deterministic detection.",
            ),
            ChatMessage(
                role="assistant",
                content="Logs show deterministic detection picks C:\\\\repo\\\\.venv\\\\Scripts as the project directory.",
            ),
            ChatMessage(
                role="user",
                content="We should exclude .venv directories so the resolver returns the repository root.",
            ),
            ChatMessage(
                role="assistant",
                content="Opening project_directory_resolution_service.py to inspect scoring rules.",
            ),
        ]

        initial_request = ChatRequest(model="test-model", messages=original_messages)
        initial_context = self.create_context(config, domain_request=initial_request)

        initial_session_id = await resolver.resolve_session_id(initial_context)
        session = Session(session_id=initial_session_id)
        await session_repository.add(session)

        initial_bundle = fingerprint_service.compute_fingerprint_bundle(
            original_messages
        )
        await session_repository.update_fingerprint(
            initial_session_id, initial_bundle.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(
            initial_session_id, initial_bundle
        )

        condensed_messages = [
            ChatMessage(
                role="system",
                content=(
                    "Summary: investigating project directory detection scoring. "
                    "Deterministic resolver incorrectly returns the .venv\\Scripts path."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    "Continue refining exclusion rules so the project root resolves to "
                    "the repository directory instead of virtual environment folders."
                ),
            ),
        ]

        # With explicit session ID header - should match
        condensed_request = ChatRequest(model="test-model", messages=condensed_messages)
        condensed_context = self.create_context(
            config,
            headers={"x-session-id": initial_session_id},
            domain_request=condensed_request,
        )

        matched_session_id = await resolver.resolve_session_id(condensed_context)

        # Should match via explicit session ID header
        assert matched_session_id == initial_session_id

        # Without explicit header - should create NEW session
        # (no structural evidence for fuzzy matching)
        condensed_context_no_header = self.create_context(
            config, domain_request=condensed_request
        )

        new_session_id = await resolver.resolve_session_id(condensed_context_no_header)

        # Should NOT match - condensed history without explicit ID creates new session
        assert new_session_id != initial_session_id

    @pytest.mark.asyncio
    async def test_resolve_new_session_different_client(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: AppConfig,
    ) -> None:
        """Test that different clients get different sessions even with same messages."""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi there!"),
        ]

        fp_bundle = fingerprint_service.compute_fingerprint_bundle(messages)

        # Create session for client A
        session_a = Session(session_id="session-client-a")
        await session_repository.add(session_a)
        await session_repository.update_fingerprint(
            "session-client-a", fp_bundle.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(
            "session-client-a", fp_bundle
        )
        await session_repository.update_client_session(
            "session-client-a", "192.168.1.1:hash123"
        )

        # Request from client B with same messages
        request = ChatRequest(model="test-model", messages=messages)
        context = self.create_context(
            config, client_host="192.168.1.2", domain_request=request
        )

        session_id = await resolver.resolve_session_id(context)

        # Should create new session for client B (different client key)
        assert session_id != "session-client-a"

    @pytest.mark.asyncio
    async def test_resolve_no_fuzzy_match_different_conversation(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        config: AppConfig,
    ) -> None:
        """Test that unrelated conversations don't match."""
        # Original conversation
        original_messages = [
            ChatMessage(role="user", content="What is Python?"),
            ChatMessage(role="assistant", content="Python is a programming language."),
        ]

        # Completely different conversation
        different_messages = [
            ChatMessage(role="user", content="Tell me about cooking."),
            ChatMessage(role="assistant", content="Cooking is an art..."),
        ]

        # Create session with original conversation
        fp_service = ConversationFingerprintService()
        fp_original_bundle = fp_service.compute_fingerprint_bundle(original_messages)

        existing_session = Session(session_id="session-python")
        await session_repository.add(existing_session)
        await session_repository.update_fingerprint(
            "session-python", fp_original_bundle.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(
            "session-python", fp_original_bundle
        )

        client_key = "127.0.0.1:5381df75"
        await session_repository.update_client_session("session-python", client_key)

        # Request with different conversation
        request = ChatRequest(model="test-model", messages=different_messages)
        context = self.create_context(config, domain_request=request)

        session_id = await resolver.resolve_session_id(context)

        # Should NOT match - create new session
        assert session_id != "session-python"

    @pytest.mark.asyncio
    async def test_client_key_generation(
        self,
        resolver: IntelligentSessionResolver,
        config: AppConfig,
    ) -> None:
        """Test that client key is generated consistently."""
        # Two contexts with same IP and user-agent
        context1 = self.create_context(
            config, headers={"user-agent": "TestAgent/1.0"}, client_host="192.168.1.100"
        )

        context2 = self.create_context(
            config, headers={"user-agent": "TestAgent/1.0"}, client_host="192.168.1.100"
        )

        # Both should generate new sessions (no messages)
        session_id1 = await resolver.resolve_session_id(context1)
        session_id2 = await resolver.resolve_session_id(context2)

        # Should create different sessions (no messages = no continuation)
        assert session_id1 is not None
        assert session_id2 is not None
        # They'll be different UUIDs since there's no conversation to match

    @pytest.mark.asyncio
    async def test_resolve_updates_client_session_mapping(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        config: AppConfig,
    ) -> None:
        """Test that session is registered to client after resolution."""
        messages = [
            ChatMessage(role="user", content="Hello"),
            ChatMessage(role="assistant", content="Hi!"),
        ]
        request = ChatRequest(model="test-model", messages=messages)

        context = self.create_context(config, domain_request=request)

        session_id = await resolver.resolve_session_id(context)

        # Session ID should be generated (resolver doesn't create Session entity, just ID)
        assert session_id is not None
        assert len(session_id) > 0

        # The client-session mapping should be recorded
        # (We can't directly verify this without exposing internals,
        # but we can verify a second request would create a new ID
        # since the session isn't persisted)
        session_id2 = await resolver.resolve_session_id(context)

        # Without persisting the session, should create new ID each time
        assert session_id2 != session_id

    @pytest.mark.asyncio
    async def test_no_cross_session_contamination_via_topic_similarity(
        self,
        resolver: IntelligentSessionResolver,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
        config: AppConfig,
    ) -> None:
        """Regression test: topic similarity should NOT merge separate conversations.

        This reproduces the critical bug where two OpenCode agents working on
        the same codebase were incorrectly merged into the same session via
        topic similarity matching, despite being completely separate tasks.

        Scenario from logs (2026-01-25):
        - Agent 1: Working on "random model replacement" feature
        - Agent 2: Working on "session already ended" warnings
        - Both agents had overlapping topic tokens (proxy, session, test, etc.)
        - Topic similarity incorrectly merged Agent 2 into Agent 1's session

        The fix: Topic similarity requires structural evidence (message count
        progression or rolling fingerprint overlap) to prevent contamination.
        """
        # Agent 1: Initial conversation about random model replacement
        agent1_messages = [
            ChatMessage(
                role="user",
                content=(
                    "Fix issues in the random model replacement feature in "
                    "llm-interactive-proxy. The proxy server is not activating "
                    "replacement correctly for test sessions."
                ),
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "I'll analyze the model_replacement_service.py to identify "
                    "why the dice roll is not activating replacement in test mode."
                ),
            ),
        ]

        # Agent 2: Completely separate conversation about session warnings
        agent2_messages = [
            ChatMessage(
                role="user",
                content=(
                    "Fix issues related to server log being spammed with "
                    "'Session already ended' warnings in the proxy server. "
                    "These warnings appear during streaming in llm-interactive-proxy."
                ),
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "I'll examine the end_of_session_stream_processor.py to understand "
                    "why the session state check is failing during streaming."
                ),
            ),
        ]

        # Create session for Agent 1
        request1 = ChatRequest(model="test-model", messages=agent1_messages)
        context1 = self.create_context(
            config,
            headers={"user-agent": "opencode/1.1.34"},
            client_host="127.0.0.1",
            domain_request=request1,
        )

        session_id1 = await resolver.resolve_session_id(context1)

        # Persist Agent 1 session
        session1 = Session(session_id=session_id1)
        await session_repository.add(session1)
        fp_bundle1 = fingerprint_service.compute_fingerprint_bundle(agent1_messages)
        await session_repository.update_fingerprint(
            session_id1, fp_bundle1.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(session_id1, fp_bundle1)

        # Create session for Agent 2 from SAME CLIENT (same IP + user-agent)
        request2 = ChatRequest(model="test-model", messages=agent2_messages)
        context2 = self.create_context(
            config,
            headers={"user-agent": "opencode/1.1.34"},
            client_host="127.0.0.1",
            domain_request=request2,
        )

        session_id2 = await resolver.resolve_session_id(context2)

        # CRITICAL: Agent 2 should get a NEW session, NOT match Agent 1
        # Topic similarity should NOT merge them without structural evidence
        assert session_id2 != session_id1, (
            "Cross-session contamination detected: Agent 2 was incorrectly matched "
            "to Agent 1's session via topic similarity despite being separate tasks. "
            f"session_id1={session_id1}, session_id2={session_id2}"
        )

        # Persist Agent 2 session
        session2 = Session(session_id=session_id2)
        await session_repository.add(session2)
        fp_bundle2 = fingerprint_service.compute_fingerprint_bundle(agent2_messages)
        await session_repository.update_fingerprint(
            session_id2, fp_bundle2.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(session_id2, fp_bundle2)

        # Verify that both sessions are tracked separately for the same client
        recent_sessions = await session_repository.find_recent_sessions_by_client(
            resolver._compute_client_key(context1),
            max_age_seconds=3600,
        )

        # Both sessions should exist for this client
        session_ids = {s.id for s in recent_sessions}
        assert session_id1 in session_ids
        assert session_id2 in session_ids
        assert len(session_ids) >= 2

    @pytest.mark.asyncio
    async def test_message_count_progression_must_not_match_even_when_topic_enabled(
        self,
        session_repository: InMemorySessionRepository,
        fingerprint_service: ConversationFingerprintService,
    ) -> None:
        """Regression test: message count progression must NEVER be treated as continuity.

        This protects against reintroducing the bug class where topic similarity
        + "incoming has more messages" could merge two *independent* parallel sessions.

        We explicitly enable topic similarity matching in config to ensure the only thing
        preventing the merge is the lack of direct continuity evidence (rolling overlap or
        identical last-user hash).
        """
        config = AppConfig(
            {
                "session": {
                    "session_continuity": {
                        "enable_topic_similarity_matching": True,
                    }
                }
            }
        )
        resolver = IntelligentSessionResolver(
            config=config,
            session_repository=session_repository,
            fingerprint_service=fingerprint_service,
        )

        # Session A: conversation about session resolver internals
        base_messages = [
            ChatMessage(
                role="user",
                content=(
                    "Please investigate llm-interactive-proxy session continuity. "
                    "Focus on intelligent_session_resolver and fingerprinting logic."
                ),
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "Understood. I'll inspect how sessions are resolved and how fingerprints "
                    "are computed and stored."
                ),
            ),
        ]

        request_a = ChatRequest(model="test-model", messages=base_messages)
        context_a = self.create_context(
            config,
            headers={"user-agent": "opencode/1.1.34"},
            client_host="127.0.0.1",
            domain_request=request_a,
        )
        session_id_a = await resolver.resolve_session_id(context_a)

        # Persist Session A fingerprints
        session_a = Session(session_id=session_id_a)
        await session_repository.add(session_a)
        bundle_a = fingerprint_service.compute_fingerprint_bundle(base_messages)
        await session_repository.update_fingerprint(
            session_id_a, bundle_a.primary.fingerprint
        )
        await session_repository.update_fingerprint_bundle(session_id_a, bundle_a)

        # Session B: topically similar, but different conversation and different messages.
        # It has more messages (message count progressed), but must NOT match unless there is
        # direct continuity evidence.
        other_messages = [
            ChatMessage(
                role="user",
                content=(
                    "I need help with llm-interactive-proxy sessions and continuity heuristics. "
                    "Review how the proxy decides a session id during request processing."
                ),
            ),
            ChatMessage(
                role="assistant",
                content=(
                    "I'll review the session matching heuristics and how they relate to the proxy's "
                    "request lifecycle."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    "Also, look at random model replacement while you are there (separate task)."
                ),
            ),
            ChatMessage(
                role="assistant", content="Ok, I'll also review model replacement."
            ),
        ]

        request_b = ChatRequest(model="test-model", messages=other_messages)
        context_b = self.create_context(
            config,
            headers={"user-agent": "opencode/1.1.34"},
            client_host="127.0.0.1",
            domain_request=request_b,
        )

        session_id_b = await resolver.resolve_session_id(context_b)

        # Even with topic matching enabled, we must NOT merge based on message count.
        assert session_id_b != session_id_a
