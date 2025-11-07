from __future__ import annotations

from src.core.ports.streaming import StreamingContent
from src.core.services.streaming.stream_utils import get_stream_id


def _build_chunk(
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    stream_id: str | None = None,
    is_done: bool = False,
) -> StreamingContent:
    metadata: dict[str, str] = {}
    if session_id is not None:
        metadata["session_id"] = session_id
    if request_id is not None:
        metadata["request_id"] = request_id
    if stream_id is not None:
        metadata["stream_id"] = stream_id
    return StreamingContent(content="", is_done=is_done, metadata=metadata)


def test_get_stream_id_prefers_request_over_session() -> None:
    """Distinct request identifiers must yield isolated stream identifiers."""

    first_chunk = _build_chunk(session_id="session-1", request_id="req-a")
    second_chunk = _build_chunk(session_id="session-1", request_id="req-b")

    first_stream_id = get_stream_id(first_chunk)
    second_stream_id = get_stream_id(second_chunk)

    assert first_stream_id != second_stream_id

    # Subsequent chunks for the same request must reuse the original identifier.
    repeat_chunk = _build_chunk(session_id="session-1", request_id="req-a")
    assert get_stream_id(repeat_chunk) == first_stream_id


def test_get_stream_id_releases_mapping_on_completion() -> None:
    """Completing a stream should allow a fresh identifier for fallback lookups."""

    chunk = _build_chunk(session_id="session-42")
    original_stream_id = get_stream_id(chunk)

    completion = _build_chunk(
        session_id="session-42",
        stream_id=original_stream_id,
        is_done=True,
    )
    # Calling get_stream_id on the completion chunk should clean up state.
    assert get_stream_id(completion) == original_stream_id

    new_chunk = _build_chunk(session_id="session-42")
    refreshed_stream_id = get_stream_id(new_chunk)

    assert refreshed_stream_id != original_stream_id
