#!/usr/bin/env python
"""Debug script to compare working vs failing requests."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.simulation.capture_reader import CaptureReader


def main() -> None:
    cbor_path = "var/wire_captures_cbor/proxy-20251202_1608.cbor"
    
    reader = CaptureReader()
    session = reader.load(cbor_path)
    
    # Entry 11 = Turn 2 request (works)
    # Entry 21 = Turn 3 request (fails)
    
    working_entry = session.entries[11]
    failing_entry = session.entries[21]
    
    # Decode data
    working_data = working_entry.data
    failing_data = failing_entry.data
    
    if isinstance(working_data, bytes):
        working_data = working_data.decode("utf-8")
    if isinstance(failing_data, bytes):
        failing_data = failing_data.decode("utf-8")
    
    working_json = json.loads(working_data)
    failing_json = json.loads(failing_data)
    
    print("="*60)
    print("WORKING REQUEST (Turn 2, Entry 11)")
    print("="*60)
    print(f"Size: {len(working_data)} bytes")
    print(f"Model: {working_json.get('model')}")
    print(f"Messages: {len(working_json.get('messages', []))}")
    print(f"Stream: {working_json.get('stream')}")
    print(f"Temperature: {working_json.get('temperature')}")
    print(f"Max tokens: {working_json.get('max_tokens')}")
    
    # Check for tools
    tools = working_json.get("tools")
    print(f"Tools: {len(tools) if tools else 'None'}")
    
    # Check extra_body
    extra_body = working_json.get("extra_body")
    if extra_body:
        print(f"Extra body keys: {list(extra_body.keys())}")
    
    print("\n" + "="*60)
    print("FAILING REQUEST (Turn 3, Entry 21)")
    print("="*60)
    print(f"Size: {len(failing_data)} bytes")
    print(f"Model: {failing_json.get('model')}")
    print(f"Messages: {len(failing_json.get('messages', []))}")
    print(f"Stream: {failing_json.get('stream')}")
    print(f"Temperature: {failing_json.get('temperature')}")
    print(f"Max tokens: {failing_json.get('max_tokens')}")
    
    # Check for tools
    tools = failing_json.get("tools")
    print(f"Tools: {len(tools) if tools else 'None'}")
    
    # Check extra_body
    extra_body = failing_json.get("extra_body")
    if extra_body:
        print(f"Extra body keys: {list(extra_body.keys())}")
    
    print("\n" + "="*60)
    print("MESSAGE STRUCTURE COMPARISON")
    print("="*60)
    
    working_msgs = working_json.get("messages", [])
    failing_msgs = failing_json.get("messages", [])
    
    print(f"\nWorking messages: {len(working_msgs)}")
    for i, msg in enumerate(working_msgs):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        content_len = len(str(content)) if content else 0
        tool_calls = msg.get("tool_calls")
        tc_info = f" + {len(tool_calls)} tool_calls" if tool_calls else ""
        print(f"  [{i}] {role}: {content_len} chars{tc_info}")
    
    print(f"\nFailing messages: {len(failing_msgs)}")
    for i, msg in enumerate(failing_msgs):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        content_len = len(str(content)) if content else 0
        tool_calls = msg.get("tool_calls")
        tc_info = f" + {len(tool_calls)} tool_calls" if tool_calls else ""
        print(f"  [{i}] {role}: {content_len} chars{tc_info}")
    
    # Check last few messages in detail
    print("\n" + "="*60)
    print("LAST 3 MESSAGES IN FAILING REQUEST")
    print("="*60)
    
    for msg in failing_msgs[-3:]:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        tool_calls = msg.get("tool_calls")
        
        print(f"\n--- {role.upper()} ---")
        if content:
            content_str = str(content)
            if len(content_str) > 1000:
                print(f"Content ({len(content_str)} chars):")
                print(f"  First 500: {content_str[:500]}")
                print(f"  Last 500: {content_str[-500:]}")
            else:
                print(f"Content: {content_str}")
        else:
            print("Content: (empty)")
        
        if tool_calls:
            print(f"Tool calls ({len(tool_calls)}):")
            for tc in tool_calls:
                print(f"  - ID: {tc.get('id')}")
                func = tc.get("function", {})
                print(f"    Name: {func.get('name')}")
                args = func.get("arguments", "")
                if len(str(args)) > 200:
                    print(f"    Args ({len(str(args))} chars): {str(args)[:200]}...")
                else:
                    print(f"    Args: {args}")


def compare_client_vs_proxy() -> None:
    """Compare client request to proxy request."""
    cbor_path = "var/wire_captures_cbor/proxy-20251202_1608.cbor"
    
    reader = CaptureReader()
    session = reader.load(cbor_path)
    
    # Entry 0 = Client to Proxy (Turn 1)
    # Entry 1 = Proxy to Backend (Turn 1)
    
    client_entry = session.entries[0]
    proxy_entry = session.entries[1]
    
    # Decode data
    client_data = client_entry.data
    proxy_data = proxy_entry.data
    
    if isinstance(client_data, bytes):
        client_data = client_data.decode("utf-8")
    if isinstance(proxy_data, bytes):
        proxy_data = proxy_data.decode("utf-8")
    
    client_json = json.loads(client_data)
    proxy_json = json.loads(proxy_data)
    
    print("="*60)
    print("CLIENT -> PROXY REQUEST")
    print("="*60)
    print(f"Size: {len(client_data)} bytes")
    
    client_tools = client_json.get("tools")
    print(f"Tools: {len(client_tools) if client_tools else 'None'}")
    if client_tools:
        print("Tool names:")
        for t in client_tools[:10]:  # First 10
            func = t.get("function", {})
            print(f"  - {func.get('name')}")
        if len(client_tools) > 10:
            print(f"  ... and {len(client_tools) - 10} more")
    
    print("\n" + "="*60)
    print("PROXY -> BACKEND REQUEST")
    print("="*60)
    print(f"Size: {len(proxy_data)} bytes")
    
    proxy_tools = proxy_json.get("tools")
    print(f"Tools: {len(proxy_tools) if proxy_tools else 'None'}")
    if proxy_tools:
        print("Tool names:")
        for t in proxy_tools[:10]:
            func = t.get("function", {})
            print(f"  - {func.get('name')}")


if __name__ == "__main__":
    main()
    print("\n\n")
    compare_client_vs_proxy()

