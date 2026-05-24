"""Integration test for parallel agent session isolation.

This test reproduces the critical bug discovered on 2026-01-25 where two
OpenCode agents working on different tasks were incorrectly merged into
the same session via fuzzy topic similarity matching.

Bug scenario from production logs:
- Agent 1: Working on "random model replacement" fixes
- Agent 2: Working on "session already ended" warnings
- Both from same client (IP + user-agent: opencode/1.1.34)
- Both working on llm-interactive-proxy codebase
- At 00:36:26.929, Agent 2's request was incorrectly matched to Agent 1's session
  via topic similarity despite no structural evidence of continuation
- Later at 00:48:56, the larger context from Agent 1 contaminated Agent 2

This test verifies the fix that requires structural evidence (message count
progression or rolling fingerprint overlap) before allowing topic similarity matching.
"""

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


@pytest.mark.asyncio
async def test_parallel_agents_remain_isolated() -> None:
    """Test that parallel agents from same client remain isolated.

    Reproduces: Critical bug from 2026-01-25 where two OpenCode agents
    working on different tasks were merged via topic similarity.
    """
    # Setup
    config = AppConfig()
    session_repository = InMemorySessionRepository()
    fingerprint_service = ConversationFingerprintService()
    resolver = IntelligentSessionResolver(
        session_repository=session_repository,
        fingerprint_service=fingerprint_service,
        config=config,
    )

    # Agent 1: Initial conversation about random model replacement
    agent1_messages = [
        ChatMessage(
            role="user",
            content=(
                "Fix issues in the random model replacement feature. "
                "The proxy server is not activating replacement correctly "
                "for test sessions in llm-interactive-proxy. Check the "
                "model_replacement_service.py and dice roll logic."
            ),
        ),
        ChatMessage(
            role="assistant",
            content=(
                "I'll analyze the model_replacement_service.py to identify "
                "why the dice roll is not activating replacement in test mode. "
                "Let me examine the probability calculation and session state."
            ),
        ),
    ]

    agent1_request = ChatRequest(model="test-model", messages=agent1_messages)
    agent1_context = RequestContext(
        headers={"user-agent": "opencode/1.1.34 ai-sdk/provider-utils/3.0.20"},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
    )
    agent1_context.domain_request = agent1_request  # type: ignore

    session_id1 = await resolver.resolve_session_id(agent1_context)

    # Persist Agent 1 session
    session1 = Session(session_id=session_id1)
    await session_repository.add(session1)
    fp_bundle1 = fingerprint_service.compute_fingerprint_bundle(agent1_messages)
    await session_repository.update_fingerprint(
        session_id1, fp_bundle1.primary.fingerprint
    )
    await session_repository.update_fingerprint_bundle(session_id1, fp_bundle1)

    # Agent 2: Initial conversation about session warnings (DIFFERENT TASK, SAME CLIENT)
    # This simulates the exact scenario from logs where a second OpenCode agent
    # started working on a completely different issue but was incorrectly matched
    # to the first agent's session via topic similarity
    agent2_messages = [
        ChatMessage(
            role="user",
            content=(
                "Fix issues related to server log being spammed with "
                "'Session already ended' warnings. These appear during "
                "streaming in the llm-interactive-proxy. Investigate the "
                "end_of_session_stream_processor.py and session state checks."
            ),
        ),
        ChatMessage(
            role="assistant",
            content=(
                "I'll examine the end_of_session_stream_processor.py to understand "
                "why the session state check is failing during streaming. "
                "Let me look for the 'already ended' logic and session lifecycle."
            ),
        ),
    ]

    agent2_request = ChatRequest(model="test-model", messages=agent2_messages)
    agent2_context = RequestContext(
        headers={"user-agent": "opencode/1.1.34 ai-sdk/provider-utils/3.0.20"},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
    )
    agent2_context.domain_request = agent2_request  # type: ignore

    session_id2 = await resolver.resolve_session_id(agent2_context)

    # CRITICAL ASSERTION: Agent 2 must get a NEW session
    # Before the fix: topic similarity would match (both mention "proxy", "session",
    # "llm-interactive-proxy", "test", "service") despite:
    # - No rolling fingerprint overlap (completely different message sequences)
    # - Same message count (both have 2 messages, so no count progression)
    # - Different last user messages (different tasks)
    #
    # After the fix: _has_structural_evidence returns False, preventing the match
    assert session_id2 != session_id1, (
        f"CRITICAL BUG REPRODUCED: Agent 2 (session {session_id2}) was incorrectly "
        f"matched to Agent 1 (session {session_id1}) via topic similarity alone. "
        "This causes cross-session contamination where both agents see each other's context."
    )


@pytest.mark.asyncio
async def test_topic_similarity_with_structural_evidence_still_matches() -> None:
    """Test that topic similarity WITH structural evidence correctly matches.

    When message count progresses (indicating actual continuation), topic
    similarity should still help match sessions even with some message drift.
    """
    # Setup
    config = AppConfig(
        {
            "session": {
                "session_continuity": {
                    "enable_topic_similarity_matching": True,
                }
            }
        }
    )
    session_repository = InMemorySessionRepository()
    fingerprint_service = ConversationFingerprintService()
    resolver = IntelligentSessionResolver(
        session_repository=session_repository,
        fingerprint_service=fingerprint_service,
        config=config,
    )

    # Initial conversation
    initial_messages = [
        ChatMessage(
            role="user",
            content="Analyze the authentication system in llm-interactive-proxy.",
        ),
        ChatMessage(role="assistant", content="I'll examine the auth modules..."),
    ]

    initial_request = ChatRequest(model="test-model", messages=initial_messages)
    initial_context = RequestContext(
        headers={"user-agent": "test-agent/1.0"},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
    )
    initial_context.domain_request = initial_request  # type: ignore

    session_id1 = await resolver.resolve_session_id(initial_context)

    # Persist session
    session1 = Session(session_id=session_id1)
    await session_repository.add(session1)
    fp_bundle1 = fingerprint_service.compute_fingerprint_bundle(initial_messages)
    await session_repository.update_fingerprint(
        session_id1, fp_bundle1.primary.fingerprint
    )
    await session_repository.update_fingerprint_bundle(session_id1, fp_bundle1)

    # Continuation with MORE messages (structural evidence of continuation)
    continuation_messages = [
        *initial_messages,
        ChatMessage(role="user", content="Check the SSO configuration."),
        ChatMessage(role="assistant", content="Looking at SSO settings..."),
    ]

    continuation_request = ChatRequest(
        model="test-model", messages=continuation_messages
    )
    continuation_context = RequestContext(
        headers={"user-agent": "test-agent/1.0"},
        cookies={},
        state=None,
        app_state=None,
        client_host="127.0.0.1",
    )
    continuation_context.domain_request = continuation_request  # type: ignore

    session_id2 = await resolver.resolve_session_id(continuation_context)

    # Should match because:
    # 1. Message count increased (2 -> 4) = structural evidence
    # 2. Has rolling fingerprint overlap (includes original messages)
    # 3. Topic similarity also matches
    assert session_id2 == session_id1
