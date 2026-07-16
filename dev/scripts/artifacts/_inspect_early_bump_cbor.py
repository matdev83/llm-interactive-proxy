"""Extract Codex outbound JSON fields from a CBOR capture."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from src.core.simulation.capture_reader import CaptureReader


def main() -> int:
    path = Path(sys.argv[1])
    reader = CaptureReader()
    session = reader.load(path)
    print(f"entries={len(session.entries)}")
    for i, entry in enumerate(session.entries):
        direction = str(getattr(entry.direction, "value", entry.direction))
        data = entry.data
        if isinstance(data, (bytes, bytearray)):
            text = bytes(data).decode("utf-8", errors="replace")
        else:
            text = str(data)
        print(f"[{i}] direction={direction!r} bytes={len(text)}")
        if "proxy_to_backend" not in direction.lower() and "P->B" not in direction:
            # still try to parse any HTTP POST body for visibility
            if "POST " not in text and '"model"' not in text:
                continue
        parts = text.split("\r\n\r\n", 1)
        if len(parts) < 2:
            parts = text.split("\n\n", 1)
        body = parts[-1] if len(parts) > 1 else text
        start = body.find("{")
        if start < 0:
            continue
        try:
            payload = json.loads(body[start:])
        except json.JSONDecodeError:
            # may be client request without nested complexity
            try:
                payload = json.loads(text[text.find("{") :])
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        if "model" not in payload and "text" not in payload:
            continue
        print(f"[{i}] model={payload.get('model')}")
        print(f"[{i}] temperature={payload.get('temperature')!r}")
        print(f"[{i}] text={payload.get('text')!r}")
        print(f"[{i}] verbosity_top={payload.get('verbosity')!r}")
        interesting = sorted(
            k
            for k in payload.keys()
            if k
            in {
                "model",
                "temperature",
                "text",
                "verbosity",
                "stream",
                "store",
                "reasoning",
            }
        )
        print(f"[{i}] interesting_keys={interesting}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
