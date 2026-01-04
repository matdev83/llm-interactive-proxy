"""
Verification script that _TextToolCallMatcher leak is fixed.

This script imports the actual class from the source file.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Import the actual class - this will use the fixed version
from connectors._openai_codex_request_translator import _TextToolCallMatcher


def test_unbounded_growth_fixed():
    """Test that _pending doesn't grow beyond max limit."""
    matcher = _TextToolCallMatcher(max_pending=100)

    print(
        f"Initial state: _pending={len(matcher._pending)}, max_pending={matcher._max_pending}"
    )

    # Register many tool calls without matching them
    for i in range(1000):
        matcher.register(
            call_id=f"call_{i}", name=f"tool_{i}", command_text=f"command_{i}"
        )

        if (i + 1) % 200 == 0:
            print(f"After {i+1} registers: _pending={len(matcher._pending)}")

    print(f"\nAfter 1000 registers: _pending={len(matcher._pending)}")
    print("Expected: <= 100 (max_pending)")
    print(f"Actual: {len(matcher._pending)}")

    # Verify fix: _pending should be capped at max
    if len(matcher._pending) > matcher._max_pending:
        print("\n!!! MEMORY LEAK STILL EXISTS !!!")
        print(
            f"_pending ({len(matcher._pending)}) exceeds max ({matcher._max_pending})"
        )
        return False
    else:
        print(f"\n✓ Fix verified: _pending is capped at {matcher._max_pending}")
        return True


def main():
    """Run all tests."""
    success = test_unbounded_growth_fixed()

    if success:
        print("\n" + "=" * 60)
        print("MEMORY LEAK FIXED - VERIFIED!")
        print("=" * 60)
        sys.exit(0)
    else:
        print("\n" + "=" * 60)
        print("FIX INCOMPLETE")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    main()
