"""Verify the actual sequence of entries in the CBOR file."""

import sys

sys.path.insert(0, ".")

import json
import zlib

import cbor2

DIRECTION_NAMES = {
    0: "C->P",
    1: "P->C",
    2: "P->B",
    3: "B->P",
}


def main():
    entries = []
    with open("var/wire_captures_cbor/proxy-20251208_1803.cbor", "rb") as f:
        cbor2.load(f)
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break

    # Find entries around timestamp 577018 (microseconds)
    target_ts = 1765213520.577018

    print("Entries around timestamp 1765213520.577:")
    print("=" * 80)

    for idx, entry in enumerate(entries):
        ts = entry.get("ts", 0)
        # Check if within 1ms of target
        if abs(ts - target_ts) < 0.001:
            direction = entry.get("dir", -1)
            seq = entry.get("seq", -1)
            data = entry.get("data", b"")

            content = "N/A"
            if data:
                try:
                    text = data.decode("utf-8").strip()
                    if text.startswith("data:"):
                        json_str = text[5:].strip()
                        if json_str != "[DONE]":
                            parsed = json.loads(json_str)
                            choices = parsed.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content", "N/A")
                except:
                    content = "error"

            print(
                f"[{idx}] seq={seq} {DIRECTION_NAMES.get(direction, 'UNK')} ts={ts:.6f} content={content!r}"
            )

    # Count B->P and P->C entries in this time window
    bp_count = sum(
        1
        for e in entries
        if abs(e.get("ts", 0) - target_ts) < 0.001 and e.get("dir") == 3
    )
    pc_count = sum(
        1
        for e in entries
        if abs(e.get("ts", 0) - target_ts) < 0.001 and e.get("dir") == 1
    )

    print()
    print(f"B->P count in window: {bp_count}")
    print(f"P->C count in window: {pc_count}")

    if bp_count != pc_count:
        print(f"\nMISMATCH: {bp_count} B->P but only {pc_count} P->C!")


if __name__ == "__main__":
    main()
