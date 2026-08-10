import json
from pathlib import Path
from src.core.simulation.capture_reader import CaptureReader
from src.core.domain.cbor_capture import CaptureDirection

def main():
    capture_path = Path("var/wire_captures_cbor/proxy-20260810_153127-p74632.cbor")
    reader = CaptureReader()
    session = reader.load(capture_path)
    
    outbound_backend_reqs = [e for e in session.entries if e.direction == CaptureDirection.PROXY_TO_BACKEND]
    
    for i, req in enumerate(outbound_backend_reqs):
        data = req.data
        text = data.decode("utf-8", errors="ignore")
        if "token-plan.ap-southeast-1.maas.aliyuncs.com" in text:
            print(f"\n==========================================")
            print(f"Alibaba Token Plan Req {i} at timestamp {req.timestamp}")
            print(f"==========================================")
            
            # Split headers and body
            parts = text.split("\r\n\r\n", 1)
            headers = parts[0]
            body = parts[1] if len(parts) > 1 else ""
            print("Headers:")
            print(headers)
            print("\nBody JSON structure:")
            try:
                obj = json.loads(body)
                print(f"Model: {obj.get('model')}")
                print(f"Stream: {obj.get('stream')}")
                print(f"Thinking: {obj.get('thinking')}")
                messages = obj.get("messages", [])
                print(f"Messages count: {len(messages)}")
                for idx, msg in enumerate(messages):
                    role = msg.get("role")
                    content = msg.get("content")
                    print(f"\n  -- Message [{idx}] role='{role}' --")
                    if isinstance(content, str):
                        print(f"     Content: {content[:100]}... (len={len(content)})")
                    elif isinstance(content, list):
                        print(f"     Content blocks ({len(content)}):")
                        for b_idx, block in enumerate(content):
                            if isinstance(block, dict):
                                b_type = block.get("type")
                                if b_type == "text":
                                    txt = block.get("text", "")
                                    print(f"       [{b_idx}] text: {txt[:80]}...")
                                elif b_type == "thinking":
                                    th = block.get("thinking", "")
                                    print(f"       [{b_idx}] thinking: {th[:80]}...")
                                elif b_type == "tool_use":
                                    print(f"       [{b_idx}] tool_use id={block.get('id')} name={block.get('name')} input={block.get('input')}")
                                elif b_type == "tool_result":
                                    res_content = block.get("content", "")
                                    if isinstance(res_content, str):
                                        print(f"       [{b_idx}] tool_result tool_use_id={block.get('tool_use_id')} is_error={block.get('is_error')} content={res_content[:100]}...")
                                    else:
                                        print(f"       [{b_idx}] tool_result tool_use_id={block.get('tool_use_id')} is_error={block.get('is_error')} content_type={type(res_content)}")
                                else:
                                    print(f"       [{b_idx}] unknown block: {block}")
                            else:
                                print(f"       [{b_idx}] non-dict block: {block}")
            except Exception as e:
                print(f"Failed to parse body as JSON: {e}")
                print(f"Raw body snippet: {body[:1000]}")

if __name__ == "__main__":
    main()
