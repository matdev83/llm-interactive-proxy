
import sys
import json
import cbor2
import zlib

def inspect_tool_defs(cbor_path):
    print(f"Reading {cbor_path} for tool definitions...")
    with open(cbor_path, "rb") as f:
        try:
           header = cbor2.load(f)
        except:
           return
           
        while True:
            try:
                entry = cbor2.load(f)
                if entry.get("enc") == "zlib":
                    entry["data"] = zlib.decompress(entry["data"])
                
                # Check for P->B (dir=2)
                if entry["dir"] == 2:
                    data = entry.get("data", b"")
                    try:
                        obj = json.loads(data)
                        if "tools" in obj:
                            print("-" * 50)
                            print(f"SEQ: {entry.get('seq')}")
                            tools = obj["tools"]
                            for t in tools:
                                if t.get("function", {}).get("name") == "Grep":
                                    print(f"TOOL: Grep")
                                    print(json.dumps(t, indent=2))
                    except:
                        pass
            except (EOFError, cbor2.CBORDecodeEOF):
                break

if __name__ == "__main__":
    if len(sys.argv) > 1:
        inspect_tool_defs(sys.argv[1])
    else:
        print("Usage: python script.py <cbor_file>")
