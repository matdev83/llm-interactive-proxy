from __future__ import annotations

import time
from typing import cast

from src.connectors._openai_codex_capabilities import CodexClientCapabilities
from src.connectors.openai_codex.continuation import (
    CodexContinuationSnapshot,
    InMemoryCodexContinuationCoordinator,
)
from src.connectors.openai_codex.contracts import (
    CodexRequestContext,
    ProcessedMessage,
)
from src.core.domain.chat import CanonicalChatRequest, ChatMessage


def _context(
    session_id: str,
    *,
    model: str = "gpt-5.1-codex",
    prompt_cache_key: str = "prompt-a",
) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
    )
    return CodexRequestContext(
        request=request,
        processed_messages=[ProcessedMessage(role="user", content="hello")],
        effective_model=model,
        capabilities=CodexClientCapabilities(),
        session_id=session_id,
        metadata={
            "continuation_backend": "openai-codex",
            "continuation_prompt_cache_key": prompt_cache_key,
        },
    )


def test_in_memory_continuation_records_and_invalidates() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    context = _context("session-1")

    assert coordinator.resolve_previous_response_id(context) is None

    coordinator.record_response_id(context, "resp-1")
    assert coordinator.resolve_previous_response_id(context) == "resp-1"

    coordinator.invalidate(context, reason="test")
    assert coordinator.resolve_previous_response_id(context) is None


def test_in_memory_continuation_expires_and_evicts_oldest() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=1, max_entries=1)
    first = _context("session-1", prompt_cache_key="prompt-a")
    second = _context("session-2", prompt_cache_key="prompt-b")

    coordinator.record_response_id(first, "resp-1")
    coordinator.record_response_id(second, "resp-2")

    assert coordinator.resolve_previous_response_id(first) is None
    assert coordinator.resolve_previous_response_id(second) == "resp-2"

    expiring = InMemoryCodexContinuationCoordinator(ttl_seconds=1, max_entries=2)
    expiring.record_response_id(first, "resp-expire")
    time.sleep(1.05)

    assert expiring.resolve_previous_response_id(first) is None


def test_in_memory_continuation_records_payload_snapshot() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    context = _context("session-1")

    coordinator.record_turn(
        context,
        response_id="resp-snap",
        payload_dict={
            "input": [
                {"type": "message", "role": "user", "content": "hello"},
                {"type": "message", "role": "assistant", "content": "hi"},
            ],
            "instructions": "bootstrap",
            "tools": [{"name": "read_file", "type": "function", "parameters": {}}],
        },
    )

    snapshot = coordinator.get_snapshot(context)

    assert isinstance(snapshot, CodexContinuationSnapshot)
    assert snapshot.response_id == "resp-snap"
    assert len(snapshot.input_fingerprints) == 2
    assert snapshot.instructions_fingerprint is not None
    assert snapshot.tools_fingerprint is not None


def test_continuation_key_uses_request_agent_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    opencode_context = _context("session-1")
    generic_context = _context("session-1")
    object.__setattr__(opencode_context.request, "agent", "opencode/1.0")

    coordinator.record_response_id(opencode_context, "resp-opencode")

    assert coordinator.resolve_previous_response_id(generic_context) is None


def test_continuation_key_uses_extra_body_agent_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    cline_like_context = _context("session-1")
    generic_context = _context("session-1")
    object.__setattr__(
        cline_like_context.request,
        "extra_body",
        {"agent": "kilocode/2.0"},
    )

    coordinator.record_response_id(cline_like_context, "resp-cline")

    assert coordinator.resolve_previous_response_id(generic_context) is None


def test_continuation_key_uses_user_agent_header_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    droid_context = _context("session-1")
    generic_context = _context("session-1")
    metadata = cast(dict[str, object], droid_context.metadata)
    metadata["headers"] = {"User-Agent": "factory-cli/1.0"}

    coordinator.record_response_id(droid_context, "resp-droid")

    assert coordinator.resolve_previous_response_id(generic_context) is None


def test_continuation_key_separates_different_client_families_in_same_session() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    opencode_context = _context("session-1")
    droid_context = _context("session-1")
    object.__setattr__(opencode_context.request, "agent", "opencode/1.0")
    metadata = cast(dict[str, object], droid_context.metadata)
    metadata["headers"] = {"User-Agent": "factory-cli/1.0"}

    coordinator.record_response_id(opencode_context, "resp-opencode")

    assert coordinator.resolve_previous_response_id(droid_context) is None
