from __future__ import annotations

from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.services.auxiliary_identity import (
    build_auxiliary_effective_session_id,
    derive_auxiliary_operation_key,
)


def _build_context(*, request_id: str | None) -> RequestContext:
    return RequestContext(
        headers={},
        cookies={},
        state={},
        app_state={},
        request_id=request_id,
    )


def test_build_auxiliary_effective_session_id_is_deterministic_and_non_leaking() -> (
    None
):
    root_session_id = "llm-b2bua-a-1234"
    first = build_auxiliary_effective_session_id(
        root_session_id=root_session_id,
        purpose="openai:gpt-4o-mini",
        operation_key="req:req-1",
        attempt_ordinal=1,
    )
    second = build_auxiliary_effective_session_id(
        root_session_id=root_session_id,
        purpose="openai:gpt-4o-mini",
        operation_key="req:req-1",
        attempt_ordinal=1,
    )

    assert first == second
    assert first.startswith("aux-1-")
    assert root_session_id not in first


def test_build_auxiliary_effective_session_id_changes_with_attempt_ordinal() -> None:
    first = build_auxiliary_effective_session_id(
        root_session_id="llm-b2bua-a-1234",
        purpose="openai:gpt-4o-mini",
        operation_key="req:req-1",
        attempt_ordinal=1,
    )
    second = build_auxiliary_effective_session_id(
        root_session_id="llm-b2bua-a-1234",
        purpose="openai:gpt-4o-mini",
        operation_key="req:req-1",
        attempt_ordinal=2,
    )

    assert first != second
    assert second.startswith("aux-2-")


def test_derive_auxiliary_operation_key_prefers_request_id() -> None:
    context = _build_context(request_id="req-abc")
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
    )

    operation_key = derive_auxiliary_operation_key(
        context=context,
        request_data=request,
        purpose="openai:gpt-4o-mini",
    )

    assert operation_key == "req:req-abc"


def test_derive_auxiliary_operation_key_falls_back_to_message_digest() -> None:
    context = _build_context(request_id=None)
    request = ChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="generate a title")],
    )

    operation_key = derive_auxiliary_operation_key(
        context=context,
        request_data=request,
        purpose="openai:gpt-4o-mini",
    )

    assert operation_key.startswith("msg:")
