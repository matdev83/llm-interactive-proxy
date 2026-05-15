from __future__ import annotations

import asyncio
import copy
import json
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
_THINKER_OPEN_TAG_PREFIX = "<proxy_thinker_memo"
_THINKER_CLOSE_TAG_PREFIX = "</proxy_thinker_memo"
_THINKER_TAG_PREFIXES = (_THINKER_OPEN_TAG_PREFIX, _THINKER_CLOSE_TAG_PREFIX)


@dataclass(frozen=True)
class _ExtractedMemo:
    text: str
    source: str


class _ProxyThinkerMemoTagStripper:
    def __init__(self) -> None:
        self._pending = ""

    def feed(self, text: str) -> str:
        combined = f"{self._pending}{text}"
        self._pending = ""
        sanitized, pending = self._strip_tags(combined, hold_incomplete=True)
        self._pending = pending
        return sanitized

    def flush(self) -> str:
        if not self._pending:
            return ""
        pending = self._pending
        self._pending = ""
        if pending == "<":
            return pending
        lowered_pending = pending.lower()
        if self._partial_tag_prefix(lowered_pending) or self._matching_tag_prefix(
            lowered_pending, 0
        ):
            return ""
        sanitized, _pending = self._strip_tags(pending, hold_incomplete=False)
        return sanitized

    @classmethod
    def strip_complete(cls, text: str) -> str:
        sanitized, _pending = cls._strip_tags(text, hold_incomplete=False)
        return sanitized

    @classmethod
    def _strip_tags(cls, text: str, *, hold_incomplete: bool) -> tuple[str, str]:
        lowered = text.lower()
        output: list[str] = []
        index = 0
        while index < len(text):
            if text[index] != "<":
                output.append(text[index])
                index += 1
                continue

            prefix = cls._matching_tag_prefix(lowered, index)
            if prefix is None:
                partial_prefix = cls._partial_tag_prefix(lowered[index:])
                if partial_prefix and hold_incomplete:
                    return "".join(output), text[index:]
                output.append(text[index])
                index += 1
                continue

            boundary_index = index + len(prefix)
            if boundary_index < len(text) and not cls._is_tag_name_boundary(
                text[boundary_index]
            ):
                output.append(text[index])
                index += 1
                continue

            tag_end = cls._find_tag_end(text, boundary_index)
            if tag_end is None:
                if hold_incomplete:
                    return "".join(output), text[index:]
                return "".join(output), ""
            index = tag_end + 1

        return "".join(output), ""

    @staticmethod
    def _matching_tag_prefix(lowered: str, index: int) -> str | None:
        for prefix in _THINKER_TAG_PREFIXES:
            if lowered.startswith(prefix, index):
                return prefix
        return None

    @staticmethod
    def _partial_tag_prefix(suffix: str) -> bool:
        return any(prefix.startswith(suffix) for prefix in _THINKER_TAG_PREFIXES)

    @staticmethod
    def _is_tag_name_boundary(char: str) -> bool:
        return char.isspace() or char in {">", "/"}

    @staticmethod
    def _find_tag_end(text: str, start: int) -> int | None:
        quote: str | None = None
        for index in range(start, len(text)):
            char = text[index]
            if quote is not None:
                if char == quote:
                    quote = None
                continue
            if char in {"'", '"'}:
                quote = char
                continue
            if char == ">":
                return index
        return None


class InterleavedThinkingOutputRecorder:
    """Capture thinker output into the current session state."""

    def __init__(
        self,
        *,
        max_output_chars: int = 8000,
        stream_to_client: bool = False,
        regular_turns_remaining: int = 2,
    ) -> None:
        self._max_output_chars = max(1, max_output_chars)
        self._stream_to_client = stream_to_client
        self._regular_turns_remaining = max(0, regular_turns_remaining)

    @property
    def stream_to_client(self) -> bool:
        return self._stream_to_client

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
                visible_to_client=self._stream_to_client,
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
        visible_to_client: bool = False,
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
        normalized_memo = self._normalize_memo_text(memo)[: self._max_output_chars]
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
            "regular_turns_remaining": self._regular_turns_remaining,
            "visible_to_client": visible_to_client,
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
            "extraction_source=%s visible_to_client=%s truncated=%s",
            request_id(context),
            session_id(context, session),
            backend_type,
            effective_model,
            source_selector,
            len(normalized_memo),
            extraction_source,
            visible_to_client,
            len(memo.strip()) > self._max_output_chars,
        )

    async def sanitize_visible_stream(
        self,
        source: AsyncIterator[ProcessedResponse],
    ) -> AsyncIterator[ProcessedResponse]:
        tag_stripper = _ProxyThinkerMemoTagStripper()
        async for item in source:
            sanitized = self._sanitize_visible_item(item, tag_stripper)
            if sanitized is not None:
                yield sanitized
        tail = tag_stripper.flush()
        if tail:
            yield ProcessedResponse(content=tail)

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
    def _normalize_memo_text(memo: str) -> str:
        return _ProxyThinkerMemoTagStripper.strip_complete(memo).strip()

    @classmethod
    def _sanitize_visible_item(
        cls,
        item: ProcessedResponse,
        tag_stripper: _ProxyThinkerMemoTagStripper,
    ) -> ProcessedResponse | None:
        content = item.content
        if isinstance(content, dict):
            sanitized_dict = cls._sanitize_visible_dict(content, tag_stripper)
            if sanitized_dict is None:
                return None
            return ProcessedResponse(
                content=sanitized_dict,
                usage=item.usage,
                metadata=dict(item.metadata),
            )
        if isinstance(content, bytes):
            return cls._sanitize_visible_text_like_item(
                content.decode("utf-8", errors="replace"),
                item,
                tag_stripper,
            )
        if isinstance(content, str):
            return cls._sanitize_visible_text_like_item(content, item, tag_stripper)
        return None

    @classmethod
    def _sanitize_visible_text_like_item(
        cls,
        text: str,
        item: ProcessedResponse,
        tag_stripper: _ProxyThinkerMemoTagStripper,
    ) -> ProcessedResponse | None:
        stripped = text.strip()
        if stripped.startswith("data:"):
            data = stripped[5:].strip()
            if data == "[DONE]":
                return None
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(parsed, dict):
                    sanitized = cls._sanitize_visible_dict(parsed, tag_stripper)
                    if sanitized is None:
                        return None
                    return ProcessedResponse(
                        content=sanitized,
                        usage=item.usage,
                        metadata=dict(item.metadata),
                    )

        sanitized_text = tag_stripper.feed(text)
        if not sanitized_text:
            return None
        return ProcessedResponse(
            content=sanitized_text,
            usage=item.usage,
            metadata=dict(item.metadata),
        )

    @classmethod
    def _sanitize_visible_dict(
        cls,
        content: dict[str, Any],
        tag_stripper: _ProxyThinkerMemoTagStripper,
    ) -> dict[str, Any] | None:
        sanitized = copy.deepcopy(content)
        emitted_text = False
        choices = sanitized.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                for container_key in ("delta", "message"):
                    container = choice.get(container_key)
                    if not isinstance(container, dict):
                        continue
                    emitted_text = (
                        cls._sanitize_visible_message_container(
                            container,
                            tag_stripper,
                        )
                        or emitted_text
                    )
            if emitted_text:
                cls._strip_tagged_strings_in_place(sanitized)
                return sanitized
            return None

        for key in ("delta", "text", "content", "message", "data"):
            value = sanitized.get(key)
            if isinstance(value, str):
                sanitized_value = tag_stripper.feed(value)
                if sanitized_value:
                    sanitized[key] = sanitized_value
                    cls._strip_tagged_strings_in_place(sanitized)
                    return sanitized
                return None
            if isinstance(value, dict):
                nested = cls._sanitize_visible_dict(value, tag_stripper)
                if nested is not None:
                    sanitized[key] = nested
                    cls._strip_tagged_strings_in_place(sanitized)
                    return sanitized

        cls._strip_tagged_strings_in_place(sanitized)
        return sanitized

    @classmethod
    def _strip_tagged_strings_in_place(cls, value: Any) -> bool:
        found_tagged_text = False
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if isinstance(item, str):
                    if cls._contains_proxy_thinker_tag(item):
                        value[key] = _ProxyThinkerMemoTagStripper.strip_complete(item)
                        found_tagged_text = True
                    continue
                if isinstance(item, dict | list):
                    found_tagged_text = (
                        cls._strip_tagged_strings_in_place(item) or found_tagged_text
                    )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    if cls._contains_proxy_thinker_tag(item):
                        value[index] = _ProxyThinkerMemoTagStripper.strip_complete(item)
                        found_tagged_text = True
                    continue
                if isinstance(item, dict | list):
                    found_tagged_text = (
                        cls._strip_tagged_strings_in_place(item) or found_tagged_text
                    )
        return found_tagged_text

    @staticmethod
    def _contains_proxy_thinker_tag(text: str) -> bool:
        lowered = text.lower()
        return any(prefix in lowered for prefix in _THINKER_TAG_PREFIXES)

    @staticmethod
    def _sanitize_visible_message_container(
        container: dict[str, Any],
        tag_stripper: _ProxyThinkerMemoTagStripper,
    ) -> bool:
        text = container.get("content")
        if not isinstance(text, str) or not text:
            for key in ("reasoning_content", "reasoning", "thinking", "thought"):
                candidate = container.get(key)
                if isinstance(candidate, str) and candidate:
                    text = candidate
                    break
        if not isinstance(text, str) or not text:
            return False

        sanitized_text = tag_stripper.feed(text)
        for key in ("reasoning_content", "reasoning", "thinking", "thought"):
            container.pop(key, None)
        if not sanitized_text:
            container.pop("content", None)
            return False
        container["content"] = sanitized_text
        return True

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
