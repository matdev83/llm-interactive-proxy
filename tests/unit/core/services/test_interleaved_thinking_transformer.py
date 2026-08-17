from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from src.core.common.exceptions import ConfigurationError
from src.core.config.models.backends import BackendSettings
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import (
    CanonicalChatRequest,
    ChatMessage,
    FunctionCall,
    ToolCall,
)
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
    assert "Session Steering Memo" in prompt
    assert "<proxy_thinker_memo>" not in prompt


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
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=context,
    )

    # Prefix message is 100% untouched for cache preservation
    assert transformed.messages[0] == request.messages[0]
    # Tail message receives the steering guidance
    assert transformed.messages[-1].role == "user"
    assert "hello" in str(transformed.messages[-1].content)
    assert "[Session Steering Guidance]" in str(transformed.messages[-1].content)
    assert "Stored thinker memo" in str(transformed.messages[-1].content)
    metadata_last = transformed.messages[-1].metadata or {}
    assert metadata_last.get("source") == "interleaved_thinking"
    assert metadata_last.get("kind") == "thinker_memo_tail"

    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 1
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injected"
    assert diagnostic["target_backend"] == "openrouter"
    assert diagnostic["target_model"] == "flash"
    assert diagnostic["memo_chars"] == len("Stored thinker memo")
    assert diagnostic["message_count_before"] == 2
    assert diagnostic["message_count_after"] == 2


def test_transformer_injects_stored_memo_into_tool_result_message() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Plan next tool call",
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
            ChatMessage(role="system", content="System base"),
            ChatMessage(role="user", content="Read file"),
            ChatMessage(
                role="assistant",
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        type="function",
                        function=FunctionCall(name="read_file", arguments="{}"),
                    )
                ],
            ),
            ChatMessage(
                role="tool",
                content="file content line 1",
                tool_call_id="call-1",
            ),
        ],
    )

    transformed = transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=session,
        context=context,
    )

    # Prefix (messages 0, 1, 2) is completely identical (100% cache hit)
    assert transformed.messages[:3] == request.messages[:3]
    # Tail tool result is augmented with guidance
    assert transformed.messages[-1].role == "tool"
    assert "file content line 1" in str(transformed.messages[-1].content)
    assert "[Session Steering Guidance]" in str(transformed.messages[-1].content)
    assert "Plan next tool call" in str(transformed.messages[-1].content)
    tool_metadata = transformed.messages[-1].metadata or {}
    assert tool_metadata.get("source") == "interleaved_thinking"
    assert tool_metadata.get("kind") == "thinker_memo_tail"


def test_transformer_injects_deepseek_memo_as_tail_context() -> None:
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
            ChatMessage(role="system", content="System base prompt"),
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

    # Prefix message 0 is untouched
    assert transformed.messages[0] == request.messages[0]
    # Tail message has memo
    assert "Stored thinker memo" in str(transformed.messages[-1].content)
    assert "[Session Steering Guidance]" in str(transformed.messages[-1].content)
    updated_state = session.update_state.call_args.args[0]
    assert updated_state.interleaved_thinking_state["injected_count"] == 1
    diagnostic = _diagnostic(context)
    assert diagnostic["action"] == "memo_injected"
    assert diagnostic["memo_chars"] == len("Stored thinker memo")
    assert diagnostic["message_count_before"] == 2
    assert diagnostic["message_count_after"] == 2


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


def test_transformer_reasoning_snippets_are_safe_for_windows_log_streams() -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    context = _context(thinker=False)
    request = CanonicalChatRequest(
        model="gpt-4",
        messages=[
            ChatMessage(
                role="assistant",
                content="",
                reasoning_content=(
                    "content.content is StopChunkWithUsage "
                    "\u2192 _serialize_stop_chunk_with_usage"
                ),
            ),
            ChatMessage(role="user", content="hello"),
        ],
    )

    transformer.transform(
        request=request,
        target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
        session=MagicMock(state=SessionState()),
        context=context,
    )

    diagnostic = _diagnostic(context)
    snippet = diagnostic["request_reasoning_first_snippet"]
    assert isinstance(snippet, str)
    assert "\\u2192" in snippet
    snippet.encode("cp1250")


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


def test_transformer_logs_memo_injection_with_turn_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transformer = InterleavedThinkingRequestTransformer(BackendSettings())
    original = _request()
    session = MagicMock(
        state=SessionState(
            interleaved_thinking_state={
                "memo": "Stored thinker memo",
                "source_selector": "openai:gpt-4",
                "regular_turns_remaining": 3,
            }
        )
    )

    with caplog.at_level(
        logging.INFO,
        logger="src.core.services.interleaved_thinking.transformer",
    ):
        context = _context(thinker=False)
        transformer.transform(
            request=original,
            target=BackendTarget(backend="openrouter", model="flash", uri_params={}),
            session=session,
            context=context,
        )

    assert any(
        "Interleaved thinking memo injected:" in record.message
        and "memo_chars=19" in record.message
        and "turns_remaining=3" in record.message
        for record in caplog.records
    )
