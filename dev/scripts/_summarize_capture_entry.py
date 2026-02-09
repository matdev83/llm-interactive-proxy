"""Summarize a single entry from a CBOR wire capture file.

This is a development-only diagnostic helper.
Prints only high-level fields to avoid dumping large prompts or secrets.
"""

from __future__ import annotations

import json
import sys
import zlib
from pathlib import Path
from typing import Any

import cbor2


def _load_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open("rb") as f:
        # Header (single CBOR object)
        _ = cbor2.load(f)
        while True:
            try:
                entry = cbor2.load(f)
            except (EOFError, cbor2.CBORDecodeEOF):
                break

            if isinstance(entry, dict) and entry.get("enc") == "zlib":
                try:
                    entry["data"] = zlib.decompress(entry["data"])
                except Exception:
                    pass
                entry.pop("enc", None)
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _safe_json_loads(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return None


def _extract_sse_data_lines(text: str) -> list[str]:
    stripped = text.strip()
    if "data:" not in stripped:
        return []
    lines: list[str] = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            lines.append(line[5:].lstrip())
    return lines


def main() -> int:
    capture_file = Path(sys.argv[1])
    idx = int(sys.argv[2])

    entries = _load_entries(capture_file)
    if idx < 0 or idx >= len(entries):
        print(f"Index out of range: {idx} (entries={len(entries)})")
        return 2

    entry = entries[idx]
    direction = entry.get("dir")
    meta = entry.get("meta", {}) if isinstance(entry.get("meta"), dict) else {}
    data = entry.get("data")

    print(f"entry_index={idx}")
    print(f"dir={direction}")
    print(f"meta_keys={sorted(list(meta.keys()))}")
    for k in ("sid", "rid", "be", "mod", "host", "ua", "sc", "ss", "se", "ci", "tc"):
        if k in meta:
            v = meta.get(k)
            if isinstance(v, str) and len(v) > 120:
                v = v[:120] + "…"
            print(f"meta.{k}={v}")

    if isinstance(data, bytes):
        preview = data[:200].decode("utf-8", errors="replace").strip()
        print(f"data_bytes={len(data)} preview={preview[:200]}")

        decoded = data.decode("utf-8", errors="replace")

        # If SSE, extract first JSON payload for summary
        sse_lines = _extract_sse_data_lines(decoded)
        if sse_lines:
            if sse_lines == ["[DONE]"]:
                print("sse.done_only=True")
                return 0
            # Use first non-DONE data line
            json_candidate = next((l for l in sse_lines if l and l != "[DONE]"), "")
            obj = _safe_json_loads(json_candidate)
        else:
            obj = _safe_json_loads(decoded)

        if isinstance(obj, dict):
            print(f"json.top_keys={sorted(list(obj.keys()))}")
            for k in ("model", "stream", "max_tokens", "max_completion_tokens"):
                if k in obj:
                    print(f"json.{k}={obj.get(k)}")
            msgs = obj.get("messages")
            if isinstance(msgs, list):
                print(f"json.messages.count={len(msgs)}")
                roles = [m.get("role") for m in msgs if isinstance(m, dict)]
                print(f"json.messages.roles_sample={roles[:10]}")

            # If OpenAI chunk format, show delta content stats
            choices = obj.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                delta = choices[0].get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    reasoning = (
                        delta.get("reasoning_content")
                        or delta.get("reasoning")
                        or delta.get("thinking")
                        or delta.get("thought")
                    )
                    if isinstance(content, str):
                        print(f"json.delta.content.len={len(content)}")
                        print(f"json.delta.content.preview={content[:120]!r}")
                    if isinstance(reasoning, str):
                        print(f"json.delta.reasoning.len={len(reasoning)}")
                        print(f"json.delta.reasoning.preview={reasoning[:120]!r}")
    else:
        print(f"data_type={type(data).__name__}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

