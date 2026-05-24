"""Streaming performance analysis."""

from __future__ import annotations

import sys
from typing import Any, TextIO

from src.core.wire_capture.inspection.correlation import (
    backend_payload_entries,
    collect_backend_response_for_pb,
    collect_correlated_entries,
    compute_backend_duration,
    compute_backend_ttft,
)
from src.core.wire_capture.inspection.metadata import meta_request_id
from src.core.wire_capture.inspection.text_output import writeln


def analyze_streaming(
    entries: list[dict[str, Any]],
    *,
    out: TextIO | None = None,
    backend_filter: str | None = None,
) -> None:
    """Analyze streaming performance and print to ``out``."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, "STREAMING PERFORMANCE ANALYSIS")
    writeln(out, "=" * 70)
    if backend_filter:
        writeln(out, f"(Filtered to backend: {backend_filter})")
        writeln(out, "=" * 70)

    seen_backend_request_ids: set[str] = set()
    i = 0
    stream_num = 0
    while i < len(entries):
        e = entries[i]

        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            i += 1
            continue

        if e["dir"] == 2:
            request_id = meta_request_id(e.get("meta", {}))
            if request_id:
                if request_id in seen_backend_request_ids:
                    i += 1
                    continue
                seen_backend_request_ids.add(request_id)

            stream_num += 1
            writeln(out, f"\n--- Stream #{stream_num} (Entry [{e.get('seq')}]) ---")

            chunks = collect_backend_response_for_pb(entries, i)
            if not chunks and request_id:
                chunks = collect_correlated_entries(
                    entries,
                    start_index=i,
                    request_id=request_id,
                    direction=3,
                )

            if not chunks:
                writeln(out, "  No backend response chunks")
                i += 1
                continue

            ttft = compute_backend_ttft(e, chunks)
            duration = compute_backend_duration(e, chunks)
            payload_chunks = backend_payload_entries(chunks)
            chunk_count = len(payload_chunks)
            total_bytes = sum(len(c.get("data", b"")) for c in payload_chunks)

            if ttft is not None:
                writeln(out, f"  Time to First Token: {ttft:.3f}s")
            if duration is not None:
                writeln(out, f"  Total Duration: {duration:.3f}s")
            writeln(out, f"  Chunks: {chunk_count}")
            writeln(out, f"  Total Data: {total_bytes:,} bytes")

            if chunk_count > 1 and duration is not None:
                avg_chunk_time = duration / (chunk_count - 1)
                writeln(out, f"  Avg Time Between Chunks: {avg_chunk_time:.3f}s")

            slow_chunks: list[tuple[Any, Any]] = []
            for k in range(1, len(payload_chunks)):
                gap = payload_chunks[k].get("ts", 0) - payload_chunks[k - 1].get(
                    "ts", 0
                )
                if gap > 5:
                    slow_chunks.append((payload_chunks[k].get("seq"), gap))

            if slow_chunks:
                writeln(out, "  Slow Chunks Detected:")
                for seq, gap in slow_chunks:
                    writeln(out, f"    Entry [{seq}]: {gap:.1f}s gap")

            i += 1
        else:
            i += 1
