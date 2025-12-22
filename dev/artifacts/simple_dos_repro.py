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


def create_large_json_payload():
    """Create a large JSON payload to trigger DoS."""
    print("Creating large JSON payload...")

    large_array = []
    for i in range(50000):  # 50k elements
        large_array.append(
            {"id": i, "data": "x" * 100, "nested": {"level1": {"level2": "deep"}}}
        )

    malicious_data = {
        "function_call": {
            "name": "test_tool",
            "arguments": {"large_array": large_array},
        }
    }

    return json.dumps(malicious_data)


def test_dos_vulnerability():
    """Test DoS vulnerability in ToolCallRepairService."""
    print("=== ToolCallRepairService DoS Vulnerability Test ===")

    repair_service = get_tool_call_repair_service()

    # Test with large payload
    print("\nTesting with large JSON payload...")
    malicious_json = create_large_json_payload()
    payload_size_mb = len(malicious_json.encode("utf-8")) / (1024 * 1024)
    print(f"Payload size: {payload_size_mb:.2f}MB")

    # Wrap in code block (attack vector)
    malicious_content = f"```json\n{malicious_json}\n```"

    start_time = time.time()

    try:
        result = repair_service.repair_tool_calls(malicious_content)

        end_time = time.time()
        duration = end_time - start_time

        print(f"[OK] Processing completed in {duration:.2f} seconds")
        print(f"Result: {'Tool call detected' if result else 'No tool call detected'}")

        if duration > 5.0:
            print("[!] VULNERABILITY CONFIRMED: Processing took > 5 seconds!")
            print(
                "Large payload causes DoS in ToolCallRepairService._process_json_match()"
            )
            return True

    except MemoryError:
        end_time = time.time()
        duration = end_time - start_time
        print(f"[ERROR] MemoryError after {duration:.2f} seconds")
        print("[!] VULNERABILITY CONFIRMED: Memory exhaustion!")
        return True
    except Exception as e:
        end_time = time.time()
        duration = end_time - start_time
        print(
            f"[ERROR] Processing failed after {duration:.2f} seconds: {type(e).__name__}: {e}"
        )

        if "Memory" in str(e) or "too large" in str(e):
            print("[!] VULNERABILITY CONFIRMED: Resource exhaustion!")
            return True

    print("\n=== Test Complete ===")
    print(
        "If processing was slow or caused memory issues, DoS vulnerability confirmed."
    )
    print("The issue is in ToolCallRepairService._process_json_match method")
    print("which calls json.loads() without size validation.")

    return False


if __name__ == "__main__":
    vulnerability_confirmed = test_dos_vulnerability()

    if vulnerability_confirmed:
        print("\n[!] DOS VULNERABILITY CONFIRMED!")
        print("This needs to be fixed by adding size validation to _process_json_match")
        sys.exit(1)
    else:
        print("\n[OK] DoS vulnerability not detected in this test")
        sys.exit(0)
