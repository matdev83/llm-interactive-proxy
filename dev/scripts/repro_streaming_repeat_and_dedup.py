"""
Reproduction harnesses for critical streaming bugs.

This script provides two small repro/verification tools:

1) from-capture:
   Replays a captured SSE stream through ContentAccumulationProcessor and verifies
   that a terminal done-only marker does NOT re-emit the full accumulated content
   after OpenAI-style deltas were already streamed.

2) dedup-storm:
   Simulates a streaming request that stays in-flight while a client retries the
   same request. Verifies that request deduplication blocks parallel duplicates,
   and that completion is only marked when the stream is terminated.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, cast

# Add project root to sys.path (dev scripts are typically run as files, not modules).
sys.path.append(os.getcwd())

from src.core.common.exceptions import DuplicateRequestError
from src.core.domain.cbor_capture import CaptureDirection
from src.core.domain.chat import ChatMessage, ChatRequest
from src.core.domain.request_context import RequestContext
from src.core.domain.responses import StreamingResponseEnvelope
from src.core.interfaces.backend_processor_interface import IBackendProcessor
from src.core.interfaces.backend_request_manager_components import (
    IBackendRequestPreparation,
)
from src.core.interfaces.quality_verifier_service_interface import (
    IQualityVerifierServiceFactory,
)
from src.core.interfaces.response_processor_interface import (
    IResponseProcessor,
    ProcessedResponse,
)
from src.core.services.backend_request_manager_service import BackendRequestManager
from src.core.services.post_backend_response_coordinator import (
    PostBackendResponseCoordinator,
)
from src.core.services.request_deduplication_service import RequestDeduplicationService
from src.core.services.streaming.content_accumulation_processor import (
    ContentAccumulationProcessor,
)
from src.core.services.streaming.stream_context_registry import StreamingContextRegistry
from src.core.transport.fastapi.adapters.sse.decoder import SSEDecoder


def _parse_direction(raw: str) -> CaptureDirection:
    value = raw.strip().lower()
    mapping = {
        "client_to_proxy": CaptureDirection.CLIENT_TO_PROXY,
        "proxy_to_client": CaptureDirection.PROXY_TO_CLIENT,
        "proxy_to_backend": CaptureDirection.PROXY_TO_BACKEND,
        "backend_to_proxy": CaptureDirection.BACKEND_TO_PROXY,
    }
    try:
        return mapping[value]
    except KeyError as e:
        raise ValueError(
            f"Unsupported direction: {raw!r}. Use one of: {', '.join(sorted(mapping))}"
        ) from e


def _iter_sse_events(payload: bytes) -> Iterator[bytes]:
    """Split a potentially batched payload into per-event SSE bytes."""
    normalized = payload.replace(b"\r\n", b"\n")
    parts = normalized.split(b"\n\n")
    for part in parts:
        if not part.strip():
            continue
        yield part + b"\n\n"


def _saw_openai_delta_content(content: Any) -> bool:
    if not isinstance(content, dict):
        return False
    choices = content.get("choices")
    if not isinstance(choices, list):
        return False
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            continue
        delta_content = delta.get("content")
        if isinstance(delta_content, str) and delta_content:
            return True
    return False


def _is_trivial_repeat(event_bytes: bytes) -> bool:
    """Heuristic filter for expected tiny repeats (e.g. whitespace deltas)."""
    if not event_bytes:
        return True
    stripped = event_bytes.strip()
    if stripped in {b"data: [DONE]", b'data: ["DONE"]'}:
        return True
    # Ignore extremely small events (single-character deltas, punctuation, etc.)
    return len(stripped) < 40


async def _cmd_from_capture(args: argparse.Namespace) -> int:
    capture_path = Path(args.capture)
    direction = _parse_direction(args.direction)

    # Load via the capture inspection loader (no MAX_CAPTURE_ENTRIES limit) so we can
    # replay real-world captures that commonly exceed 10k entries.
    from scripts.inspect_cbor_capture import load_capture_file

    header, entries = load_capture_file(capture_path)

    def _meta(e: dict[str, Any]) -> dict[str, Any]:
        meta = e.get("meta", {})
        return meta if isinstance(meta, dict) else {}

    filtered: list[dict[str, Any]] = []
    for e in entries:
        if e.get("dir") != int(direction):
            continue
        meta = _meta(e)
        if args.session_id and meta.get("sid") != args.session_id:
            continue
        if args.backend and meta.get("be") != args.backend:
            continue
        filtered.append(e)

    # Group into streams using ss/se markers when present.
    streams: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for e in filtered:
        meta = _meta(e)
        if meta.get("ss") is True:
            current = [e]
            continue
        if current is None:
            continue
        current.append(e)
        if meta.get("se") is True:
            streams.append(current)
            current = None

    if args.list_streams:
        print(f"capture={capture_path}")
        print(f"header.session_id={header.get('session_id')!r} entries={len(entries)}")
        print(f"streams(direction={direction.name})={len(streams)}")
        for i, stream in enumerate(streams):
            total_bytes = sum(len(e.get("data", b"") or b"") for e in stream)
            sid = next(
                (_meta(e).get("sid") for e in stream if _meta(e).get("sid")), None
            )
            backend = next(
                (_meta(e).get("be") for e in stream if _meta(e).get("be")), None
            )
            model = next(
                (_meta(e).get("mod") for e in stream if _meta(e).get("mod")), None
            )
            print(
                f"[{i}] entries={len(stream)} bytes={total_bytes} "
                f"sid={sid!r} backend={backend!r} model={model!r} "
                f"seq={stream[0].get('seq')}->{stream[-1].get('seq')}"
            )
        return 0

    if not streams:
        print("No streams matched the provided filters.", file=sys.stderr)
        return 2

    stream_index = int(args.stream_index)
    if stream_index < 0 or stream_index >= len(streams):
        print(
            f"Invalid --stream-index={stream_index}; available: 0..{len(streams)-1}",
            file=sys.stderr,
        )
        return 2

    chosen_stream = streams[stream_index]
    decoder = SSEDecoder()
    registry = StreamingContextRegistry(state_ttl_seconds=300)
    accumulator = ContentAccumulationProcessor(registry=registry)
    from src.core.domain.streaming.streaming_content import StreamingContent

    saw_delta = False
    done_only_emissions: list[tuple[int, int]] = []
    failed: list[tuple[int, int]] = []

    for entry in chosen_stream:
        meta = _meta(entry)
        sid = (
            meta.get("sid") or args.session_id or header.get("session_id") or "unknown"
        )
        raw = entry.get("data", b"")
        if not isinstance(raw, bytes):
            continue
        for event_bytes in _iter_sse_events(raw):
            decoded = decoder.decode_payload(event_bytes)
            metadata = {
                "session_id": sid,
                "stream_id": sid,
                "capture_seq": entry.get("seq"),
            }
            metadata.update(decoded.metadata or {})

            if _saw_openai_delta_content(decoded.content):
                saw_delta = True

            chunk = StreamingContent(
                content=decoded.content if decoded.content is not None else "",
                metadata=metadata,
                is_done=decoded.is_done,
                raw_data=event_bytes,
            )

            processed = await accumulator.process(chunk)

            if decoded.is_done and (decoded.content == "" or decoded.content is None):
                # Terminal done-only marker: this is where the historical duplication happened.
                emitted_len = 0
                if isinstance(processed.content, str):
                    emitted_len = len(processed.content)
                done_only_emissions.append((int(entry.get("seq") or 0), emitted_len))
                if saw_delta and emitted_len > 0:
                    failed.append((int(entry.get("seq") or 0), emitted_len))

    print(f"capture={capture_path}")
    print(f"direction={direction.name} stream_index={stream_index}")
    print(f"saw_openai_delta_content={saw_delta}")
    if done_only_emissions:
        last_seq, last_len = done_only_emissions[-1]
        print(f"done_only_marker_last_seq={last_seq} emitted_content_len={last_len}")
    else:
        print("done_only_markers=0")

    if failed:
        print(
            "FAIL: done-only marker emitted non-empty content after deltas were streamed:",
            file=sys.stderr,
        )
        for seq, emitted_len in failed[:10]:
            print(f"  seq={seq} emitted_content_len={emitted_len}", file=sys.stderr)
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more", file=sys.stderr)
        return 3

    print("OK")
    return 0


async def _cmd_detect_repeats(args: argparse.Namespace) -> int:
    capture_path = Path(args.capture)
    direction = _parse_direction(args.direction)

    from scripts.inspect_cbor_capture import load_capture_file

    _header, entries = load_capture_file(capture_path)

    def _meta(e: dict[str, Any]) -> dict[str, Any]:
        meta = e.get("meta", {})
        return meta if isinstance(meta, dict) else {}

    filtered: list[dict[str, Any]] = []
    for e in entries:
        if e.get("dir") != int(direction):
            continue
        meta = _meta(e)
        if args.session_id and meta.get("sid") != args.session_id:
            continue
        filtered.append(e)

    streams: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for e in filtered:
        meta = _meta(e)
        if meta.get("ss") is True:
            current = [e]
            continue
        if current is None:
            continue
        current.append(e)
        if meta.get("se") is True:
            streams.append(current)
            current = None

    threshold = int(args.threshold)
    found = 0
    post_done_found = 0
    missing_finish_reason_found = 0

    for stream_index, stream in enumerate(streams):
        prev: bytes | None = None
        run_start_seq: int | None = None
        run_length = 0
        done_seen = False
        finish_reason_seen = False
        tool_calls_seen = False
        for entry in stream:
            raw = entry.get("data", b"")
            if not isinstance(raw, bytes):
                continue
            for event in _iter_sse_events(raw):
                stripped = event.strip()
                if stripped in {b"data: [DONE]", b'data: ["DONE"]'}:
                    done_seen = True
                    continue
                if b'"tool_calls"' in stripped:
                    tool_calls_seen = True
                if b'"finish_reason"' in stripped and not (
                    b'"finish_reason": null' in stripped
                    or b'"finish_reason":null' in stripped
                ):
                    finish_reason_seen = True
                if done_seen and stripped:
                    # Any content after [DONE] is suspicious.
                    post_done_found += 1
                    preview = (
                        event[:120]
                        .decode("utf-8", errors="replace")
                        .replace("\n", "\\n")
                    )
                    print(
                        f"[post-done] stream_index={stream_index} seq={entry.get('seq')} preview={preview!r}"
                    )
                    done_seen = False

                if prev is None:
                    prev = event
                    run_start_seq = int(entry.get("seq") or 0)
                    run_length = 1
                    continue
                if event == prev:
                    run_length += 1
                    continue

                # Flush previous run
                if (
                    run_length >= threshold
                    and prev is not None
                    and not _is_trivial_repeat(prev)
                ):
                    found += 1
                    start_seq = run_start_seq or 0
                    end_seq = int(entry.get("seq") or 0)
                    preview = (
                        prev[:120]
                        .decode("utf-8", errors="replace")
                        .replace("\n", "\\n")
                    )
                    print(
                        f"[repeat] stream_index={stream_index} run={run_length} "
                        f"seq_start={start_seq} seq_end~={end_seq} preview={preview!r}"
                    )
                prev = event
                run_start_seq = int(entry.get("seq") or 0)
                run_length = 1

        # End of stream flush
        if (
            run_length >= threshold
            and prev is not None
            and not _is_trivial_repeat(prev)
        ):
            found += 1
            start_seq = run_start_seq or 0
            end_seq = int(stream[-1].get("seq") or 0)
            preview = prev[:120].decode("utf-8", errors="replace").replace("\n", "\\n")
            print(
                f"[repeat] stream_index={stream_index} run={run_length} "
                f"seq_start={start_seq} seq_end={end_seq} preview={preview!r}"
            )

        if done_seen and tool_calls_seen and not finish_reason_seen:
            missing_finish_reason_found += 1
            print(
                f"[missing-finish-reason] stream_index={stream_index} "
                f"note='tool_calls present but finish_reason never non-null before DONE'"
            )
        elif done_seen and not finish_reason_seen:
            missing_finish_reason_found += 1
            print(
                f"[missing-finish-reason] stream_index={stream_index} "
                f"note='no non-null finish_reason observed before DONE'"
            )

    if found == 0:
        if post_done_found == 0 and missing_finish_reason_found == 0:
            print("OK (no suspicious repeats found)")
            return 0
        return 1
    return 1


async def _cmd_summarize_streams(args: argparse.Namespace) -> int:
    capture_path = Path(args.capture)
    direction = _parse_direction(args.direction)

    from scripts.inspect_cbor_capture import load_capture_file

    header, entries = load_capture_file(capture_path)

    def _meta(e: dict[str, Any]) -> dict[str, Any]:
        meta = e.get("meta", {})
        return meta if isinstance(meta, dict) else {}

    filtered: list[dict[str, Any]] = []
    for e in entries:
        if e.get("dir") != int(direction):
            continue
        meta = _meta(e)
        if args.session_id and meta.get("sid") != args.session_id:
            continue
        filtered.append(e)

    streams: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] | None = None
    for e in filtered:
        meta = _meta(e)
        if meta.get("ss") is True:
            current = [e]
            continue
        if current is None:
            continue
        current.append(e)
        if meta.get("se") is True:
            streams.append(current)
            current = None

    decoder = SSEDecoder()

    def _extract_delta_text(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if not isinstance(choices, list):
            return ""
        out = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue
            c = delta.get("content")
            if isinstance(c, str) and c:
                out.append(c)
        return "".join(out)

    def _safe_for_stdout(text: str) -> str:
        encoding = sys.stdout.encoding or "utf-8"
        return text.encode(encoding, errors="backslashreplace").decode(encoding)

    seen: dict[str, int] = {}
    for i, stream in enumerate(streams):
        text_parts: list[str] = []
        for entry in stream:
            raw = entry.get("data", b"")
            if not isinstance(raw, bytes):
                continue
            for event in _iter_sse_events(raw):
                decoded = decoder.decode_payload(event)
                text = _extract_delta_text(decoded.content)
                if text:
                    text_parts.append(text)
        final_text = "".join(text_parts)
        key = str(hash(final_text))
        dup_of = seen.get(key)
        if dup_of is None:
            seen[key] = i
        sid = args.session_id or header.get("session_id") or "unknown"
        seq_start = stream[0].get("seq")
        seq_end = stream[-1].get("seq")
        preview = final_text[:100].replace("\n", "\\n")
        suffix = (
            final_text[-100:].replace("\n", "\\n") if len(final_text) > 100 else preview
        )
        print(
            _safe_for_stdout(
                f"[{i}] sid={sid!r} seq={seq_start}->{seq_end} chars={len(final_text)} "
                f"dup_of={dup_of} head={preview!r} tail={suffix!r}"
            )
        )

    return 0


class _NoopAngelFactory(IQualityVerifierServiceFactory):
    def create(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise RuntimeError("AngelServiceFactory not used in this repro")


class _NoopResponseProcessor(IResponseProcessor):
    async def process_response(
        self, response: Any, session_id: str, context: RequestContext | None = None
    ) -> ProcessedResponse:  # pragma: no cover
        return ProcessedResponse(content=response)

    def process_streaming_response(
        self,
        response_iterator: Any,
        session_id: str,
        context: RequestContext | None = None,
    ) -> Any:  # pragma: no cover
        return response_iterator

    async def register_middleware(
        self, middleware: Any, priority: int = 0
    ) -> None:  # pragma: no cover
        return None


class _NoopRequestPreparation(IBackendRequestPreparation):
    async def prepare(
        self, request_data: ChatRequest, command_result: Any
    ) -> ChatRequest | None:  # pragma: no cover
        return request_data


class _PassthroughStreamingHandler:
    async def handle(
        self,
        stream: StreamingResponseEnvelope,
        request: ChatRequest,
        context: RequestContext,
        processing_context: Any,
    ) -> StreamingResponseEnvelope:
        return stream


class _FakeBackendProcessor(IBackendProcessor):
    def __init__(self, hang_event: asyncio.Event) -> None:
        self.calls = 0
        self._hang_event = hang_event

    async def process_backend_request(
        self,
        request: ChatRequest,
        session_id: str,
        context: RequestContext | None = None,
    ) -> StreamingResponseEnvelope:
        self.calls += 1

        async def _stream() -> Any:
            try:
                chunk = {
                    "id": "repro",
                    "object": "chat.completion.chunk",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": "hello"},
                            "finish_reason": None,
                        }
                    ],
                }
                yield ProcessedResponse(
                    content=f"data: {json.dumps(chunk)}\n\n".encode()
                )
                # Hang to keep this request IN_FLIGHT until the caller closes the stream.
                await self._hang_event.wait()
            except GeneratorExit:
                return

        return StreamingResponseEnvelope(content=_stream())


async def _cmd_dedup_storm(args: argparse.Namespace) -> int:
    session_id = "repro-session"
    hang_event = asyncio.Event()
    dedup = RequestDeduplicationService(
        window_seconds=2.0,
        streaming_window_seconds=30.0,
        streaming_in_flight_window_seconds=30.0,
        enabled=True,
    )

    backend = _FakeBackendProcessor(hang_event=hang_event)
    manager = BackendRequestManager(
        backend_processor=backend,
        response_processor=_NoopResponseProcessor(),
        quality_verifier_service_factory=_NoopAngelFactory(),
        request_preparation=_NoopRequestPreparation(),
        post_backend_response_coordinator=PostBackendResponseCoordinator(
            streaming_handler=_PassthroughStreamingHandler(),
        ),
        dedup_service=dedup,
    )

    request = ChatRequest(
        model="repro-model",
        stream=True,
        messages=[ChatMessage(role="user", content="hi")],
    )
    context = RequestContext(headers={}, cookies={}, state=None, app_state=None)

    # First request: register IN_FLIGHT and yield one chunk.
    first = await manager.process_backend_request(request, session_id, context)
    assert isinstance(first, StreamingResponseEnvelope)
    assert first.content is not None
    iterator = first.content

    # Consume one chunk, but keep the stream open.
    _ = await iterator.__anext__()

    # Second identical request: should be blocked as duplicate while IN_FLIGHT.
    duplicate_blocked = False
    try:
        dup = await manager.process_backend_request(request, session_id, context)
        if isinstance(dup, StreamingResponseEnvelope) and (
            (dup.headers or {}).get("x-llmproxy-duplicate-request") == "true"
        ):
            duplicate_blocked = True
    except DuplicateRequestError:
        duplicate_blocked = True

    # Close the stream (simulate client disconnect).
    try:
        aclose = getattr(iterator, "aclose", None)
        if aclose and callable(aclose):
            await aclose()
    finally:
        hang_event.set()

    # Third identical request: should still be blocked (zombie retry pattern after disconnect).
    zombie_blocked = False
    try:
        dup = await manager.process_backend_request(request, session_id, context)
        if isinstance(dup, StreamingResponseEnvelope) and (
            (dup.headers or {}).get("x-llmproxy-duplicate-request") == "true"
        ):
            zombie_blocked = True
    except DuplicateRequestError:
        zombie_blocked = True

    print(f"backend_calls={backend.calls}")
    print(f"duplicate_blocked_in_flight={duplicate_blocked}")
    print(f"duplicate_blocked_after_disconnect={zombie_blocked}")

    ok = backend.calls == 1 and duplicate_blocked and zombie_blocked
    if not ok:
        print("FAIL", file=sys.stderr)
        return 3
    print("OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="repro_streaming_repeat_and_dedup",
        description="Repro harness for critical streaming duplication/dedup bugs.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    from_capture = sub.add_parser(
        "from-capture",
        help="Replay a captured stream through ContentAccumulationProcessor.",
    )
    from_capture.add_argument("capture", help="Path to a CBOR wire capture file.")
    from_capture.add_argument(
        "--direction",
        default="backend_to_proxy",
        help="Capture direction to analyze (default: backend_to_proxy).",
    )
    from_capture.add_argument(
        "--session-id", default=None, help="Filter by session id."
    )
    from_capture.add_argument("--backend", default=None, help="Filter by backend name.")
    from_capture.add_argument(
        "--stream-index",
        default=0,
        help="Index of the matching stream to replay (default: 0).",
    )
    from_capture.add_argument(
        "--list-streams",
        action="store_true",
        help="List matching streams and exit.",
    )
    from_capture.set_defaults(_handler=_cmd_from_capture)

    dedup_storm = sub.add_parser(
        "dedup-storm",
        help="Simulate in-flight streaming request retries and verify dedup behavior.",
    )
    dedup_storm.set_defaults(_handler=_cmd_dedup_storm)

    detect_repeats = sub.add_parser(
        "detect-repeats",
        help="Scan a capture for suspicious repeated outbound SSE events.",
    )
    detect_repeats.add_argument("capture", help="Path to a CBOR wire capture file.")
    detect_repeats.add_argument(
        "--direction",
        default="proxy_to_client",
        help="Capture direction to analyze (default: proxy_to_client).",
    )
    detect_repeats.add_argument(
        "--session-id", default=None, help="Filter by session id."
    )
    detect_repeats.add_argument(
        "--threshold",
        default=15,
        help="Minimum consecutive repeats to report (default: 15).",
    )
    detect_repeats.set_defaults(_handler=_cmd_detect_repeats)

    summarize_streams = sub.add_parser(
        "summarize-streams",
        help="Summarize reconstructed text per stream (OpenAI delta style).",
    )
    summarize_streams.add_argument("capture", help="Path to a CBOR wire capture file.")
    summarize_streams.add_argument(
        "--direction",
        default="proxy_to_client",
        help="Capture direction to analyze (default: proxy_to_client).",
    )
    summarize_streams.add_argument(
        "--session-id", default=None, help="Filter by session id."
    )
    summarize_streams.set_defaults(_handler=_cmd_summarize_streams)

    ns = parser.parse_args(argv)
    handler = getattr(ns, "_handler", None)
    if handler is None or not callable(handler):
        raise RuntimeError("Missing command handler; did you pick a subcommand?")
    typed_handler = cast(Callable[[argparse.Namespace], Awaitable[int]], handler)

    async def _invoke() -> int:
        return await typed_handler(ns)

    return asyncio.run(_invoke())


if __name__ == "__main__":
    raise SystemExit(main())
