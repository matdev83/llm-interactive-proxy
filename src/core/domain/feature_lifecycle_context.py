"""Typed lifecycle context for response-processing features (Wave 4).

Provides a canonical dataclass for terminal state, finish reason, and request
metadata, plus a bridge from legacy ``dict[str, object]`` contexts so features
can migrate incrementally without breaking callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Key used inside legacy middleware / feature context dicts.
FEATURE_LIFECYCLE_CONTEXT_KEY: str = "feature_lifecycle"

_TERMINAL_FINISH_REASONS = frozenset(
    {
        "stop",
        "length",
        "error",
        "tool_calls",
        "cancelled",
        "user_cancelled",
        "system_cancelled",
        "content_filter",
        "security_limit",
    }
)


@dataclass(frozen=True, slots=True)
class FeatureLifecycleContext:
    """Canonical lifecycle snapshot for a single feature invocation.

    Attributes:
        is_streaming: True when the feature is invoked on a streaming chunk path.
        is_terminal_chunk: True when this chunk/response represents a terminal
            completion boundary for the current mode (non-streaming is always True).
        finish_reason: Provider finish reason when known (e.g. OpenAI ``stop``).
        session_id: Session identifier for the request.
        stream_id: Stream identifier when streaming; None for non-streaming.
        request_id: Optional request correlation id when present in context/metadata.
        backend_name: Optional backend id from request propagation.
        model_name: Optional effective model name from request propagation.
        non_streaming_single_chunk: True when the unified pipeline wrapped a
            complete response as a single streaming chunk (``non_streaming`` flag).
    """

    is_streaming: bool
    is_terminal_chunk: bool
    finish_reason: str | None
    session_id: str
    stream_id: str | None
    request_id: str | None
    backend_name: str | None
    model_name: str | None
    non_streaming_single_chunk: bool


def _str_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _finish_reason_from_openai_style_dict(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    fr = first.get("finish_reason")
    if isinstance(fr, str) and fr.strip():
        return fr
    delta = first.get("delta")
    if isinstance(delta, dict):
        dfr = delta.get("finish_reason")
        if isinstance(dfr, str) and dfr.strip():
            return dfr
    return None


def _metadata_from_chunk(chunk: Any) -> dict[str, Any]:
    if chunk is None:
        return {}
    meta = getattr(chunk, "metadata", None)
    if isinstance(meta, dict):
        return meta
    if isinstance(chunk, dict):
        return chunk
    return {}


def _resolve_finish_reason(chunk: Any, meta: Mapping[str, Any]) -> str | None:
    direct = meta.get("finish_reason")
    if isinstance(direct, str) and direct.strip():
        return direct
    content = getattr(chunk, "content", None)
    if isinstance(content, dict):
        found = _finish_reason_from_openai_style_dict(content)
        if found:
            return found
    if isinstance(chunk, dict):
        return _finish_reason_from_openai_style_dict(chunk)
    return None


def _terminal_from_finish_reason(fr: str | None) -> bool:
    if not isinstance(fr, str):
        return False
    return fr.strip().lower() in _TERMINAL_FINISH_REASONS


def _terminal_chunk(
    *,
    is_streaming: bool,
    meta: Mapping[str, Any],
    finish_reason: str | None,
    non_streaming_single_chunk: bool,
) -> bool:
    if not is_streaming:
        return True
    if non_streaming_single_chunk:
        return True
    if bool(meta.get("is_done")):
        return True
    return bool(_terminal_from_finish_reason(finish_reason))


def build_feature_lifecycle_context_from_streaming_content(
    *,
    content: Any,
    response_type: str,
    session_id: str,
    stream_id: str | None,
) -> FeatureLifecycleContext:
    """Build lifecycle context from a ``StreamingContent`` chunk (stream processor)."""
    meta_raw = getattr(content, "metadata", None)
    meta: dict[str, Any] = dict(meta_raw) if isinstance(meta_raw, dict) else {}

    non_single = bool(meta.get("non_streaming")) or response_type == "non_streaming"
    is_streaming = not non_single
    finish_reason = _resolve_finish_reason(content, meta)

    is_done_attr = bool(getattr(content, "is_done", False))
    is_cancellation = bool(getattr(content, "is_cancellation", False))
    is_terminal = (
        (not is_streaming)
        or non_single
        or is_done_attr
        or is_cancellation
        or _terminal_from_finish_reason(finish_reason)
    )

    return FeatureLifecycleContext(
        is_streaming=is_streaming,
        is_terminal_chunk=is_terminal,
        finish_reason=finish_reason,
        session_id=session_id,
        stream_id=stream_id,
        request_id=_str_or_none(meta.get("request_id")),
        backend_name=_str_or_none(meta.get("backend_name")),
        model_name=_str_or_none(meta.get("model_name")),
        non_streaming_single_chunk=non_single,
    )


def build_feature_lifecycle_context_from_manager_chunk(
    *,
    chunk: Any,
    is_streaming: bool,
    session_id: str,
    base_context: Mapping[str, Any],
) -> FeatureLifecycleContext:
    """Build lifecycle context inside ``MiddlewareApplicationManager`` loops."""
    meta = _metadata_from_chunk(chunk)
    non_single = bool(base_context.get("non_streaming"))
    finish_reason = _resolve_finish_reason(chunk, meta)
    if finish_reason is None:
        finish_reason = _str_or_none(base_context.get("finish_reason"))

    is_terminal = _terminal_chunk(
        is_streaming=is_streaming,
        meta=meta,
        finish_reason=finish_reason,
        non_streaming_single_chunk=non_single,
    )

    stream_id = base_context.get("stream_id")
    stream_id_str = stream_id if isinstance(stream_id, str) else None

    return FeatureLifecycleContext(
        is_streaming=is_streaming,
        is_terminal_chunk=is_terminal,
        finish_reason=finish_reason,
        session_id=session_id,
        stream_id=stream_id_str,
        request_id=_str_or_none(
            base_context.get("request_id") or meta.get("request_id")
        ),
        backend_name=_str_or_none(
            base_context.get("backend_name") or meta.get("backend_name")
        ),
        model_name=_str_or_none(
            base_context.get("model_name") or meta.get("model_name")
        ),
        non_streaming_single_chunk=non_single,
    )


def feature_lifecycle_context_from_dict(
    context: Mapping[str, Any] | None,
    *,
    is_streaming: bool | None = None,
    session_id_fallback: str = "",
) -> FeatureLifecycleContext:
    """Compatibility bridge: typed view from a legacy context dict.

    If ``FEATURE_LIFECYCLE_CONTEXT_KEY`` is present and is a
    ``FeatureLifecycleContext``, it is returned (caller should still pass a
    fully-populated dict from producers).

    Otherwise a best-effort snapshot is synthesized from known keys so older
    callers remain supported.
    """
    ctx = dict(context or {})
    embedded = ctx.get(FEATURE_LIFECYCLE_CONTEXT_KEY)
    if isinstance(embedded, FeatureLifecycleContext):
        return embedded

    response_type = str(ctx.get("response_type") or "")
    resolved_streaming = is_streaming
    if resolved_streaming is None:
        resolved_streaming = response_type in ("stream", "streaming")

    session_raw = ctx.get("session_id") or session_id_fallback
    session = str(session_raw) if session_raw is not None else ""

    finish_reason = _str_or_none(ctx.get("finish_reason"))
    stream_raw = ctx.get("stream_id")
    stream_id = stream_raw if isinstance(stream_raw, str) else None

    non_single = bool(ctx.get("non_streaming"))
    is_terminal = _terminal_chunk(
        is_streaming=bool(resolved_streaming),
        meta=ctx,
        finish_reason=finish_reason,
        non_streaming_single_chunk=non_single,
    )

    return FeatureLifecycleContext(
        is_streaming=bool(resolved_streaming),
        is_terminal_chunk=is_terminal,
        finish_reason=finish_reason,
        session_id=session,
        stream_id=stream_id,
        request_id=_str_or_none(ctx.get("request_id")),
        backend_name=_str_or_none(ctx.get("backend_name")),
        model_name=_str_or_none(ctx.get("model_name")),
        non_streaming_single_chunk=non_single,
    )


def attach_feature_lifecycle_context(
    context: dict[str, Any],
    lifecycle: FeatureLifecycleContext,
) -> dict[str, Any]:
    """Attach typed lifecycle to a mutable context dict (in-place)."""
    context[FEATURE_LIFECYCLE_CONTEXT_KEY] = lifecycle
    return context
