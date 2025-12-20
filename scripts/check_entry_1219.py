"""Check specific entries from CBOR capture."""

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


def main() -> None:
    entries: list[dict] = []
    with open("var/wire_captures_cbor/proxy-20251208_1803.cbor", "rb") as f:
        header: dict = cbor2.load(f)  # Read header first
        print(f"Header: session_id={header.get('session_id')}")

        while True:
            try:
                entry: dict = cbor2.load(f)
                # Handle decompression
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break

    print(f"Total entries: {len(entries)}")

    # Check entries 1217-1223
    for idx in [1217, 1218, 1219, 1220, 1221, 1222, 1223]:
        if idx >= len(entries):
            print(f"Entry [{idx}] - Out of range")
            continue

        entry = entries[idx]
        direction: int = entry.get("dir", -1)
        data_bytes: bytes = entry.get("data", b"")
        ts: float = entry.get("ts", 0)

        print(f"\n[{idx}] {DIRECTION_NAMES.get(direction, 'UNK')} ts={ts:.6f}")

        if data_bytes:
            try:
                text: str = data_bytes.decode("utf-8").strip()
                print(f"  raw (first 150): {text[:150]}")

                if text.startswith("data:"):
                    json_str: str = text[5:].strip()
                    if json_str != "[DONE]":
                        parsed: dict = json.loads(json_str)
                        choices: list[dict] = parsed.get("choices", [])
                        if choices:
                            delta: dict = choices[0].get("delta", {})
                            content: str | None = delta.get("content")
                            print(f"  content: {content!r}")
            except Exception as e:
                print(f"  error: {e}")


if __name__ == "__main__":
    main()
