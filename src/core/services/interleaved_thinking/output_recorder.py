from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from src.core.domain.request_context import RequestContext
from src.core.domain.responses import ResponseEnvelope, StreamingResponseEnvelope
from src.core.interfaces.domain_entities_interface import ISession
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.services.composite_routing_state import (
    COMPOSITE_SELECTED_LEAF_SELECTOR_KEY,
)
from src.core.services.interleaved_thinking.state_utils import (
    as_session_state,
    request_id,
    session_id,
)

logger = logging.getLogger(__name__)

INTERLEAVED_THINKING_RECORDER_DIAGNOSTIC_KEY = (
    "interleaved_thinking_recorder_diagnostic"
)


@dataclass(frozen=True)
class _ExtractedMemo:
    text: str
    source: str


class InterleavedThinkingOutputRecorder:
    """Capture thinker output into the current session state."""

    def __init__(self, *, max_output_chars: int = 8000) -> None:
        self._max_output_chars = max(1, max_output_chars)

    def capture_non_streaming(
        self,
        *,
        response: ResponseEnvelope,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
        effective_model: str,
    ) -> None:
        extracted = self._extract_from_content(response.content)
        if extracted is None:
            self._store_memo(
                memo=None,
                session=session,
                context=context,
                backend_type=backend_type,
                effective_model=effective_model,
                empty_reason="no_extractable_memo",
            )
            return
        self._store_memo(
            memo=extracted.text,
            session=session,
            context=context,
            backend_type=backend_type,
            effective_model=effective_model,
            extraction_source=extracted.source,
        )

    def wrap_streaming(
        self,
        *,
        response: StreamingResponseEnvelope,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
        effective_model: str,
    ) -> StreamingResponseEnvelope:
        if response.content is None:
            return response

        source = response.content

        async def _wrapped() -> AsyncIterator[ProcessedResponse]:
            parts: list[str] = []
            extraction_source: str | None = None
            try:
                async for item in source:
                    extracted = self._extract_from_content(item.content)
                    if extracted is not None:
                        parts.append(extracted.text)
                        extraction_source = extraction_source or extracted.source
                    yield item
            except (GeneratorExit, asyncio.CancelledError):
                partial_memo_chars = len("".join(parts))
                self._record_diagnostic(
                    context,
                    action="memo_store_skipped",
                    reason="stream_interrupted",
                    backend_type=backend_type,
                    effective_model=effective_model,
                    partial_memo_chars=partial_memo_chars,
                    extraction_source=extraction_source,
                )
                if logger.isEnabledFor(logging.DEBUG):
                    logger.debug(
                        "Interleaved thinking memo store skipped: stream interrupted "
                        "request_id=%s session_id=%s backend=%s model=%s "
                        "partial_memo_chars=%d",
                        request_id(context),
                        session_id(context, session),
                        backend_type,
                        effective_model,
                        partial_memo_chars,
                    )
                raise
            except BaseException:
                partial_memo_chars = len("".join(parts))
                self._record_diagnostic(
                    context,
                    action="memo_store_skipped",
                    reason="stream_interrupted",
                    backend_type=backend_type,
                    effective_model=effective_model,
                    partial_memo_chars=partial_memo_chars,
                    extraction_source=extraction_source,
                )
                logger.warning(
                    "Interleaved thinking memo store skipped: stream interrupted "
                    "request_id=%s session_id=%s backend=%s model=%s "
                    "partial_memo_chars=%d",
                    request_id(context),
                    session_id(context, session),
                    backend_type,
                    effective_model,
                    partial_memo_chars,
                    exc_info=True,
                )
                raise
            self._store_memo(
                memo="".join(parts),
                session=session,
                context=context,
                backend_type=backend_type,
                effective_model=effective_model,
                extraction_source=extraction_source,
                empty_reason=(
                    "empty_memo"
                    if extraction_source is not None
                    else "no_extractable_memo"
                ),
            )

        response.content = _wrapped()
        return response

    def _store_memo(
        self,
        *,
        memo: str | None,
        session: ISession | None,
        context: RequestContext | None,
        backend_type: str,
        effective_model: str,
        extraction_source: str | None = None,
        empty_reason: str = "empty_memo",
    ) -> None:
        if session is None:
            self._record_diagnostic(
                context,
                action="memo_store_skipped",
                reason="missing_session",
                backend_type=backend_type,
                effective_model=effective_model,
                extraction_source=extraction_source,
            )
            logger.info(
                "Interleaved thinking memo store skipped: missing session "
                "request_id=%s backend=%s model=%s",
                request_id(context),
                backend_type,
                effective_model,
            )
            return
        if not memo or not memo.strip():
            self._record_diagnostic(
                context,
                action="memo_store_skipped",
                reason=empty_reason,
                backend_type=backend_type,
                effective_model=effective_model,
                extraction_source=extraction_source,
            )
            logger.info(
                "Interleaved thinking memo store skipped: %s "
                "request_id=%s session_id=%s backend=%s model=%s "
                "extraction_source=%s",
                empty_reason,
                request_id(context),
                session_id(context, session),
                backend_type,
                effective_model,
                extraction_source,
            )
            return
        normalized_memo = memo.strip()[: self._max_output_chars]
        if not normalized_memo:
            return

        source_selector = None
        stored_request_id = None
        if context is not None:
            raw_selector = context.extensions.get(COMPOSITE_SELECTED_LEAF_SELECTOR_KEY)
            if isinstance(raw_selector, str):
                source_selector = raw_selector
            stored_request_id = context.request_id

        stored = {
            "memo": normalized_memo,
            "source_selector": source_selector,
            "backend": backend_type,
            "model": effective_model,
            "request_id": stored_request_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "injected_count": 0,
            "extraction_source": extraction_source,
        }
        base_state = as_session_state(getattr(session, "state", None))
        if base_state is None:
            self._record_diagnostic(
                context,
                action="memo_store_skipped",
                reason="invalid_session_state",
                backend_type=backend_type,
                effective_model=effective_model,
                memo_chars=len(normalized_memo),
                source_selector=source_selector,
                extraction_source=extraction_source,
            )
            logger.info(
                "Interleaved thinking memo store skipped: invalid session state "
                "request_id=%s session_id=%s backend=%s model=%s memo_chars=%d",
                request_id(context),
                session_id(context, session),
                backend_type,
                effective_model,
                len(normalized_memo),
            )
            return
        session.update_state(
            cast(Any, base_state.with_interleaved_thinking_state(stored))
        )
        self._record_diagnostic(
            context,
            action="memo_stored",
            backend_type=backend_type,
            effective_model=effective_model,
            memo_chars=len(normalized_memo),
            source_selector=source_selector,
            extraction_source=extraction_source,
        )
        logger.info(
            "Interleaved thinking memo stored: request_id=%s session_id=%s "
            "backend=%s model=%s source_selector=%s memo_chars=%d "
            "extraction_source=%s truncated=%s",
            request_id(context),
            session_id(context, session),
            backend_type,
            effective_model,
            source_selector,
            len(normalized_memo),
            extraction_source,
            len(memo.strip()) > self._max_output_chars,
        )

    @staticmethod
    def _record_diagnostic(
        context: RequestContext | None,
        *,
        action: str,
        backend_type: str,
        effective_model: str,
        reason: str | None = None,
        memo_chars: int | None = None,
        partial_memo_chars: int | None = None,
        source_selector: str | None = None,
        extraction_source: str | None = None,
    ) -> None:
        if context is None:
            return
        diagnostic: dict[str, Any] = {
            "action": action,
            "backend": backend_type,
            "model": effective_model,
            "request_id": context.request_id,
            "session_id": context.session_id,
        }
        if reason is not None:
            diagnostic["reason"] = reason
        if memo_chars is not None:
            diagnostic["memo_chars"] = memo_chars
        if partial_memo_chars is not None:
            diagnostic["partial_memo_chars"] = partial_memo_chars
        if source_selector is not None:
            diagnostic["source_selector"] = source_selector
        if extraction_source is not None:
            diagnostic["extraction_source"] = extraction_source
        context.extensions[INTERLEAVED_THINKING_RECORDER_DIAGNOSTIC_KEY] = diagnostic

    def _extract_from_content(self, content: Any) -> _ExtractedMemo | None:
        if isinstance(content, dict):
            choice = self._first_choice(content)
            if choice is not None:
                for container_key in ("message", "delta"):
                    container = choice.get(container_key)
                    if isinstance(container, dict):
                        extracted = self._extract_text_fields(container)
                        if extracted is not None:
                            return extracted
            extracted = self._extract_text_fields(content)
            if extracted is not None:
                return extracted
        if isinstance(content, str):
            return _ExtractedMemo(content, "raw_string")
        if isinstance(content, bytes):
            return _ExtractedMemo(
                content.decode("utf-8", errors="replace"), "raw_bytes"
            )
        return None

    @staticmethod
    def _first_choice(content: dict[str, Any]) -> dict[str, Any] | None:
        choices = content.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        return first if isinstance(first, dict) else None

    @staticmethod
    def _extract_text_fields(container: dict[str, Any]) -> _ExtractedMemo | None:
        for key in ("reasoning_content", "reasoning", "content"):
            value = container.get(key)
            if isinstance(value, str):
                return _ExtractedMemo(value, key)
        return None
