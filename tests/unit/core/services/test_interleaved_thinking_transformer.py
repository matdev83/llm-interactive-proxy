from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.models.backends import BackendSettings
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.request_context import RequestContext
from src.core.domain.session import SessionState
from src.core.services.composite_routing_state import (
    COMPOSITE_ROUTING_SURFACE_KEY,
    COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY,
)
from src.core.services.interleaved_thinking.transformer import (
    INTERLEAVED_THINKING_ACTIVE_KEY,
    INTERLEAVED_THINKING_DIAGNOSTIC_KEY,
    InterleavedThinkingRequestTransformer,
)


def _context(*, thinker: bool = False, surface: str = "main") -> RequestContext:
    context = RequestContext(
        headers={},
        cookies={},
        state={},
        app_state=None,
        request_id="req-transformer",
        session_id="session-transformer",
    )
    context.extensions[COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY] = thinker
    context.extensions[COMPOSITE_ROUTING_SURFACE_KEY] = surface
    return context


def _request() -> CanonicalChatRequest:
    return CanonicalChatRequest(
        model="gpt-4",
        messages=[ChatMessage(role="user", content="hello")],
        tools=[{"type": "function", "function": {"name": "do_it"}}],
        tool_choice="auto",
        parallel_tool_calls=True,
    )


def _diagnostic(context: RequestContext) -> dict[str, Any]:
    return cast(dict[str, Any], context.extensions[INTERLEAVED_THINKING_DIAGNOSTIC_KEY])


def _stateful_session(state: SessionState) -> MagicMock:
    session = MagicMock()
    session.state = state

    def update_state(updated_state: SessionState) -> None:
        session.state = updated_state

    session.update_state = MagicMock(side_effect=update_state)
    return session


def test_transformer_adds_thinker_instructions_and_suppresses_tools(
    tmp_path: Path,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Thinker instructions", encoding="utf-8")
    transformer = InterleavedThinkingRequestTransformer(
        BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
        )
    )
    context = _context(thinker=True)

    transformed = transformer.transform(
        request=_request(),
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        session=MagicMock(state=SessionState()),
        context=context,
    )

    assert transformed.messages[0].role == "system"
    assert transformed.messages[0].content == "Thinker instructions"
    assert transformed.messages[0].metadata == {
        "source": "interleaved_thinking",
        "kind": "thinker_instructions",
    }
    assert transformed.tools is None
    assert transformed.tool_choice is None
    assert transformed.parallel_tool_calls is None
    assert context.extensions[INTERLEAVED_THINKING_ACTIVE_KEY] is True
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "thinker_prompt_injected"
    assert diagnostic["target_backend"] == "openai"
    assert diagnostic["target_model"] == "gpt-4"
    assert diagnostic["message_count_before"] == 1
    assert diagnostic["message_count_after"] == 2


def test_transformer_loads_shipped_default_thinker_prompt() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    context = _context(thinker=True)

    transformed = transformer.transform(
        request=_request(),
        target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
        session=MagicMock(state=SessionState()),
        context=context,
    )

    assert transformed.messages[0].role == "system"
    prompt = str(transformed.messages[0].content)
    assert "thinker" in prompt.lower()
    assert "<proxy_thinker_memo>" in prompt
    assert "</proxy_thinker_memo>" in prompt


def test_transformer_caches_loaded_thinker_instructions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instructions_file = tmp_path / "thinker.md"
    instructions_file.write_text("Cached thinker instructions", encoding="utf-8")
    read_count = 0
    original_read_text = Path.read_text

    def read_text_once(
        self: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        nonlocal read_count
        read_count += 1
        return original_read_text(self, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", read_text_once)
    transformer = InterleavedThinkingRequestTransformer(
        BackendSettings(
            interleaved_thinking_instructions_file=str(instructions_file),
        )
    )

    for _ in range(2):
        transformed = transformer.transform(
            request=_request(),
            target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            session=MagicMock(state=SessionState()),
            context=_context(thinker=True),
        )
        assert transformed.messages[0].content == "Cached thinker instructions"

    assert read_count == 1


def test_transformer_raises_when_thinker_instructions_file_is_missing() -> None:
    transformer = InterleavedThinkingRequestTransformer(
        BackendSettings(
            interleaved_thinking_instructions_file="does/not/exist.md",
        )
    )

    with pytest.raises(ConfigurationError):
        transformer.transform(
            request=_request(),
            target=BackendTarget(backend="openai", model="gpt-4", uri_params={}),
            session=MagicMock(state=SessionState()),
            context=_context(thinker=True),
        )


def test_transformer_injects_stored_memo_into_non_thinker_request() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "injected_count": 0,
            }
        )
    )
    session.update_state = MagicMock()

    context = _context(thinker=False)

    transformed = transformer.transform(
        request=_request(),
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=context,
    )

    assert transformed.messages[0].role == "system"
    assert "Stored thinker memo" in str(transformed.messages[0].content)
    assert transformed.messages[0].metadata == {
        "source": "interleaved_thinking",
        "kind": "thinker_memo_system",
    }
    assert transformed.messages[-2].role == "assistant"
    assert transformed.messages[-2].content == ""
    assert transformed.messages[-2].reasoning_content == "Stored thinker memo"
    assert transformed.messages[-2].metadata == {
        "source": "interleaved_thinking",
        "kind": "thinker_memo_reasoning",
    }
    assert transformed.messages[-1].role == "user"
    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 1
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injected"
    assert diagnostic["target_backend"] == "openrouter"
    assert diagnostic["target_model"] == "flash"
    assert diagnostic["memo_chars"] == len("Stored thinker memo")
    assert diagnostic["message_count_before"] == 1
    assert diagnostic["message_count_after"] == 3


def test_transformer_skips_stored_memo_when_reasoning_content_exists() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "injected_count": 0,
            }
        )
    )
    session.update_state = MagicMock()
    context = _context(thinker=False)
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="assistant",
                content="",
                reasoning_content="client-carried thinker memo",
            ),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=context,
    )

    assert transformed.messages == request.messages
    session.update_state.assert_not_called()
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injection_skipped"
    assert diagnostic["reason"] == "request_already_has_reasoning_content"
    assert diagnostic["request_reasoning_messages"] == 1
    assert diagnostic["request_reasoning_chars"] == len("client-carried thinker memo")
    assert diagnostic["message_count_before"] == 2
    assert diagnostic["message_count_after"] == 2


def test_transformer_injects_deepseek_memo_as_visible_context_when_reasoning_exists() -> (
    None
):
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "injected_count": 0,
            }
        )
    )
    session.update_state = MagicMock()
    context = _context(thinker=False)
    request = CanonicalChatRequest(
        model="deepseek-v4-flash-free",
        messages=[
            ChatMessage(
                role="assistant",
                content="",
                reasoning_content="stale DeepSeek-incompatible reasoning",
            ),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(
            backend="opencode-zen.1",
            model="deepseek-v4-flash-free",
            uri_params={},
        ),
        session=session,
        context=context,
    )

    assert transformed.messages[0].role == "system"
    assert "Stored thinker memo" in str(transformed.messages[0].content)
    assert transformed.messages[1:] == request.messages
    assert all(
        message.reasoning_content != "Stored thinker memo"
        for message in transformed.messages
    )
    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 1
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injected"
    assert diagnostic["memo_chars"] == len("Stored thinker memo")
    assert diagnostic["message_count_before"] == 2
    assert diagnostic["message_count_after"] == 3


def test_transformer_skips_visible_memo_already_carried_by_client_context() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = _stateful_session(
        SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "injected_count": 0,
                "regular_turns_remaining": 2,
                "visible_to_client": True,
            }
        )
    )
    context = _context(thinker=False)
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="assistant", content="Stored thinker memo"),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=context,
    )

    assert transformed.messages == request.messages
    updated_state = session.state
    assert updated_state.interleaved_thinking_state["injected_count"] == 0
    assert updated_state.interleaved_thinking_state["regular_turns_remaining"] == 1
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injection_skipped"
    assert diagnostic["reason"] == "memo_already_visible_in_request"


def test_transformer_records_skip_reason_when_non_thinker_has_no_memo() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    context = _context(thinker=False)

    transformed = transformer.transform(
        request=_request(),
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=MagicMock(state=SessionState()),
        context=context,
    )

    assert transformed.messages == _request().messages
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injection_skipped"
    assert diagnostic["reason"] == "no_stored_memo"


def test_transformer_records_existing_reasoning_content_when_no_stored_memo() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    context = _context(thinker=False)
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="assistant", content="", reasoning_content="memo"),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=MagicMock(state=SessionState()),
        context=context,
    )

    assert transformed.messages == request.messages
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injection_skipped"
    assert diagnostic["reason"] == "no_stored_memo"
    assert diagnostic["request_reasoning_messages"] == 1
    assert diagnostic["request_reasoning_chars"] == len("memo")


def test_transformer_increments_existing_injected_count() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "injected_count": 2,
            }
        )
    )
    session.update_state = MagicMock()

    transformer.transform(
        request=_request(),
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=_context(thinker=False),
    )

    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 3


def test_transformer_skips_non_main_surfaces() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    original = _request()
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
            }
        )
    )

    transformed = transformer.transform(
        request=original,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=_context(thinker=False, surface="auxiliary"),
    )

    assert transformed is original
