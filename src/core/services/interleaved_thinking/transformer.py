from __future__ import annotations

import logging
from collections.abc import Callable
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
_DEFAULT_SYSTEM_INJECTION_PREFIX = (
    "The proxy captured this thinker memo for the next executor model. "
    "Use it as planning context, but obey the user's latest request."
)


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
            messages = [
                ChatMessage(
                    role="system",
                    content=instructions,
                    metadata={
                        "source": "interleaved_thinking",
                        "kind": "thinker_instructions",
                    },
                ),
                *request.messages,
            ]
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
                "messages_before=%d messages_after=%d tools_present=%s",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
                len(instructions),
                len(request.messages),
                len(messages),
                bool(request.tools),
            )
            return request.model_copy(update={"messages": messages})

        reasoning_message_count, reasoning_chars = (
            self._request_reasoning_content_stats(request)
        )
        memo = self._get_stored_memo(session)
        if not memo:
            self._record_diagnostic(
                context,
                action="memo_injection_skipped",
                reason="no_stored_memo",
                target=target,
                request_reasoning_messages=reasoning_message_count,
                request_reasoning_chars=reasoning_chars,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            if reasoning_message_count:
                logger.info(
                    "Interleaved thinking memo injection skipped: no stored proxy memo, "
                    "but request already carries reasoning_content "
                    "request_id=%s session_id=%s backend=%s model=%s "
                    "reasoning_messages=%d reasoning_chars=%d",
                    request_id(context),
                    session_id(context, session),
                    target.backend,
                    target.model,
                    reasoning_message_count,
                    reasoning_chars,
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

        if reasoning_message_count:
            self._record_diagnostic(
                context,
                action="memo_injection_skipped",
                reason="request_already_has_reasoning_content",
                target=target,
                memo_chars=len(memo),
                request_reasoning_messages=reasoning_message_count,
                request_reasoning_chars=reasoning_chars,
                message_count_before=len(request.messages),
                message_count_after=len(request.messages),
            )
            logger.info(
                "Interleaved thinking memo injection skipped: request already carries "
                "reasoning_content request_id=%s session_id=%s backend=%s model=%s "
                "memo_chars=%d reasoning_messages=%d reasoning_chars=%d",
                request_id(context),
                session_id(context, session),
                target.backend,
                target.model,
                len(memo),
                reasoning_message_count,
                reasoning_chars,
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
                request_reasoning_messages=reasoning_message_count,
                request_reasoning_chars=reasoning_chars,
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

        system_message = ChatMessage(
            role="system",
            content=f"{_DEFAULT_SYSTEM_INJECTION_PREFIX}\n\n{memo}",
            metadata={
                "source": "interleaved_thinking",
                "kind": "thinker_memo_system",
            },
        )
        reasoning_message = ChatMessage(
            role="assistant",
            content="",
            reasoning_content=memo,
            metadata={
                "source": "interleaved_thinking",
                "kind": "thinker_memo_reasoning",
            },
        )
        messages = list(request.messages)
        insert_at = self._last_user_message_index(messages)
        if insert_at is None:
            messages = [system_message, reasoning_message, *messages]
        else:
            messages.insert(insert_at, reasoning_message)
            messages.insert(0, system_message)
        self._increment_injected_count(session)
        self._record_diagnostic(
            context,
            action="memo_injected",
            target=target,
            memo_chars=len(memo),
            message_count_before=len(request.messages),
            message_count_after=len(messages),
        )
        logger.info(
            "Interleaved thinking memo injected: request_id=%s session_id=%s "
            "backend=%s model=%s memo_chars=%d messages_before=%d "
            "messages_after=%d insert_before_last_user=%s tools_present=%s",
            request_id(context),
            session_id(context, session),
            target.backend,
            target.model,
            len(memo),
            len(request.messages),
            len(messages),
            insert_at is not None,
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
        request_reasoning_messages: int | None = None,
        request_reasoning_chars: int | None = None,
        message_count_before: int,
        message_count_after: int,
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
        if reason is not None:
            diagnostic["reason"] = reason
        if memo_chars is not None:
            diagnostic["memo_chars"] = memo_chars
        if request_reasoning_messages is not None:
            diagnostic["request_reasoning_messages"] = request_reasoning_messages
        if request_reasoning_chars is not None:
            diagnostic["request_reasoning_chars"] = request_reasoning_chars
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
    ) -> tuple[int, int]:
        count = 0
        total_chars = 0
        for message in request.messages:
            reasoning_content = getattr(message, "reasoning_content", None)
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                count += 1
                total_chars += len(reasoning_content.strip())
        return count, total_chars

    @staticmethod
    def _get_interleaved_state(session: ISession) -> dict[str, Any] | None:
        base_state = as_session_state(getattr(session, "state", None))
        if base_state is None:
            return None
        raw_state = base_state.interleaved_thinking_state
        return raw_state if isinstance(raw_state, dict) else None

    @staticmethod
    def _last_user_message_index(messages: list[ChatMessage]) -> int | None:
        for index in range(len(messages) - 1, -1, -1):
            if messages[index].role == "user":
                return index
        return None
