"""Compare the actual bytes in B->P and P->C entries."""

import sys
sys.path.insert(0, ".")

import cbor2
import json
import zlib

DIRECTION_NAMES = {
    0: "C->P",
    1: "P->C",
    2: "P->B",
    3: "B->P",
}


def main():
    entries = []
    with open("var/wire_captures_cbor/proxy-20251208_1803.cbor", "rb") as f:
        header = cbor2.load(f)
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                    del entry["enc"]
                entries.append(entry)
            except (EOFError, cbor2.CBORDecodeEOF):
                break
    
    print("Comparing B->P and P->C bytes around the problematic area:")
    print("=" * 80)
    
    # Entry 1219 is the newline B->P with NO P->C
    # Entry 1220 is the dash B->P
    # Entry 1221 is the dash P->C
    
    for idx in [1219, 1220, 1221]:
        entry = entries[idx]
        direction = entry.get("dir", -1)
        data = entry.get("data", b"")
        ts = entry.get("ts", 0)
        
        print(f"\n[{idx}] {DIRECTION_NAMES.get(direction, 'UNK')} ts={ts:.6f}")
        print(f"  Raw bytes ({len(data)} bytes):")
        print(f"  {data!r}")
        
        # Also show the parsed content
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
                            print(f"  Parsed content: {content!r}")
            except Exception as e:
                print(f"  Parse error: {e}")


if __name__ == "__main__":
    main()

