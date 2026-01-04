#!/usr/bin/env python3
"""
Test script to verify DoS vulnerability fix in ToolCallRepairService.
"""

import json
import sys
import time
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.tool_call_repair_service import ToolCallRepairService


def create_large_json_payload(multiplier=10):
    """Create a large JSON payload to test DoS protection."""
    print(f"Creating large JSON payload ({multiplier}x multiplier)...")

    large_array = []
    for i in range(200000 * multiplier):  # 200k elements * multiplier
        large_array.append(
            {
                "id": i,
                "data": "x" * 200,  # 200 chars per item
                "nested": {
                    "level1": {
                        "level2": {
                            "level3": {
                                "level4": {"level5": "very deep nesting test data"}
                            }
                        }
                    }
                },
            }
        )

    malicious_data = {
        "function_call": {
            "name": "test_tool",
            "arguments": {
                "large_array": large_array,
                "duplicate_array": large_array.copy(),  # Double the size
            },
        }
    }

    return json.dumps(malicious_data)


def test_dos_protection():
    """Test that DoS protection is working."""
    print("=== Testing DoS Protection Fix ===")

    repair_service = ToolCallRepairService()

    # Test with progressively larger payloads that should be blocked
    multipliers = [5, 10, 20]  # Different sizes that exceed 10MB limit

    for multiplier in multipliers:
        print(f"\n--- Testing with {multiplier}x multiplier ---")

        malicious_json = create_large_json_payload(multiplier)
        payload_size_mb = len(malicious_json.encode("utf-8")) / (1024 * 1024)
        print(f"Payload size: {payload_size_mb:.2f}MB")

        # Test various attack vectors
        attack_vectors = [
            ("Code block", f"```json\n{malicious_json}\n```"),
            ("Direct JSON", malicious_json),
            ("Tool format", f'{{"tool": {malicious_json}}}'),
            ("Function call format", f'{{"function_call": {malicious_json}}}'),
        ]

        for vector_name, content in attack_vectors:
            print(f"\nTesting {vector_name} attack vector...")

            start_time = time.time()

            try:
                result = repair_service.repair_tool_calls(content)

                end_time = time.time()
                duration = end_time - start_time

                print(f"  [OK] Completed in {duration:.2f} seconds")

                # With fix, large payloads should be rejected quickly (< 1 second)
                if duration > 1.0:
                    print(
                        f"  [WARNING] Processing took {duration:.2f} seconds - possible issue"
                    )
                else:
                    print(
                        f"  [SUCCESS] Processing was fast ({duration:.2f}s) - protection working!"
                    )

            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                print(
                    f"  [ERROR] Failed after {duration:.2f} seconds: {type(e).__name__}: {e}"
                )

    # Test with normal-sized payload (should still work)
    print("\n--- Testing normal-sized payload (should work) ---")

    normal_payload = {
        "function_call": {
            "name": "test_tool",
            "arguments": {
                "message": "This is a normal-sized payload",
                "data": [1, 2, 3, 4, 5],
            },
        }
    }

    normal_json = json.dumps(normal_payload)
    normal_content = f"```json\n{normal_json}\n```"

    start_time = time.time()

    try:
        result = repair_service.repair_tool_calls(normal_content)

        end_time = time.time()
        duration = end_time - start_time

        print(f"Normal payload processed in {duration:.3f} seconds")

        if result:
            print(f"Tool call detected: {result.tool_call['function']['name']}")
        else:
            print("No tool call detected")

    except Exception as e:
        print(f"Normal payload failed: {type(e).__name__}: {e}")

    print("\n=== Test Summary ===")
    print("Expected behavior:")
    print("1. Large payloads (>1MB) should be rejected quickly (< 1 second)")
    print("2. Normal payloads should process normally")
    print("3. No memory errors or recursion errors should occur")


if __name__ == "__main__":
    test_dos_protection()
