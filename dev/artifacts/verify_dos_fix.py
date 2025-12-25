#!/usr/bin/env python3
"""
Test script to verify DoS vulnerability fix in CodeBuff message router.

This script tests that large JSON payloads are properly rejected
with appropriate error messages.
"""

import asyncio
import json
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed


async def test_dos_protection(websocket_url: str, payload_size_mb: int = 2):
    """
    Test DoS protection by sending a large JSON payload.
    
    Args:
        websocket_url: WebSocket server URL (e.g., "ws://localhost:8000/ws")
        payload_size_mb: Size of test payload in megabytes
    
    Returns:
        bool: True if protection is working, False if not
    """
    print(f"[*] Connecting to WebSocket server at {websocket_url}")
    
    try:
        async with websockets.connect(websocket_url) as websocket:
            print("[*] Connected successfully")
            
            # Step 1: Send a valid identify message first
            identify_msg = {
                "type": "identify",
                "clientSessionId": "test-session-protection",
                "txid": 1
            }
            
            print("[*] Sending identify message...")
            await websocket.send(json.dumps(identify_msg))
            
            # Wait for ack
            response = await websocket.recv()
            response_data = json.loads(response)
            
            if not response_data.get("success"):
                print(f"[-] Identify failed: {response_data}")
                return False
            
            print("[*] Identify successful, proceeding with protection test")
            
            # Step 2: Create large payload that should be rejected
            print(f"[*] Creating {payload_size_mb}MB test payload...")
            
            large_data = "x" * (payload_size_mb * 1024 * 1024)
            test_payload = {
                "type": "ping",
                "txid": 2,
                "largeData": large_data
            }
            
            payload_json = json.dumps(test_payload)
            actual_size_mb = len(payload_json) / (1024 * 1024)
            print(f"[*] Payload size: {actual_size_mb:.2f}MB")
            
            # Step 3: Send large payload and check response
            print("[*] Sending large payload (should be rejected)...")
            start_time = time.time()
            
            await websocket.send(payload_json)
            
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                end_time = time.time()
                response_time = end_time - start_time
                
                response_data = json.loads(response)
                print(f"[*] Response time: {response_time:.3f} seconds")
                
                # Check if we got a proper error response
                if not response_data.get("success"):
                    error_msg = response_data.get("message", "")
                    if "too large" in error_msg.lower():
                        print("[+] PROTECTION WORKING: Large payload was rejected")
                        print(f"[+] Error message: {error_msg}")
                        return True
                    else:
                        print(f"[?] Large payload rejected but for different reason: {error_msg}")
                        return True
                else:
                    print("[-] PROTECTION FAILED: Large payload was accepted")
                    return False
                    
            except asyncio.TimeoutError:
                end_time = time.time()
                response_time = end_time - start_time
                print(f"[!] Server took {response_time:.3f} seconds and timed out")
                print("[-] PROTECTION FAILED: Server appears to be overwhelmed")
                return False
                
    except ConnectionClosed as e:
        print(f"[!] Server closed connection: {e}")
        print("[+] PROTECTION WORKING: Server rejected the connection")
        return True
        
    except Exception as e:
        print(f"[-] Error during test: {e}")
        return False


async def test_normal_operation(websocket_url: str):
    """Test that normal-sized messages still work correctly."""
    print(f"[*] Testing normal operation with {websocket_url}")
    
    try:
        async with websockets.connect(websocket_url) as websocket:
            # Send identify
            identify_msg = {
                "type": "identify",
                "clientSessionId": "test-normal",
                "txid": 1
            }
            
            await websocket.send(json.dumps(identify_msg))
            response = await websocket.recv()
            response_data = json.loads(response)
            
            if not response_data.get("success"):
                print(f"[-] Normal identify failed: {response_data}")
                return False
            
            # Send normal-sized ping
            ping_msg = {
                "type": "ping",
                "txid": 2
            }
            
            await websocket.send(json.dumps(ping_msg))
            response = await websocket.recv()
            response_data = json.loads(response)
            
            if response_data.get("success"):
                print("[+] Normal operation works correctly")
                return True
            else:
                print(f"[-] Normal ping failed: {response_data}")
                return False
                
    except Exception as e:
        print(f"[-] Error in normal operation test: {e}")
        return False


async def main():
    """Main function to run DoS protection tests."""
    if len(sys.argv) < 2:
        print("Usage: python verify_dos_fix.py <websocket_url> [test_payload_size_mb]")
        print("Example: python verify_dos_fix.py ws://localhost:8000/ws 2")
        sys.exit(1)
    
    websocket_url = sys.argv[1]
    test_payload_size_mb = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    
    print("=" * 60)
    print("CodeBuff DoS Protection Verification")
    print("=" * 60)
    print(f"Target: {websocket_url}")
    print(f"Test payload size: {test_payload_size_mb}MB")
    print()
    
    try:
        # Test 1: Normal operation
        print("TEST 1: Normal operation")
        print("-" * 30)
        normal_ok = await test_normal_operation(websocket_url)
        print()
        
        # Test 2: Large payload rejection
        print("TEST 2: Large payload rejection")
        print("-" * 30)
        protection_ok = await test_dos_protection(websocket_url, test_payload_size_mb)
        print()
        
        # Results
        print("=" * 60)
        print("RESULTS:")
        print("=" * 60)
        print(f"Normal operation: {'PASS' if normal_ok else 'FAIL'}")
        print(f"DoS protection:   {'PASS' if protection_ok else 'FAIL'}")
        print()
        
        if normal_ok and protection_ok:
            print("[SUCCESS] DoS vulnerability has been fixed!")
            print("          Normal messages work, large messages are blocked.")
        elif not normal_ok and protection_ok:
            print("[PARTIAL] DoS protection works but broke normal operation")
        elif normal_ok and not protection_ok:
            print("[FAIL] DoS protection not working - vulnerability still exists")
        else:
            print("[FAIL] Both normal operation and protection are broken")
            
    except KeyboardInterrupt:
        print("\n[!] Test interrupted by user")
        
    except Exception as e:
        print(f"\n[-] Test failed with error: {e}")


if __name__ == "__main__":
    asyncio.run(main())