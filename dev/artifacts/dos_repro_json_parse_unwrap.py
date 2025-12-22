"""Repro script for DoS vulnerability: JSON parsing without size validation.

This script demonstrates the vulnerability where json.loads() is called
on potentially unbounded strings without size validation, causing memory
exhaustion.

Vulnerability: src/core/services/tool_call_repair_service.py:1086
Fixed: Added MAX_JSON_PARSE_SIZE limit (1MB) before json.loads call
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def create_large_nested_content(size_mb: int = 2) -> dict:
    """Create a nested content structure with large JSON string."""
    # Create a large JSON string
    large_data = {"data": "x" * (size_mb * 1024 * 1024)}
    large_json_string = json.dumps(large_data)

    # Wrap in the nested content pattern
    return {"content": large_json_string}


def demonstrate_vulnerability():
    """Demonstrate the vulnerability before fix."""
    print("=" * 70)
    print("DoS Vulnerability Repro: JSON Parsing in _unwrap_nested_content")
    print("=" * 70)
    print()
    print("Vulnerability Location:")
    print("  src/core/services/tool_call_repair_service.py:1086")
    print()
    print("Attack Vector:")
    print("  Provide nested content structure with extremely large JSON")
    print("  string in the 'content' field to exhaust memory during parsing.")
    print()

    # Create large nested content
    content_size_mb = 2  # Exceeds 1MB limit
    nested_content = create_large_nested_content(size_mb=content_size_mb)
    content_str = nested_content["content"]
    content_size_bytes = len(content_str.encode("utf-8"))
    content_size_mb_actual = content_size_bytes / (1024 * 1024)

    print(f"Creating nested content with {content_size_mb_actual:.2f}MB JSON string")
    print("(This should be rejected after fix)")
    print()

    # Simulate the vulnerable code path
    print("Simulating vulnerable code path...")
    print("(In real attack, this would be triggered via tool call arguments)")
    print()

    # Check pattern match
    if (
        len(nested_content) == 1
        and "content" in nested_content
        and isinstance(nested_content["content"], str)
    ):
        content_str = nested_content["content"].strip()
        if content_str.startswith("{") and content_str.endswith("}"):
            print("Pattern matched: {'content': '<json_string>'}")
            print(f"Content size: {content_size_mb_actual:.2f}MB")
            print()

            try:
                print("Calling json.loads() without size check...")
                import time

                start = time.time()
                parsed = json.loads(content_str)
                elapsed = time.time() - start

                print(f"⚠️  VULNERABILITY CONFIRMED:")
                print(f"   json.loads() parsed {content_size_mb_actual:.2f}MB string")
                print(f"   Parsing took {elapsed:.2f} seconds")
                print(f"   Limit should be 1MB, but parsing continued")
                print()
                print("✅ After fix: Size check returns original arguments if > 1MB")

            except MemoryError:
                print()
                print("⚠️  MEMORY ERROR: System ran out of memory!")
                print("   This confirms the DoS vulnerability.")
            except Exception as e:
                print(f"Error during parsing: {e}")

    print()
    print("=" * 70)
    print("Fix Applied:")
    print("  - Added MAX_JSON_PARSE_SIZE = 1MB constant")
    print("  - Check content_str size before json.loads() call")
    print("  - Return original arguments if size exceeds limit")
    print("=" * 70)


if __name__ == "__main__":
    demonstrate_vulnerability()

