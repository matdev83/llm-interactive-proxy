"""Simple test for Codex WebSocket support via proxy API.

This test:
1. Assumes the proxy is running with Codex backend enabled
2. Tests HTTP/SSE and WebSocket connections through the proxy
3. Compares performance
"""

import asyncio
import json
import logging
import sys
import time

import httpx
import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

PROXY_URL = "http://localhost:8001"
PROXY_WS_URL = "ws://localhost:8001"


async def test_http_sse(backend: str = "openai-codex") -> dict:
    """Test HTTP/SSE connection through proxy."""
    logger.info(f"Testing HTTP/SSE with backend: {backend}")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            payload = {
                "model": f"{backend}:gpt-4",
                "messages": [
                    {
                        "role": "user",
                        "content": "Say 'Hello from Codex via HTTP/SSE' and nothing else."
                    }
                ],
                "stream": True,
            }
            
            start_time = time.time()
            
            # Send request
            async with client.stream(
                "POST",
                f"{PROXY_URL}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                response.raise_for_status()
                
                chunks = []
                content = ""
                
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                            chunks.append(chunk)
                            if "choices" in chunk:
                                for choice in chunk["choices"]:
                                    if "delta" in choice and "content" in choice["delta"]:
                                        content += choice["delta"]["content"]
                        except json.JSONDecodeError:
                            pass
            
            elapsed = time.time() - start_time
            
            logger.info(f"HTTP/SSE completed in {elapsed:.3f}s, {len(chunks)} chunks")
            logger.info(f"Content: {content}")
            
            return {
                "success": True,
                "transport": "HTTP/SSE",
                "elapsed_seconds": elapsed,
                "chunk_count": len(chunks),
                "content": content,
                "error": None,
            }
            
        except Exception as e:
            logger.error(f"HTTP/SSE test failed: {e}", exc_info=True)
            return {
                "success": False,
                "transport": "HTTP/SSE",
                "error": str(e),
                "error_type": type(e).__name__,
            }


async def test_websocket(backend: str = "openai-codex") -> dict:
    """Test WebSocket connection through proxy."""
    logger.info(f"Testing WebSocket with backend: {backend}")
    
    try:
        async with websockets.connect(
            f"{PROXY_WS_URL}/v1/responses",
            open_timeout=10,
        ) as ws:
            # Send response.create event
            payload = {
                "type": "response.create",
                "model": f"{backend}:gpt-4",
                "input": [
                    {
                        "role": "user",
                        "content": "Say 'Hello from Codex via WebSocket' and nothing else."
                    }
                ],
            }
            
            start_time = time.time()
            
            await ws.send(json.dumps(payload))
            logger.info("Sent WebSocket request")
            
            chunks = []
            content = ""
            done = False
            
            # Receive events
            while not done:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    event = json.loads(message)
                    chunks.append(event)
                    
                    event_type = event.get("type")
                    logger.debug(f"Received event: {event_type}")
                    
                    if event_type == "response.text.delta":
                        delta = event.get("delta", "")
                        content += delta
                    elif event_type == "response.done":
                        done = True
                        
                except asyncio.TimeoutError:
                    logger.warning("WebSocket receive timeout")
                    break
            
            elapsed = time.time() - start_time
            
            logger.info(f"WebSocket completed in {elapsed:.3f}s, {len(chunks)} events")
            logger.info(f"Content: {content}")
            
            return {
                "success": True,
                "transport": "WebSocket",
                "elapsed_seconds": elapsed,
                "chunk_count": len(chunks),
                "content": content,
                "error": None,
            }
            
    except Exception as e:
        logger.error(f"WebSocket test failed: {e}", exc_info=True)
        return {
            "success": False,
            "transport": "WebSocket",
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def main():
    """Run comparison test."""
    print("=" * 80)
    print("Codex WebSocket Support Test (via Proxy API)")
    print("=" * 80)
    print()
    print("NOTE: This test requires the proxy to be running with Codex backend enabled")
    print(f"      Proxy URL: {PROXY_URL}")
    print()
    
    # Test HTTP/SSE
    print("TEST 1: HTTP/SSE via Proxy")
    print("-" * 80)
    http_result = await test_http_sse()
    print()
    print(f"Result: {json.dumps(http_result, indent=2)}")
    print()
    
    # Test WebSocket
    print("TEST 2: WebSocket via Proxy")
    print("-" * 80)
    ws_result = await test_websocket()
    print()
    print(f"Result: {json.dumps(ws_result, indent=2)}")
    print()
    
    # Comparison
    print("=" * 80)
    print("COMPARISON RESULTS")
    print("=" * 80)
    
    http_success = http_result.get("success", False)
    ws_success = ws_result.get("success", False)
    
    print(f"HTTP/SSE Success: {http_success}")
    print(f"WebSocket Success: {ws_success}")
    print()
    
    if http_success and ws_success:
        http_time = http_result.get("elapsed_seconds", 0)
        ws_time = ws_result.get("elapsed_seconds", 0)
        
        if ws_time > 0:
            speedup = ((http_time - ws_time) / http_time) * 100
            print(f"HTTP/SSE Time: {http_time:.3f}s")
            print(f"WebSocket Time: {ws_time:.3f}s")
            print(f"Speedup: {speedup:+.1f}%")
        
        print()
        print("[SUCCESS] Both transports work!")
        print()
        print("RECOMMENDATION: WebSocket support confirmed - safe to enable by default")
        return 0
        
    elif http_success and not ws_success:
        ws_error = ws_result.get("error", "Unknown")
        print(f"[INFO] HTTP/SSE works, but WebSocket failed")
        print(f"WebSocket Error: {ws_error}")
        print()
        
        # Check if it's a protocol error (backend doesn't support WS)
        if "Unsupported" in ws_error or "404" in ws_error or "400" in ws_error:
            print("RECOMMENDATION: Codex backend doesn't support WebSocket yet")
            print("                Keep WebSocket disabled by default (opt-in)")
        else:
            print("RECOMMENDATION: WebSocket might work but needs investigation")
            print("                Keep disabled by default for safety")
        return 0
        
    elif not http_success:
        print("[ERROR] HTTP/SSE baseline test failed")
        print(f"Error: {http_result.get('error', 'Unknown')}")
        print()
        print("Check if proxy is running and Codex backend is enabled")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[INTERRUPTED] Test cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
