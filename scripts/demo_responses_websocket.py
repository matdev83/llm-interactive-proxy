#!/usr/bin/env python
"""Demo script for OpenAI Responses API WebSocket transport.

This script demonstrates how to use WebSocket transport for the Responses API,
showing both direct OpenAI connections and proxy connections.

Usage:
    # Test direct OpenAI WebSocket connection:
    python scripts/demo_responses_websocket.py --mode direct

    # Test proxy WebSocket connection:
    python scripts/demo_responses_websocket.py --mode proxy --proxy-url ws://localhost:8000/v1/responses

    # Test with multiple turns (conversation):
    python scripts/demo_responses_websocket.py --mode direct --turns 3

Requirements:
    - Set OPENAI_API_KEY environment variable
    - For proxy mode, ensure proxy is running with WebSocket enabled
"""

import argparse
import asyncio
import json
import os
import sys
import time

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


async def demo_direct_openai_websocket(turns: int = 1):
    """Demonstrate direct WebSocket connection to OpenAI.

    Args:
        turns: Number of conversation turns to execute
    """
    from src.connectors.openai_websocket_client import OpenAIWebSocketClient

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    print("=" * 80)
    print("OpenAI Responses API WebSocket Demo - Direct Connection")
    print("=" * 80)
    print()

    client = OpenAIWebSocketClient(api_key=api_key)

    try:
        print("Connecting to OpenAI WebSocket endpoint...")
        await client.connect()
        print("✓ Connected successfully")
        print()

        previous_response_id = None

        for turn in range(1, turns + 1):
            print(f"--- Turn {turn}/{turns} ---")
            print()

            # Prepare request payload
            if turn == 1:
                input_text = "Tell me a short fact about Python programming language."
            else:
                input_text = "Tell me another interesting fact."

            payload = {
                "model": "gpt-4o-mini",
                "input": input_text,
                "max_output_tokens": 100,
            }

            print(f"Request: {input_text}")
            print()

            # Send request and stream response
            start_time = time.time()
            response_text = ""
            response_id = None

            print("Response: ", end="", flush=True)

            async for response_chunk in client.send_response_create(
                payload=payload,
                previous_response_id=previous_response_id,
            ):
                content = response_chunk.content
                metadata = response_chunk.metadata or {}

                # Handle different event types
                if metadata.get("event_type") == "response.content_part.delta":
                    if isinstance(content, dict):
                        delta = content.get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            print(text, end="", flush=True)
                            response_text += text

                elif metadata.get("done"):
                    if isinstance(content, dict):
                        response_id = content.get("id")
                    break

            elapsed = time.time() - start_time

            print()
            print()
            print(f"Response ID: {response_id}")
            print(f"Time: {elapsed:.2f}s")
            print()

            # Save response ID for next turn
            previous_response_id = response_id

        print("=" * 80)
        print(f"✓ Completed {turns} conversation turns successfully")
        print("=" * 80)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()
    finally:
        print("\nDisconnecting...")
        await client.disconnect()
        print("✓ Disconnected")


async def demo_proxy_websocket(proxy_url: str, turns: int = 1):
    """Demonstrate WebSocket connection through proxy.

    Args:
        proxy_url: WebSocket URL of the proxy
        turns: Number of conversation turns to execute
    """
    try:
        import websockets
    except ImportError:
        print("Error: websockets library not installed")
        print("Install with: pip install websockets")
        sys.exit(1)

    api_key = os.getenv("OPENAI_API_KEY", "dummy-key-for-proxy")

    print("=" * 80)
    print("OpenAI Responses API WebSocket Demo - Through Proxy")
    print("=" * 80)
    print()

    print(f"Connecting to proxy at {proxy_url}...")

    try:
        async with websockets.connect(
            proxy_url,
            extra_headers={
                "Authorization": f"Bearer {api_key}",
            },
        ) as websocket:
            print("✓ Connected successfully")
            print()

            response_cache = {}

            for turn in range(1, turns + 1):
                print(f"--- Turn {turn}/{turns} ---")
                print()

                # Prepare request
                if turn == 1:
                    input_text = "Tell me a short fact about WebSockets."
                else:
                    input_text = "Tell me more about that."

                request_event = {
                    "type": "response.create",
                    "model": "gpt-4o-mini",
                    "input": input_text,
                    "max_output_tokens": 100,
                }

                # Add previous_response_id if available
                if turn > 1 and response_cache:
                    last_id = list(response_cache.keys())[-1]
                    request_event["previous_response_id"] = last_id

                print(f"Request: {input_text}")
                print()

                # Send request
                await websocket.send(json.dumps(request_event))

                # Receive response
                start_time = time.time()
                response_text = ""
                response_id = None

                print("Response: ", end="", flush=True)

                while True:
                    message = await websocket.recv()
                    event = json.loads(message)

                    event_type = event.get("type")

                    if event_type == "error":
                        print(f"\n\nError from proxy: {event.get('error')}")
                        break

                    elif event_type == "response.content_part.delta":
                        delta = event.get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            print(text, end="", flush=True)
                            response_text += text

                    elif event_type == "response.done":
                        response_obj = event.get("response", {})
                        response_id = response_obj.get("id")
                        if response_id:
                            response_cache[response_id] = response_obj
                        break

                elapsed = time.time() - start_time

                print()
                print()
                print(f"Response ID: {response_id}")
                print(f"Time: {elapsed:.2f}s")
                print()

            print("=" * 80)
            print(f"✓ Completed {turns} conversation turns successfully")
            print("=" * 80)

    except ConnectionRefusedError:
        print(f"\nError: Could not connect to proxy at {proxy_url}")
        print("Make sure the proxy is running with WebSocket support enabled")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback

        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description="Demo script for OpenAI Responses API WebSocket transport"
    )
    parser.add_argument(
        "--mode",
        choices=["direct", "proxy"],
        default="direct",
        help="Connection mode: direct to OpenAI or through proxy",
    )
    parser.add_argument(
        "--proxy-url",
        default="ws://localhost:8000/v1/responses",
        help="Proxy WebSocket URL (for proxy mode)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=1,
        help="Number of conversation turns to execute",
    )

    args = parser.parse_args()

    if args.mode == "direct":
        asyncio.run(demo_direct_openai_websocket(turns=args.turns))
    else:
        asyncio.run(demo_proxy_websocket(proxy_url=args.proxy_url, turns=args.turns))


if __name__ == "__main__":
    main()
