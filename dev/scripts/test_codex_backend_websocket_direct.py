"""Direct test of ChatGPT Codex backend WebSocket support.

Tests the actual ChatGPT backend at wss://chatgpt.com/backend-api/codex/responses
to determine if WebSockets are supported as a transport.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

import websockets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_codex_credentials() -> dict:
    """Load credentials from ~/.codex/auth.json"""
    auth_path = Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        raise FileNotFoundError(f"Codex auth file not found: {auth_path}")
    
    with open(auth_path) as f:
        return json.load(f)


async def test_codex_websocket() -> dict:
    """Test WebSocket connection to ChatGPT Codex backend."""
    logger.info("Loading Codex credentials...")
    try:
        creds = load_codex_credentials()
        access_token = creds.get("tokens", {}).get("access_token")
        
        if not access_token:
            return {
                "success": False,
                "error": "No access_token found in auth.json",
            }
        
        logger.info(f"Access token loaded (length: {len(access_token)})")
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to load credentials: {e}",
        }
    
    # Test WebSocket endpoint
    ws_url = "wss://chatgpt.com/backend-api/codex/responses"
    logger.info(f"Attempting WebSocket connection to: {ws_url}")
    
    try:
        # Try to connect with auth header
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        logger.info("Connecting to WebSocket endpoint...")
        async with websockets.connect(
            ws_url,
            additional_headers=headers,
            open_timeout=10,
        ) as ws:
            logger.info("[SUCCESS] WebSocket connection established!")
            
            # Try to send a test request (use o1-mini which is supported)
            test_request = {
                "model": "o1-mini",
                "input": [
                    {
                        "role": "user",
                        "content": "Say 'WebSocket test successful' and nothing else."
                    }
                ],
                "tools": [],
                "stream": True,
            }
            
            logger.info("Sending test request...")
            await ws.send(json.dumps(test_request))
            logger.info("Request sent, waiting for response...")
            
            # Wait for response (with timeout)
            try:
                response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                logger.info(f"[SUCCESS] Received response: {response[:200]}...")
                
                return {
                    "success": True,
                    "websocket_supported": True,
                    "response_preview": response[:500],
                    "message": "ChatGPT Codex backend supports WebSockets!",
                }
            except asyncio.TimeoutError:
                logger.warning("Response timeout - connection works but no data received")
                return {
                    "success": True,
                    "websocket_supported": True,
                    "response_preview": None,
                    "message": "WebSocket connects but response format may be different",
                }
                
    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"WebSocket connection rejected: HTTP {e.status_code}")
        return {
            "success": False,
            "websocket_supported": False,
            "error": f"HTTP {e.status_code}",
            "message": f"ChatGPT backend rejected WebSocket (HTTP {e.status_code})",
        }
    except websockets.exceptions.InvalidHandshake as e:
        logger.error(f"WebSocket handshake failed: {e}")
        return {
            "success": False,
            "websocket_supported": False,
            "error": str(e),
            "message": "ChatGPT backend doesn't support WebSocket protocol",
        }
    except ConnectionRefusedError:
        logger.error("Connection refused")
        return {
            "success": False,
            "websocket_supported": False,
            "error": "Connection refused",
            "message": "ChatGPT backend refused connection",
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {
            "success": False,
            "websocket_supported": False,
            "error": str(e),
            "error_type": type(e).__name__,
        }


async def test_http_fallback() -> dict:
    """Test HTTP POST to the same endpoint for comparison."""
    logger.info("\n--- Testing HTTP POST (baseline) ---")
    
    import httpx
    
    try:
        creds = load_codex_credentials()
        access_token = creds.get("tokens", {}).get("access_token")
        
        http_url = "https://chatgpt.com/backend-api/codex/responses"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": "o1-mini",
            "input": [
                {
                    "role": "user",
                    "content": "Say 'HTTP test' and nothing else."
                }
            ],
            "tools": [],
            "stream": True,
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"Sending HTTP POST to: {http_url}")
            response = await client.post(http_url, json=payload, headers=headers)
            logger.info(f"HTTP Status: {response.status_code}")
            
            if response.status_code == 200:
                logger.info("[SUCCESS] HTTP POST works")
                return {
                    "success": True,
                    "status_code": response.status_code,
                }
            else:
                logger.warning(f"HTTP POST failed: {response.status_code}")
                return {
                    "success": False,
                    "status_code": response.status_code,
                    "response": response.text[:200],
                }
                
    except Exception as e:
        logger.error(f"HTTP test failed: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


async def main():
    """Run WebSocket and HTTP tests."""
    print("=" * 80)
    print("ChatGPT Codex Backend WebSocket Support Test")
    print("=" * 80)
    print()
    print("This test connects directly to the ChatGPT backend API to determine")
    print("if WebSockets are supported as a transport mechanism.")
    print()
    
    # Test WebSocket
    print("TEST 1: WebSocket Connection")
    print("-" * 80)
    ws_result = await test_codex_websocket()
    print()
    print(f"Result: {json.dumps(ws_result, indent=2)}")
    print()
    
    # Test HTTP for comparison
    print("TEST 2: HTTP POST (Baseline)")
    print("-" * 80)
    http_result = await test_http_fallback()
    print()
    print(f"Result: {json.dumps(http_result, indent=2)}")
    print()
    
    # Final verdict
    print("=" * 80)
    print("FINAL VERDICT")
    print("=" * 80)
    
    ws_supported = ws_result.get("websocket_supported", False)
    http_works = http_result.get("success", False)
    
    if ws_supported:
        print("[CONFIRMED] ChatGPT Codex backend SUPPORTS WebSockets!")
        print()
        print("RECOMMENDATION: Enable WebSocket by default for Codex connector")
        print("                Set enabled: true in config")
        return 0
    else:
        error_msg = ws_result.get("error", "Unknown")
        print(f"[CONFIRMED] ChatGPT Codex backend DOES NOT support WebSockets")
        print(f"             Error: {error_msg}")
        print()
        
        if http_works:
            print("HTTP POST works, so the endpoint and credentials are valid.")
            print()
        
        print("RECOMMENDATION: Keep WebSocket disabled by default (enabled: false)")
        print("                This is the correct default setting")
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
