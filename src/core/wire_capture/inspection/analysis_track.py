"""Single-request flow tracking."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from src.core.wire_capture.inspection.constants import DIRECTION_SYMBOLS
from src.core.wire_capture.inspection.correlation import (
    cp_window_end_index,
    find_enclosing_cp_index,
)
from src.core.wire_capture.inspection.metadata import meta_request_id
from src.core.wire_capture.inspection.payload import parse_all_sse_events
from src.core.wire_capture.inspection.text_output import writeln


def track_request(
    entries: list[dict[str, Any]],
    request_num: int,
    *,
    out: TextIO | None = None,
    backend_filter: str | None = None,
) -> None:
    """Track a specific request through the system; print to ``out``."""
    out = out or sys.stdout
    writeln(out)
    writeln(out, "=" * 70)
    writeln(out, f"REQUEST FLOW TRACKING - Request #{request_num}")
    writeln(out, "=" * 70)
    if backend_filter:
        writeln(out, f"(Filtered to backend: {backend_filter})")
        writeln(out, "=" * 70)

    bf_norm = backend_filter.strip().lower() if backend_filter else ""
    is_client = bf_norm == "client"

    req_idx: int | None = None
    if is_client:
        req_count = 0
        for i, e in enumerate(entries):
            if e.get("dir") == 0:
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break
    else:
        req_count = 0
        for i, e in enumerate(entries):
            if e.get("dir") == 2 and (
                backend_filter is None or e.get("meta", {}).get("be") == backend_filter
            ):
                req_count += 1
                if req_count == request_num:
                    req_idx = i
                    break
        if req_idx is None and backend_filter is None:
            req_count = 0
            for i, e in enumerate(entries):
                if e.get("dir") == 0:
                    req_count += 1
                    if req_count == request_num:
                        req_idx = i
                        break

    if req_idx is None:
        writeln(out, f"Request #{request_num} not found")
        return

    req_entry = entries[req_idx]
    anchor_rid = meta_request_id(req_entry.get("meta", {}))

    def passes_filter(ent: dict[str, Any]) -> bool:
        if backend_filter is None:
            return True
        if is_client:
            return ent.get("dir") in (0, 1)
        direction = ent.get("dir")
        if direction in (0, 1):
            return True
        if anchor_rid:
            ent_rid = meta_request_id(ent.get("meta", {}))
            if ent_rid and ent_rid != anchor_rid:
                return False
        ent_meta = ent.get("meta", {})
        be = ent_meta.get("be") if isinstance(ent_meta, dict) else None
        return bool(be == backend_filter)

    cp_idx = find_enclosing_cp_index(entries, req_idx)
    flow_start = cp_idx if cp_idx is not None else req_idx
    anchor_meta = entries[flow_start].get("meta", {})
    flow_end = cp_window_end_index(entries, flow_start, anchor_meta)

    prefix = [e for e in entries[flow_start:req_idx] if passes_filter(e)]
    suffix = [e for e in entries[req_idx + 1 : flow_end] if passes_filter(e)]
    flow = [*prefix, req_entry, *suffix]

    writeln(out, f"\nRequest initiated at entry [{req_entry.get('seq')}]")
    start_ts = req_entry.get("ts", 0)

    try:
        req_data = json.loads(req_entry.get("data", b"").decode("utf-8"))
        writeln(out, f"Model: {req_data.get('model', 'N/A')}")
        writeln(out, f"Request size: {len(req_entry.get('data', b'')):,} bytes")
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    writeln(out, "\nFlow timeline:")
    for e in flow:
        seq = e.get("seq", "?")
        direction = DIRECTION_SYMBOLS.get(e["dir"], f"?{e['dir']}")
        ts = e.get("ts", 0)
        delta = ts - start_ts
        data_len = len(e.get("data", b""))

        if e is req_entry:
            start_desc = (
                "Request received" if e.get("dir") == 0 else "Forwarded to backend"
            )
            writeln(
                out,
                f"  [START] [{seq}] {direction}  {start_desc} (t={delta:.3f}s)",
            )
            continue

        desc = f"{data_len:,} bytes"
        if e["dir"] == 2:
            desc = "Forwarded to backend"
        elif e["dir"] == 3:
            events = parse_all_sse_events(e.get("data", b""))
            if events:
                descriptions: list[str] = []
                for parsed in events:
                    if parsed.get("error"):
                        descriptions.append(
                            f"ERROR: {parsed['error'].get('message', 'Unknown')[:50]}"
                        )
                    elif any(
                        c.get("delta", {}).get("tool_calls")
                        for c in parsed.get("choices", [])
                    ):
                        descriptions.append("Tool call")
                    elif any(
                        c.get("delta", {}).get("content")
                        for c in parsed.get("choices", [])
                    ):
                        descriptions.append("Content")
                    else:
                        descriptions.append("Meta")

                if any(d.startswith("ERROR") for d in descriptions):
                    desc = next(d for d in descriptions if d.startswith("ERROR"))
                elif "Tool call" in descriptions:
                    desc = (
                        f"Tool call response (+{len(descriptions) - 1} other events)"
                        if len(descriptions) > 1
                        else "Tool call response"
                    )
                elif "Content" in descriptions:
                    desc = (
                        f"Content chunk (+{len(descriptions) - 1} other events)"
                        if len(descriptions) > 1
                        else "Content chunk"
                    )
                else:
                    desc = "Metadata chunk"
            else:
                desc = f"{len(e.get('data', b''))} bytes (Raw)"
        elif e["dir"] == 1:
            desc = "Forwarded to client"

        if delta > 10:
            desc += " !!! SLOW !!!"

        writeln(out, f"  [{direction}] [{seq}] {desc} (t={delta:.3f}s)")
