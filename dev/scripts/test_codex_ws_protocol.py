"""Test different WebSocket protocols for Codex backend."""

import asyncio
import json
import logging
from pathlib import Path

import websockets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_token():
    """Load access token from auth.json"""
    auth_path = Path.home() / ".codex" / "auth.json"
    with open(auth_path) as f:
        creds = json.load(f)
    return creds.get("tokens", {}).get("access_token")


async def test_protocol(protocol_name: str, test_func):
    """Test a specific WebSocket protocol."""
    print(f"\n{'='*60}")
    print(f"Testing: {protocol_name}")
    print('='*60)
    
    try:
        token = load_token()
        headers = {"Authorization": f"Bearer {token}"}
        
        ws_url = "wss://chatgpt.com/backend-api/codex/responses"
        
        async with websockets.connect(ws_url, additional_headers=headers, open_timeout=10) as ws:
            logger.info("[CONNECTED] WebSocket established")
            
            # Run the test function
            result = await test_func(ws)
            
            print(f"[SUCCESS] {protocol_name} worked!")
            print(f"Response: {result[:500] if result else 'No response'}")
            return True
            
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[FAILED] Connection closed: {e}")
        return False
    except Exception as e:
        print(f"[FAILED] Error: {e}")
        return False


async def test_openai_responses_format(ws):
    """Test OpenAI Responses API format (what we tried)."""
    request = {
        "model": "gpt-4o-mini",
        "input": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }
    await ws.send(json.dumps(request))
    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return response


async def test_openai_responses_event_format(ws):
    """Test OpenAI Responses API event format (response.create)."""
    event = {
        "type": "response.create",
        "model": "gpt-4o-mini",
        "input": [{"role": "user", "content": "Hello"}],
    }
    await ws.send(json.dumps(event))
    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return response


async def test_chat_completions_format(ws):
    """Test chat completions format."""
    request = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello"}],
        "stream": True,
    }
    await ws.send(json.dumps(request))
    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return response


async def test_empty_ping(ws):
    """Test empty message (ping)."""
    await ws.send("")
    response = await asyncio.wait_for(ws.recv(), timeout=5.0)
    return response


async def main():
    """Test different WebSocket protocols."""
    print("Testing ChatGPT Codex Backend WebSocket Protocols")
    print("This will try different message formats to find what's supported\n")
    
    tests = [
        ("OpenAI Responses API format", test_openai_responses_format),
        ("OpenAI Responses API event format", test_openai_responses_event_format),
        ("Chat Completions format", test_chat_completions_format),
        ("Empty ping", test_empty_ping),
    ]
    
    results = {}
    for name, test_func in tests:
        results[name] = await test_protocol(name, test_func)
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    working = [name for name, success in results.items() if success]
    
    if working:
        print(f"\n[SUCCESS] Working protocols: {', '.join(working)}")
        print("\nRECOMMENDATION: WebSocket is supported, enable by default!")
    else:
        print("\n[FAILED] No protocols worked - WebSocket not supported")
        print("\nRECOMMENDATION: Keep WebSocket disabled by default")


if __name__ == "__main__":
    asyncio.run(main())
