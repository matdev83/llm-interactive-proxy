"""Export capture sessions to JSON."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from src.core.wire_capture.inspection.constants import DIRECTION_NAMES
from src.core.wire_capture.inspection.metadata import normalize_metadata
from src.core.wire_capture.inspection.payload import parse_sse_chunk, safe_decode
from src.core.wire_capture.inspection.text_output import writeln


def export_to_json(
    header: dict[str, Any],
    entries: list[dict[str, Any]],
    output_file: str | None,
    *,
    out: TextIO | None = None,
    backend_filter: str | None = None,
) -> None:
    """Export capture data to JSON; messages go to ``out`` (and file if given)."""
    out = out or sys.stdout
    entries_list: list[dict[str, Any]] = []
    output: dict[str, Any] = {
        "header": {
            "session_id": header.get("session_id"),
            "created_at": header.get("created_at"),
            "metadata": header.get("metadata", {}),
        },
        "entries": entries_list,
    }

    for e in entries:
        if backend_filter is not None and e.get("meta", {}).get("be") != backend_filter:
            continue
        meta = e.get("meta", {})
        entry_dict = {
            "seq": e.get("seq"),
            "direction": DIRECTION_NAMES.get(e["dir"], f"Unknown({e['dir']})"),
            "timestamp": e.get("ts"),
            "data_length": len(e.get("data", b"")),
            "metadata": normalize_metadata(meta),
        }

        parsed = parse_sse_chunk(e.get("data", b""))
        if parsed:
            entry_dict["parsed"] = parsed
        else:
            data = e.get("data", b"")
            if data:
                entry_dict["data_preview"] = safe_decode(data, 500)

        entries_list.append(entry_dict)

    json_str = json.dumps(output, indent=2, default=str)
    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(json_str)
        writeln(out, f"Exported to {output_file}")
    else:
        writeln(out, json_str)
