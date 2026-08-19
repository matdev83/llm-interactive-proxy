from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from src.core.common.exceptions import ConfigurationError
from src.core.config.models.backends import BackendSettings
from src.core.domain.backend_target import BackendTarget
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.composite_routing import RoutingSurface
from src.core.domain.request_context import RequestContext
from src.core.interfaces.domain_entities_interface import ISession
from src.core.services.composite_routing_state import (
    COMPOSITE_ROUTING_SURFACE_KEY,
    COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY,
)
from src.core.services.interleaved_thinking.state_utils import (
    as_session_state,
    request_id,
    session_id,
)

logger = logging.getLogger(__name__)

INTERLEAVED_THINKING_ACTIVE_KEY = "interleaved_thinking_active"
INTERLEAVED_THINKING_DIAGNOSTIC_KEY = "interleaved_thinking_diagnostic"
INTERLEAVED_THINKING_SUPPRESS_MEMO_INJECTION_KEY = (
    "interleaved_thinking_suppress_memo_injection"
)
_DEFAULT_STEERING_INJECTION_HEADER = "[Session Steering Guidance]"
_SYNTHETIC_MEMO_MESSAGE_KIND = "thinker_memo_synthetic_user"
_DEFAULT_SYSTEM_INJECTION_PREFIX = (
    "The proxy captured this thinker memo for the next executor model. "
    "Use it as planning context, but obey the user's latest request."
)
_THINKER_MEMO_MARKER = "<proxy_thinker_memo"
_THINKER_FINAL_DIRECTIVE = (
    "Produce the compact steering memo now. Do not call tools, emit tool-call "
    "markup, or continue the user's task. Return memo text only."
)


@dataclass(frozen=True)
class _ReasoningContentStats:
    message_count: int = 0
    total_chars: int = 0
    interleaved_metadata_count: int = 0
    tagged_memo_count: int = 0
    first_role: str | None = None
    last_role: str | None = None
    first_hash: str | None = None
    last_hash: str | None = None
    first_snippet: str | None = None
    last_snippet: str | None = None


class InterleavedThinkingRequestTransformer:
    """Apply thinker instructions and inject stored thinker memos."""

    def __init__(self, settings: BackendSettings) -> None:
        self._settings = settings
        self._cached_instructions: str | None = None

    def transform(
        self,
        *,
        request: CanonicalChatRequest,
        target: BackendTarget,
        session: ISession | None,
        context: RequestContext | None,
    ) -> CanonicalChatRequest:
        if not self._is_main_surface(context):
            self._record_diagnostic(
                context,
                action="transform_skipped",
                reason="non_main_surface",
                target=target,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            logger.debug(
                "Interleaved thinking transform skipped: non-main surface "
                "request_id=%s session_id=%s backend=%s model=%s",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
            )
            return request

        if self._is_thinker_selected(context):
            instructions = self._load_instructions()
            thinker_history = self._history_without_tool_interactions(request.messages)
            messages = [
                ChatMessage(
                    role="system",
                    content=instructions,
                    metadata={
                        "source": "interleaved_thinking",
                        "kind": "thinker_instructions",
                    },
                ),
                *thinker_history,
                ChatMessage(
                    role="user",
                    content=_THINKER_FINAL_DIRECTIVE,
                    metadata={
                        "source": "interleaved_thinking",
                        "kind": "thinker_final_directive",
                    },
                ),
            ]
            request_updates: dict[str, Any] = {
                "messages": messages,
                "stream": False,
                "tools": None,
                "tool_choice": None,
                "parallel_tool_calls": None,
            }
            if context is not None:
                context.extensions[INTERLEAVED_THINKING_ACTIVE_KEY] = True
            self._record_diagnostic(
                context,
                action="thinker_prompt_injected",
                target=target,
                memo_chars=None,
                message_count_before=len(request.messages),
                message_count_after=len(messages),
            )
            logger.info(
                "Interleaved thinking prompt injected: request_id=%s "
                "session_id=%s backend=%s model=%s instructions_chars=%d "
                "messages_before=%d messages_after=%d tools_present_before=%s "
                "tools_forwarded=False stream_forwarded=False",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
                len(instructions),
                len(request.messages),
                len(messages),
                bool(request.tools),
            )
            return request.model_copy(update=request_updates)

        reasoning_stats = self._request_reasoning_content_stats(request)
        memo = self._get_stored_memo(session)
        if self._is_memo_injection_suppressed(context):
            self._record_diagnostic(
                context,
                action="memo_injection_skipped",
                reason="suppressed_by_continuation",
                target=target,
                memo_chars=len(memo) if memo else None,
                request_reasoning=reasoning_stats,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            logger.info(
                "Interleaved thinking memo injection skipped: suppressed by "
                "continuation request_id=%s session_id=%s backend=%s model=%s "
                "stored_memo_chars=%d",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
                len(memo) if memo else 0,
            )
            return request
        if not memo:
            self._record_diagnostic(
                context,
                action="memo_injection_skipped",
                reason="no_stored_memo",
                target=target,
                request_reasoning=reasoning_stats,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            if reasoning_stats.message_count:
                logger.info(
                    "Interleaved thinking memo injection skipped: no stored proxy memo, "
                    "but request already carries reasoning_content "
                    "request_id=%s session_id=%s backend=%s model=%s "
                    "reasoning_messages=%d reasoning_chars=%d "
                    "reasoning_interleaved_metadata_messages=%d "
                    "reasoning_tagged_memo_messages=%d first_role=%s last_role=%s "
                    "first_hash=%s last_hash=%s first_snippet=%r last_snippet=%r "
                    "interpretation=%s",
                    request_id(context),
                    session_id(context, session),
                    target.backend,
                    target.model,
                    reasoning_stats.message_count,
                    reasoning_stats.total_chars,
                    reasoning_stats.interleaved_metadata_count,
                    reasoning_stats.tagged_memo_count,
                    reasoning_stats.first_role,
                    reasoning_stats.last_role,
                    reasoning_stats.first_hash,
                    reasoning_stats.last_hash,
                    reasoning_stats.first_snippet,
                    reasoning_stats.last_snippet,
                    self._reasoning_interpretation(reasoning_stats),
                )
            else:
                logger.info(
                    "Interleaved thinking memo injection skipped: no stored memo "
                    "request_id=%s session_id=%s backend=%s model=%s",
                    request_id(context),
                    session_id(context, session),
                    target.backend,
                    target.model,
                )
            return request

        if self._stored_memo_was_visible_to_client(
            session
        ) and self._request_contains_visible_memo(request, memo):
            self._consume_regular_turn(session)
            self._record_diagnostic(
                context,
                action="memo_injection_skipped",
                reason="memo_already_visible_in_request",
                target=target,
                memo_chars=len(memo),
                request_reasoning=reasoning_stats,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            logger.info(
                "Interleaved thinking memo injection skipped: visible memo already "
                "present in request context request_id=%s session_id=%s backend=%s "
                "model=%s memo_chars=%d",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
                len(memo),
            )
            return request

        messages = self._inject_memo_at_tail(list(request.messages), memo)
        self._increment_injected_count(session)
        self._record_diagnostic(
            context,
            action="memo_injected",
            target=target,
            memo_chars=len(memo),
            message_count_before=len(request.messages),
            message_count_after=len(messages),
            injection_mode="synthetic_user",
        )
        stored_state = self._get_interleaved_state(session)
        turns_remaining = (
            stored_state.get("regular_turns_remaining")
            if isinstance(stored_state, dict)
            else None
        )
        logger.info(
            "Interleaved thinking memo injected: request_id=%s session_id=%s "
            "backend=%s model=%s memo_chars=%d memo_hash=%s memo_snippet=%r "
            "turns_remaining=%s messages_before=%d "
            "messages_after=%d injection_mode=%s "
            "synthetic_role=%s tools_present=%s",
            request_id(context),
            session_id(context, session),
            target.backend,
            target.model,
            len(memo),
            self._text_hash(memo),
            self._snippet(memo),
            turns_remaining,
            len(request.messages),
            len(messages),
            "synthetic_user",
            "user",
            bool(request.tools),
        )
        return request.model_copy(update={"messages": messages})

    @classmethod
    def _record_diagnostic(
        cls,
        context: RequestContext | None,
        *,
        action: str,
        target: BackendTarget,
        reason: str | None = None,
        memo_chars: int | None = None,
        request_reasoning: _ReasoningContentStats | None = None,
        message_count_before: int,
        message_count_after: int,
        injection_mode: str | None = None,
    ) -> None:
        if context is None:
            return
        diagnostic: dict[str, Any] = {
            "action": action,
            "target_backend": target.backend,
            "target_model": target.model,
            "request_id": context.request_id,
            "session_id": context.session_id,
            "message_count_before": message_count_before,
            "message_count_after": message_count_after,
        }
        if injection_mode is not None:
            diagnostic["injection_mode"] = injection_mode
        if reason is not None:
            diagnostic["reason"] = reason
        if memo_chars is not None:
            diagnostic["memo_chars"] = memo_chars
        if request_reasoning is not None:
            diagnostic["request_reasoning_messages"] = request_reasoning.message_count
            diagnostic["request_reasoning_chars"] = request_reasoning.total_chars
            diagnostic["request_reasoning_interleaved_metadata_messages"] = (
                request_reasoning.interleaved_metadata_count
            )
            diagnostic["request_reasoning_tagged_memo_messages"] = (
                request_reasoning.tagged_memo_count
            )
            diagnostic["request_reasoning_first_role"] = request_reasoning.first_role
            diagnostic["request_reasoning_last_role"] = request_reasoning.last_role
            diagnostic["request_reasoning_first_hash"] = request_reasoning.first_hash
            diagnostic["request_reasoning_last_hash"] = request_reasoning.last_hash
            diagnostic["request_reasoning_first_snippet"] = (
                request_reasoning.first_snippet
            )
            diagnostic["request_reasoning_last_snippet"] = (
                request_reasoning.last_snippet
            )
            diagnostic["request_reasoning_interpretation"] = (
                cls._reasoning_interpretation(request_reasoning)
            )
        context.extensions[INTERLEAVED_THINKING_DIAGNOSTIC_KEY] = diagnostic

    @staticmethod
    def _is_main_surface(context: RequestContext | None) -> bool:
        if context is None:
            return True
        raw_surface = context.extensions.get(COMPOSITE_ROUTING_SURFACE_KEY)
        return raw_surface in (None, RoutingSurface.MAIN.value)

    @staticmethod
    def _is_thinker_selected(context: RequestContext | None) -> bool:
        if context is None:
            return False
        return bool(context.extensions.get(COMPOSITE_SELECTED_LEAF_IS_THINKER_KEY))

    @staticmethod
    def _is_memo_injection_suppressed(context: RequestContext | None) -> bool:
        if context is None:
            return False
        return bool(
            context.extensions.get(INTERLEAVED_THINKING_SUPPRESS_MEMO_INJECTION_KEY)
        )

    def _load_instructions(self) -> str:
        if self._cached_instructions is not None:
            return self._cached_instructions

        path_text = self._settings.interleaved_thinking_instructions_file
        if not path_text:
            raise ConfigurationError(
                message=(
                    "A [thinker] branch was selected, but "
                    "backends.interleaved_thinking_instructions_file is not configured."
                ),
                details={"code": "missing_interleaved_thinking_instructions_file"},
            )
        path = Path(path_text)
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConfigurationError(
                message=(
                    "Unable to read interleaved thinking instructions file: "
                    f"{path_text}"
                ),
                details={
                    "code": "invalid_interleaved_thinking_instructions_file",
                    "path": path_text,
                },
            ) from exc
        if not content:
            raise ConfigurationError(
                message="Interleaved thinking instructions file is empty.",
                details={
                    "code": "empty_interleaved_thinking_instructions_file",
                    "path": path_text,
                },
            )
        self._cached_instructions = content
        return content

    @staticmethod
    def _history_without_tool_interactions(
        messages: list[ChatMessage],
    ) -> list[ChatMessage]:
        """Keep the thinker in memo mode instead of continuing a tool loop.

        A thinker request deliberately has no tool definitions, but historical
        assistant tool calls and ``tool`` turns can still prime a model to emit a
        new tool call. Remove those control-flow turns from the internal thinker
        transcript while retaining any textual assistant reasoning.
        """
        filtered: list[ChatMessage] = []
        for message in messages:
            if message.role == "tool" or message.tool_call_id:
                continue
            if message.tool_calls:
                stripped = message.model_copy(update={"tool_calls": None})
                has_content = (
                    isinstance(stripped.content, str) and bool(stripped.content.strip())
                ) or bool(stripped.content)
                has_reasoning = bool(
                    isinstance(stripped.reasoning_content, str)
                    and stripped.reasoning_content.strip()
                )
                if not has_content and not has_reasoning:
                    continue
                filtered.append(stripped)
                continue
            filtered.append(message)
        return filtered

    @staticmethod
    def _get_stored_memo(session: ISession | None) -> str | None:
        if session is None:
            return None
        raw_state = InterleavedThinkingRequestTransformer._get_interleaved_state(
            session
        )
        if not isinstance(raw_state, dict):
            return None
        memo = raw_state.get("memo")
        if isinstance(memo, str) and memo.strip():
            return memo.strip()
        return None

    @staticmethod
    def _stored_memo_was_visible_to_client(session: ISession | None) -> bool:
        if session is None:
            return False
        raw_state = InterleavedThinkingRequestTransformer._get_interleaved_state(
            session
        )
        return bool(
            raw_state.get("visible_to_client", False)
            if isinstance(raw_state, dict)
            else False
        )

    @staticmethod
    def _request_contains_visible_memo(
        request: CanonicalChatRequest,
        memo: str,
    ) -> bool:
        normalized_memo = InterleavedThinkingRequestTransformer._normalize_text(memo)
        if not normalized_memo:
            return False
        for message in request.messages:
            content_text = InterleavedThinkingRequestTransformer._message_content_text(
                message.content
            )
            reasoning_text = getattr(message, "reasoning_content", None)
            candidates = [content_text]
            if isinstance(reasoning_text, str):
                candidates.append(reasoning_text)
            for candidate in candidates:
                if (
                    normalized_memo
                    in InterleavedThinkingRequestTransformer._normalize_text(candidate)
                ):
                    return True
        return False

    @staticmethod
    def _message_content_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts)
        return ""

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split())

    @staticmethod
    def _increment_injected_count(session: ISession | None) -> None:
        def update_state(state: dict[str, Any]) -> dict[str, Any]:
            current = state.get("injected_count", 0)
            injected_count = current if isinstance(current, int) else 0
            raw_regular_turns = state.get("regular_turns_remaining", 0)
            regular_turns_remaining = (
                raw_regular_turns if isinstance(raw_regular_turns, int) else 0
            )
            state["injected_count"] = injected_count + 1
            if regular_turns_remaining > 0:
                state["regular_turns_remaining"] = regular_turns_remaining - 1
            return state

        InterleavedThinkingRequestTransformer._update_interleaved_state(
            session,
            update_state,
        )

    @staticmethod
    def _consume_regular_turn(session: ISession | None) -> None:
        def update_state(state: dict[str, Any]) -> dict[str, Any] | None:
            raw_regular_turns = state.get("regular_turns_remaining", 0)
            regular_turns_remaining = (
                raw_regular_turns if isinstance(raw_regular_turns, int) else 0
            )
            if regular_turns_remaining <= 0:
                return None
            state["regular_turns_remaining"] = regular_turns_remaining - 1
            return state

        InterleavedThinkingRequestTransformer._update_interleaved_state(
            session,
            update_state,
        )

    @staticmethod
    def _update_interleaved_state(
        session: ISession | None,
        update_state: Callable[[dict[str, Any]], dict[str, Any] | None],
    ) -> None:
        if session is None:
            return
        base_state = as_session_state(getattr(session, "state", None))
        if base_state is None:
            return
        raw_state = base_state.interleaved_thinking_state
        if not isinstance(raw_state, dict):
            return
        updated_state = update_state(dict(raw_state))
        if updated_state is None:
            return
        session.update_state(
            cast(Any, base_state.with_interleaved_thinking_state(updated_state))
        )

    @staticmethod
    def _request_reasoning_content_stats(
        request: CanonicalChatRequest,
    ) -> _ReasoningContentStats:
        messages: list[tuple[ChatMessage, str]] = []
        total_chars = 0
        interleaved_metadata_count = 0
        tagged_memo_count = 0
        for message in request.messages:
            reasoning_content = getattr(message, "reasoning_content", None)
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                stripped = reasoning_content.strip()
                messages.append((message, stripped))
                total_chars += len(stripped)
                if InterleavedThinkingRequestTransformer._message_has_interleaved_metadata(
                    message
                ):
                    interleaved_metadata_count += 1
                if _THINKER_MEMO_MARKER in stripped.lower():
                    tagged_memo_count += 1
        if not messages:
            return _ReasoningContentStats()

        first_message, first_text = messages[0]
        last_message, last_text = messages[-1]
        return _ReasoningContentStats(
            message_count=len(messages),
            total_chars=total_chars,
            interleaved_metadata_count=interleaved_metadata_count,
            tagged_memo_count=tagged_memo_count,
            first_role=first_message.role,
            last_role=last_message.role,
            first_hash=InterleavedThinkingRequestTransformer._text_hash(first_text),
            last_hash=InterleavedThinkingRequestTransformer._text_hash(last_text),
            first_snippet=InterleavedThinkingRequestTransformer._snippet(first_text),
            last_snippet=InterleavedThinkingRequestTransformer._snippet(last_text),
        )

    @staticmethod
    def _message_has_interleaved_metadata(message: ChatMessage) -> bool:
        metadata = message.metadata
        if not isinstance(metadata, dict):
            return False
        return metadata.get("source") == "interleaved_thinking" or str(
            metadata.get("kind", "")
        ).startswith("thinker_memo")

    @staticmethod
    def _text_hash(text: str) -> str:
        return sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]

    @staticmethod
    def _snippet(text: str, *, limit: int = 180) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            snippet = normalized
        else:
            snippet = f"{normalized[:limit]}..."
        return snippet.encode("ascii", errors="backslashreplace").decode("ascii")

    @staticmethod
    def _reasoning_interpretation(stats: _ReasoningContentStats) -> str:
        if stats.message_count <= 0:
            return "no_reasoning_content"
        if stats.interleaved_metadata_count:
            return "proxy_injected_interleaved_thinking_memo"
        if stats.tagged_memo_count:
            return "tagged_proxy_thinker_memo_in_request"
        return "preexisting_or_client_carried_reasoning_content"

    @staticmethod
    def _get_interleaved_state(session: ISession | None) -> dict[str, Any] | None:
        if session is None:
            return None
        base_state = as_session_state(getattr(session, "state", None))
        if base_state is None:
            return None
        raw_state = base_state.interleaved_thinking_state
        return raw_state if isinstance(raw_state, dict) else None

    @staticmethod
    def _inject_memo_at_tail(
        messages: list[ChatMessage],
        memo: str,
    ) -> list[ChatMessage]:
        """Append steering as an isolated synthetic user turn.

        Do not attach the memo to the final tool result or user message. Tool output
        is untrusted data, and placing proxy steering inside it makes the executor
        model interpret the steering as an instruction embedded in tool output. A
        separate user turn is supported by the lowest common denominator of chat
        backends, while the metadata remains proxy-local because ``ChatMessage.to_dict``
        deliberately excludes it from provider payloads.
        """
        return [
            *messages,
            ChatMessage(
                role="user",
                content=f"{_DEFAULT_STEERING_INJECTION_HEADER}\n{memo}",
                metadata={
                    "source": "interleaved_thinking",
                    "kind": _SYNTHETIC_MEMO_MESSAGE_KIND,
                    "non_forwardable": True,
                },
            ),
        ]
