"""Repro script for ToolCallRepairService._tool_call_buffers memory leak.

This script checks if _tool_call_buffers can grow unbounded.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from dev.artifacts.di_helper import get_tool_call_repair_service


def main():
    """Check if _tool_call_buffers can grow unbounded."""
    service = get_tool_call_repair_service()

    print("Checking ToolCallRepairService._tool_call_buffers...")
    print(f"Initial size: {len(service._tool_call_buffers)}")

    # Check if _tool_call_buffers is actually used
    # If it's never accessed, it might be dead code
    print(f"Buffer dict exists: {hasattr(service, '_tool_call_buffers')}")
    print(f"Buffer dict type: {type(service._tool_call_buffers)}")
    print(f"Buffer dict size: {len(service._tool_call_buffers)}")

    # Try to find where it's used
    print("\nNote: If _tool_call_buffers is never used, it's not a memory leak.")
    print("However, if it IS used and never cleaned up, it can grow unbounded.")


if __name__ == "__main__":
    main()
