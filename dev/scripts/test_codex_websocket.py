"""Test script to verify Codex WebSocket support in real world.

This script tests:
1. HTTP/SSE connection to Codex (baseline)
2. WebSocket connection to Codex (if supported)
3. Compares performance and functionality
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.connectors._openai_codex_connector import OpenAICodexConnector
from src.core.config.app_config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def test_codex_connection(use_websocket: bool = False) -> dict:
    """Test Codex connector with or without WebSocket.
    
    Args:
        use_websocket: Whether to enable WebSocket transport
        
    Returns:
        dict with test results
    """
    transport_mode = "WebSocket" if use_websocket else "HTTP/SSE"
    logger.info(f"Testing Codex connector with {transport_mode} transport...")
    
    # Load minimal config
    config_path = project_root / "config" / "config.yaml"
    if not config_path.exists():
        config_path = project_root / "config" / "config.example.yaml"
    
    app_config = load_config(config_path=str(config_path))
    
    # Override WebSocket setting via environment
    if use_websocket:
        os.environ["OPENAI_CODEX_WEBSOCKET_ENABLED"] = "1"
    else:
        os.environ.pop("OPENAI_CODEX_WEBSOCKET_ENABLED", None)
    
    # Create connector with minimal required parameters
    connector = OpenAICodexConnector(
        client=None,
        config=app_config,
    )
    
    try:
        # Initialize connector
        await connector.initialize()
        
        # Check if WebSocket is actually enabled
        if hasattr(connector, "_response_executor"):
            executor = connector._response_executor
            if executor and hasattr(executor, "_transport"):
                transport = executor._transport
                ws_enabled = getattr(transport, "_use_websocket", False)
                logger.info(f"Transport WebSocket flag: {ws_enabled}")
        
        # Prepare a simple test request
        test_request = {
            "model": "gpt-4",
            "messages": [
                {
                    "role": "user",
                    "content": "Say 'Hello from Codex' and nothing else."
                }
            ],
            "stream": True,
        }
        
        start_time = time.time()
        
        # Make request
        logger.info(f"Sending test request via {transport_mode}...")
        response = await connector.chat_completions(test_request)
        
        # Collect streaming response
        chunks = []
        content = ""
        
        if hasattr(response, "content") and hasattr(response.content, "__aiter__"):
            async for chunk in response.content:
                chunks.append(chunk)
                # Try to extract text content
                if isinstance(chunk, dict):
                    if "choices" in chunk:
                        for choice in chunk["choices"]:
                            if "delta" in choice and "content" in choice["delta"]:
                                content += choice["delta"]["content"]
        elif hasattr(response, "content"):
            # Non-streaming response
            if isinstance(response.content, dict):
                content = str(response.content)
        
        elapsed = time.time() - start_time
        
        logger.info(f"{transport_mode} test completed in {elapsed:.3f}s")
        logger.info(f"Received {len(chunks)} chunks")
        logger.info(f"Content: {content[:100]}...")
        
        return {
            "success": True,
            "transport": transport_mode,
            "elapsed_seconds": elapsed,
            "chunk_count": len(chunks),
            "content_preview": content[:200],
            "error": None,
        }
        
    except Exception as e:
        logger.error(f"{transport_mode} test failed: {e}", exc_info=True)
        return {
            "success": False,
            "transport": transport_mode,
            "error": str(e),
            "error_type": type(e).__name__,
        }
    finally:
        # Cleanup
        try:
            await connector.shutdown()
        except Exception as cleanup_err:
            logger.warning(f"Cleanup error: {cleanup_err}")


async def main():
    """Run comparison test between HTTP/SSE and WebSocket."""
    print("=" * 80)
    print("Codex WebSocket Support Test")
    print("=" * 80)
    print()
    
    # Check auth file exists
    auth_path = Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        print(f"[ERROR] Auth file not found at: {auth_path}")
        print("Please run Codex CLI login first or set up auth.json manually.")
        return 1
    
    print(f"[OK] Found auth file at: {auth_path}")
    print()
    
    # Test 1: HTTP/SSE (baseline)
    print("TEST 1: HTTP/SSE Transport (Baseline)")
    print("-" * 80)
    http_result = await test_codex_connection(use_websocket=False)
    print()
    print(f"Result: {json.dumps(http_result, indent=2)}")
    print()
    
    # Test 2: WebSocket
    print("TEST 2: WebSocket Transport")
    print("-" * 80)
    ws_result = await test_codex_connection(use_websocket=True)
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
        print("RECOMMENDATION: Enable WebSocket by default")
        return 0
        
    elif http_success and not ws_success:
        print("[INFO] HTTP/SSE works, but WebSocket failed")
        print(f"WebSocket Error: {ws_result.get('error', 'Unknown')}")
        print()
        print("RECOMMENDATION: Keep WebSocket disabled by default (opt-in)")
        return 0
        
    elif not http_success:
        print("[ERROR] HTTP/SSE baseline test failed")
        print(f"Error: {http_result.get('error', 'Unknown')}")
        print()
        print("Cannot test WebSocket support - baseline connectivity issue")
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
