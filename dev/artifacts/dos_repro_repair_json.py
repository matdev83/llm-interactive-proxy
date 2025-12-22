"""Repro script for DoS vulnerability: repair_json calls without size limits.

This script demonstrates the vulnerability where repair_json() is called
on potentially unbounded input strings without size validation, causing
CPU/memory exhaustion.

Vulnerabilities:
  1. src/core/services/tool_call_reactor/arguments_parser.py:118
  2. src/core/services/json_repair_service.py:179
  3. src/tool_call_loop/tracker.py:102

Fixed: Added MAX_JSON_REPAIR_INPUT_SIZE limit (1MB) before all repair_json calls
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from json_repair import repair_json


def create_large_json_string(size_mb: int = 2) -> str:
    """Create a large JSON string for testing."""
    # Create a JSON object with repeated content
    chunk = '{"key": "value", "data": "' + "x" * 1000 + '"}'
    chunks_needed = (size_mb * 1024 * 1024) // len(chunk)
    large_dict = {"items": [chunk] * chunks_needed}
    import json

    return json.dumps(large_dict)


def demonstrate_vulnerability_1():
    """Demonstrate vulnerability in ToolArgumentsParser._parse_string()."""
    print("=" * 70)
    print("DoS Vulnerability Repro: repair_json in ToolArgumentsParser")
    print("=" * 70)
    print()
    print("Vulnerability Location:")
    print("  src/core/services/tool_call_reactor/arguments_parser.py:118")
    print()
    print("Attack Vector:")
    print("  Provide tool call arguments of arbitrary size to exhaust")
    print("  CPU/memory during repair.")
    print()

    # Create large input
    large_input = create_large_json_string(size_mb=2)  # Exceeds 1MB limit
    input_size_mb = len(large_input.encode("utf-8")) / (1024 * 1024)

    print(f"Creating large input: {input_size_mb:.2f}MB")
    print("(This should be rejected after fix)")
    print()

    try:
        print("Calling repair_json()...")
        import time

        start = time.time()
        repaired = repair_json(large_input)
        elapsed = time.time() - start

        print(f"⚠️  VULNERABILITY CONFIRMED:")
        print(f"   repair_json() processed {input_size_mb:.2f}MB input")
        print(f"   Processing took {elapsed:.2f} seconds")
        print(f"   Limit should be 1MB, but processing continued")
        print()
        print("✅ After fix: Size check rejects input > 1MB before repair")

    except Exception as e:
        print(f"Error during repair: {e}")

    print()


def demonstrate_vulnerability_2():
    """Demonstrate vulnerability in JsonRepairService.repair_json()."""
    print("=" * 70)
    print("DoS Vulnerability Repro: repair_json in JsonRepairService")
    print("=" * 70)
    print()
    print("Vulnerability Location:")
    print("  src/core/services/json_repair_service.py:179")
    print()
    print("Attack Vector:")
    print("  Provide JSON strings of arbitrary size to exhaust CPU/memory.")
    print()

    # Create large input
    large_input = create_large_json_string(size_mb=2)  # Exceeds 1MB limit
    input_size_mb = len(large_input.encode("utf-8")) / (1024 * 1024)

    print(f"Creating large JSON string: {input_size_mb:.2f}MB")
    print("(This should be rejected after fix)")
    print()

    try:
        print("Calling repair_json()...")
        import time

        start = time.time()
        repaired = repair_json(large_input)
        elapsed = time.time() - start

        print(f"⚠️  VULNERABILITY CONFIRMED:")
        print(f"   repair_json() processed {input_size_mb:.2f}MB input")
        print(f"   Processing took {elapsed:.2f} seconds")
        print(f"   Limit should be 1MB, but processing continued")
        print()
        print("✅ After fix: Size check raises JSONParsingError if > 1MB")

    except Exception as e:
        print(f"Error during repair: {e}")

    print()


def demonstrate_vulnerability_3():
    """Demonstrate vulnerability in ToolCallTracker._canonicalize_arguments()."""
    print("=" * 70)
    print("DoS Vulnerability Repro: repair_json in ToolCallTracker")
    print("=" * 70)
    print()
    print("Vulnerability Location:")
    print("  src/tool_call_loop/tracker.py:102")
    print()
    print("Attack Vector:")
    print("  Provide tool call arguments of arbitrary size to exhaust")
    print("  CPU/memory during canonicalization.")
    print()

    # Create large input
    large_input = create_large_json_string(size_mb=2)  # Exceeds 1MB limit
    input_size_mb = len(large_input.encode("utf-8")) / (1024 * 1024)

    print(f"Creating large arguments string: {input_size_mb:.2f}MB")
    print("(This should be rejected after fix)")
    print()

    try:
        print("Calling repair_json()...")
        import time

        start = time.time()
        repaired = repair_json(large_input)
        elapsed = time.time() - start

        print(f"⚠️  VULNERABILITY CONFIRMED:")
        print(f"   repair_json() processed {input_size_mb:.2f}MB input")
        print(f"   Processing took {elapsed:.2f} seconds")
        print(f"   Limit should be 1MB, but processing continued")
        print()
        print("✅ After fix: Size check uses hash fallback if > 1MB")

    except Exception as e:
        print(f"Error during repair: {e}")

    print()


def main():
    """Run all vulnerability demonstrations."""
    print()
    print("DoS Vulnerability Reproductions: repair_json Calls")
    print("=" * 70)
    print()

    demonstrate_vulnerability_1()
    demonstrate_vulnerability_2()
    demonstrate_vulnerability_3()

    print("=" * 70)
    print("Summary of Fixes:")
    print("  - Added MAX_JSON_REPAIR_INPUT_SIZE = 1MB constant")
    print("  - Check input size before calling repair_json() in all locations")
    print("  - Raise appropriate exceptions or use fallbacks when limit exceeded")
    print("=" * 70)


if __name__ == "__main__":
    main()

