"""Check CBOR file structure."""

import sys

sys.path.insert(0, ".")

import cbor2


def main():
    with open("var/wire_captures_cbor/proxy-20251208_1803.cbor", "rb") as f:
        data = cbor2.load(f)

    print(f"Type: {type(data)}")
    if isinstance(data, dict):
        print(f"Keys: {data.keys()}")
        for key, value in data.items():  # type: ignore[reportUnknownVariableType]
            print(
                f"  {key}: {type(value)}, len={len(value) if hasattr(value, '__len__') else 'N/A'}"
            )
    elif isinstance(data, list):
        print(f"List length: {len(data)}")
        if data:
            print(f"First item type: {type(data[0])}")
            if isinstance(data[0], dict):
                print(f"First item keys: {data[0].keys()}")


if __name__ == "__main__":
    main()
