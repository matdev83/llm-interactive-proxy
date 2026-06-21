from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
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
    extra_body: dict[str, Any] | None = None,
) -> CodexRequestContext:
    request = CanonicalChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content="hello")],
        stream=True,
        extra_body=extra_body,
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


@pytest.mark.asyncio
async def test_in_memory_continuation_records_and_invalidates() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    context = _context("session-1")

    assert await coordinator.resolve_previous_response_id(context) is None

    await coordinator.record_response_id(context, "resp-1")
    assert await coordinator.resolve_previous_response_id(context) == "resp-1"

    await coordinator.invalidate(context, reason="test")
    assert await coordinator.resolve_previous_response_id(context) is None


@pytest.mark.asyncio
async def test_in_memory_continuation_expires_and_evicts_oldest() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=1, max_entries=1)
    first = _context("session-1", prompt_cache_key="prompt-a")
    second = _context("session-2", prompt_cache_key="prompt-b")

    await coordinator.record_response_id(first, "resp-1")
    await coordinator.record_response_id(second, "resp-2")

    assert await coordinator.resolve_previous_response_id(first) is None
    assert await coordinator.resolve_previous_response_id(second) == "resp-2"

    expiring = InMemoryCodexContinuationCoordinator(ttl_seconds=1, max_entries=2)
    start_time = 100.0
    with patch("time.monotonic", side_effect=[start_time, start_time + 1.05]):
        await expiring.record_response_id(first, "resp-expire")
        assert await expiring.resolve_previous_response_id(first) is None


@pytest.mark.asyncio
async def test_in_memory_continuation_records_payload_snapshot() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    context = _context("session-1")

    await coordinator.record_turn(
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

    snapshot = await coordinator.get_snapshot(context)

    assert isinstance(snapshot, CodexContinuationSnapshot)
    assert snapshot.response_id == "resp-snap"
    assert len(snapshot.input_fingerprints) == 2
    assert snapshot.instructions_fingerprint is not None
    assert snapshot.tools_fingerprint is not None


@pytest.mark.asyncio
async def test_continuation_key_uses_request_agent_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator(ttl_seconds=60, max_entries=4)
    # Simulate agent via extra_body
    context = _context("session-1", extra_body={"agent": "kilocode/1.2.3"})

    await coordinator.record_response_id(context, "resp-kilo")
    assert await coordinator.resolve_previous_response_id(context) == "resp-kilo"

    # Generic context in same session should NOT see it
    generic = _context("session-1")
    assert await coordinator.resolve_previous_response_id(generic) is None


@pytest.mark.asyncio
async def test_continuation_key_uses_extra_body_agent_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator()
    context = _context("s1", extra_body={"agent": "roo-cline/0.1.0"})

    await coordinator.record_response_id(context, "id1")

    # Cline-like should find it
    cline = _context("s1")
    assert cline.metadata is not None
    cline.metadata["agent"] = "cline"
    assert await coordinator.resolve_previous_response_id(cline) == "id1"


@pytest.mark.asyncio
async def test_continuation_key_uses_user_agent_header_family_signal() -> None:
    coordinator = InMemoryCodexContinuationCoordinator()
    context = _context("s1")
    assert context.metadata is not None
    context.metadata["headers"] = {"User-Agent": "factory_cli/v1"}

    await coordinator.record_response_id(context, "id1")

    # Droid should find it
    droid = _context("s1")
    assert droid.metadata is not None
    droid.metadata["headers"] = {"user-agent": "factorydroid"}
    assert await coordinator.resolve_previous_response_id(droid) == "id1"


@pytest.mark.asyncio
async def test_continuation_key_does_not_treat_android_user_agent_as_droid() -> None:
    coordinator = InMemoryCodexContinuationCoordinator()
    context = _context("s1")
    assert context.metadata is not None
    context.metadata["headers"] = {"User-Agent": "Mozilla/5.0 (Android 10)"}

    await coordinator.record_response_id(context, "id1")

    # Generic should find it (since both are generic)
    generic = _context("s1")
    assert await coordinator.resolve_previous_response_id(generic) == "id1"

    # Droid should NOT
    droid = _context("s1")
    assert droid.metadata is not None
    droid.metadata["headers"] = {"User-Agent": "factorydroid"}
    assert await coordinator.resolve_previous_response_id(droid) is None


@pytest.mark.asyncio
async def test_continuation_key_separates_different_client_families_in_same_session() -> (
    None
):
    coordinator = InMemoryCodexContinuationCoordinator()
    s1 = "session-1"

    # Register 3 different ID lineages for the same session ID but different client families
    await coordinator.record_response_id(
        _context(s1, prompt_cache_key="a"), "id-generic"
    )

    opencode = _context(s1, prompt_cache_key="a", extra_body={"agent": "opencode-go"})
    await coordinator.record_response_id(opencode, "id-opencode")

    droid = _context(s1, prompt_cache_key="a")
    assert droid.metadata is not None
    droid.metadata["headers"] = {"user-agent": "factory-cli"}
    await coordinator.record_response_id(droid, "id-droid")

    # Verify isolation
    assert (
        await coordinator.resolve_previous_response_id(
            _context(s1, prompt_cache_key="a")
        )
        == "id-generic"
    )
    assert await coordinator.resolve_previous_response_id(opencode) == "id-opencode"
    assert await coordinator.resolve_previous_response_id(droid) == "id-droid"
