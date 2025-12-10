
import sys
import json
import cbor2
import zlib
from pathlib import Path

def inspect_tool_calls(cbor_path):
    print(f"Reading {cbor_path}...")
    with open(cbor_path, "rb") as f:
        try:
           header = cbor2.load(f)
        except:
           print("Failed to load header")
           return
           
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                
                # Check for P->C (dir=1)
                if entry["dir"] == 1:
                    data = entry.get("data", b"")
                    try:
                        text = data.decode("utf-8", errors="ignore")
                        if "tool_calls" in text:
                            # Parse SSE events
                            for line in text.split("\n"):
                                if line.startswith("data: ") and "[DONE]" not in line:
                                    json_str = line[6:]
                                    try:
                                        obj = json.loads(json_str)
                                        choices = obj.get("choices", [])
                                        for choice in choices:
                                            delta = choice.get("delta", {})
                                            tool_calls = delta.get("tool_calls", [])
                                            for tc in tool_calls:
                                                print("-" * 50)
                                                print(f"SEQ: {entry.get('seq')}")
                                                print(f"TOOL CALL: {tc}")
                                                func = tc.get("function", {})
                                                print(f"FUNCTION: {func.get('name')}")
                                                print(f"ARGS: {func.get('arguments')}")
                                    except json.JSONDecodeError:
                                        pass
                    except:
                        pass
            except (EOFError, cbor2.CBORDecodeEOF):
                break

if __name__ == "__main__":
    if len(sys.argv) > 1:
        inspect_tool_calls(sys.argv[1])
    else:
        print("Usage: python script.py <cbor_file>")
