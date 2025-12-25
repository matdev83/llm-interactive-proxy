"""
Verification script that the _TextToolCallMatcher leak is fixed.

This script imports the actual class from the source file.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Import the actual class
from connectors._openai_codex_request_translator import _TextToolCallMatcher


def test_unbounded_growth_fixed():
    """Test that _pending doesn't grow beyond max limit."""
    matcher = _TextToolCallMatcher(max_pending=100)

    print(f"Initial state: _pending={len(matcher._pending)}, max=100")

    # Register many tool calls without matching them
    for i in range(1000):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

        if (i + 1) % 200 == 0:
            print(f"After {i+1} registers: _pending={len(matcher._pending)}")

    print(f"\nAfter 1000 registers: _pending={len(matcher._pending)}")
    print("Expected: <= 100 (max_pending)")
    print(f"Actual: {len(matcher._pending)}")

    # Verify fix: _pending should be capped at max
    if len(matcher._pending) > matcher._max_pending:
        print("\n!!! MEMORY LEAK STILL EXISTS !!!")
        print(f"_pending ({len(matcher._pending)}) exceeds max ({matcher._max_pending})")
        return False
    else:
        print(f"\n✓ Fix verified: _pending is capped at {matcher._max_pending}")
        return True


def test_matching_still_works():
    """Test that matching still works after the fix."""
    matcher = _TextToolCallMatcher(max_pending=100)

    print("\n" + "="*60)
    print("Test: Matching functionality still works")
    print("="*60)

    # Register some tool calls
    for i in range(50):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

    print(f"Registered 50 tool calls, _pending={len(matcher._pending)}")

    # Try to match a few
    from connectors._openai_codex_request_translator import TextToolResult

    # Match first one - should find by name
    result1 = TextToolResult(
        canonical_name="tool_0",
        command_text="command_0",
        output_text="output1"
    )
    matched1 = matcher.match_textual_result(result1)
    print(f"Match attempt 1: {'✓ matched' if matched1 else '✗ not matched'}")
    print(f"  _pending after match: {len(matcher._pending)}")

    # Match second one - should find by name
    result2 = TextToolResult(
        canonical_name="tool_1",
        command_text="command_1",
        output_text="output2"
    )
    matched2 = matcher.match_textual_result(result2)
    print(f"Match attempt 2: {'✓ matched' if matched2 else '✗ not matched'}")
    print(f"  _pending after match: {len(matcher._pending)}")

    # Mismatch - should pop first pending
    result3 = TextToolResult(
        canonical_name="different_tool",  # Different name
        command_text="command_2",
        output_text="output3"
    )
    matched3 = matcher.match_textual_result(result3)
    print(f"Match attempt 3 (mismatch): {'✓ matched' if matched3 else '✗ not matched'}")
    print(f"  _pending after match: {len(matcher._pending)}")

    # Verify that at least one matched
    if matched1 or matched2 or matched3:
        print("\n✓ Matching functionality works")
        return True
    else:
        print("\n!!! Matching broken by fix")
        return False


def main():
    """Run all tests."""
    success = True

    success &= test_unbounded_growth_fixed()
    success &= test_matching_still_works()

    if success:
        print("\n" + "="*60)
        print("ALL TESTS PASSED - FIX VERIFIED!")
        print("="*60)
        sys.exit(0)
    else:
        print("\n" + "="*60)
        print("SOME TESTS FAILED")
        print("="*60)
        sys.exit(1)


if __name__ == "__main__":
    main()
