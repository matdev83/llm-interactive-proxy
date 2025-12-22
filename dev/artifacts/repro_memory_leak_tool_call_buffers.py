"""
Repro script to confirm memory leak in ToolCallRepairService._tool_call_buffers.

Issue: _tool_call_buffers is initialized but never used (dead code).
If it were used, it would accumulate buffers per session without cleanup.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dev.artifacts.di_helper import get_tool_call_repair_service


def test_unused_buffers():
    """Test that _tool_call_buffers is never used."""
    service = get_tool_call_repair_service()

    print(f"_tool_call_buffers initialized: {service._tool_call_buffers is not None}")
    print(f"Initial _tool_call_buffers size: {len(service._tool_call_buffers)}")

    # Try various operations that might use buffers
    result1 = service.repair_tool_calls(
        '{"function_call": {"name": "test", "arguments": "{}"}}'
    )
    result2 = service.repair_tool_calls("<test_tool>content</test_tool>")
    result3 = service.repair_tool_calls_in_messages(
        [{"role": "assistant", "content": "<test>args</test>"}]
    )

    final_size = len(service._tool_call_buffers)
    print(f"After operations: _tool_call_buffers size={final_size}")

    if final_size == 0:
        print("[WARNING] DEAD CODE CONFIRMED: _tool_call_buffers is never used")
        return True
    else:
        print("[OK] _tool_call_buffers is being used")
        return False


def main():
    """Run test."""
    print("=" * 70)
    print("Memory Leak Repro: ToolCallRepairService Buffers")
    print("=" * 70)

    dead_code_confirmed = test_unused_buffers()

    print("\n" + "=" * 70)
    print("Summary:")
    print("=" * 70)
    if dead_code_confirmed:
        print("[WARNING] DEAD CODE CONFIRMED: _tool_call_buffers is never used")
    else:
        print("[OK] _tool_call_buffers is being used")

    return dead_code_confirmed


if __name__ == "__main__":
    result = main()
    sys.exit(1 if result else 0)
