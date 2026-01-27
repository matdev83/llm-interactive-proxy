import json
import sys
import zlib

import cbor2


def dump_cbor(path, entry_index):
    entries = []
    with open(path, "rb") as f:
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

    if entry_index >= len(entries):
        print(f"Entry {entry_index} not found. Total entries: {len(entries)}")
        return

    entry = entries[entry_index]
    print(f"Entry {entry_index} Direction: {entry.get('dir')}")

    try:
        content_bytes = entry.get("data")
        if isinstance(content_bytes, bytes):
            try:
                content = content_bytes.decode("utf-8")
                try:
                    # Try parsing as JSON
                    content = json.loads(content)
                    print(json.dumps(content, indent=2))
                except:
                    print(content)
            except:
                print(f"Hex: {content_bytes.hex()[:100]}...")
        else:
            print(json.dumps(content_bytes, indent=2))
    except Exception as e:
        print(f"Error dumping content: {e}")


if __name__ == "__main__":
    dump_cbor(sys.argv[1], int(sys.argv[2]))
