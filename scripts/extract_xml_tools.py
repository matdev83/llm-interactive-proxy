
import sys
import json
import cbor2
import zlib
import re

def inspect_xml_tools(cbor_path):
    print(f"Reading {cbor_path} for XML tools...")
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
                
                # Check for B->P (dir=3)
                if entry["dir"] == 3:
                    data = entry.get("data", b"")
                    try:
                        text = data.decode("utf-8", errors="ignore")
                        # Look for <Tool> tags or JSON containing them
                        if "<Tool>" in text or "&lt;Tool&gt;" in text:
                            print("-" * 50)
                            print(f"SEQ: {entry.get('seq')}")
                            # Simplify output
                            start = text.find("<Tool>")
                            if start == -1: start = text.find("&lt;Tool&gt;")
                            end = text.find("</Tool>")
                            if end == -1: end = text.find("&lt;/Tool&gt;")
                            
                            if start != -1 and end != -1:
                                snippet = text[start:end+15] # include closing tag roughly
                                print(f"XML SNIPPET: {snippet}")
                            else:
                                print(f"FULL TEXT (truncated): {text[:200]}...")
                                
                    except:
                        pass
            except (EOFError, cbor2.CBORDecodeEOF):
                break

if __name__ == "__main__":
    if len(sys.argv) > 1:
        inspect_xml_tools(sys.argv[1])
    else:
        print("Usage: python script.py <cbor_file>")
