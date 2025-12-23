"""
Reproduction script for _TextToolCallMatcher memory leak.

The _pending list grows unbounded because:
1. register() appends to _pending
2. match_textual_result() only pops when a match is found
3. If tool calls are never matched, entries accumulate indefinitely
4. No size limit, no cleanup, no TTL
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from connectors._openai_codex_request_translator import _TextToolCallMatcher


def test_unbounded_pending_growth():
    """Test that demonstrates unbounded growth of _pending list."""
    matcher = _TextToolCallMatcher()

    print(f"Initial state: _pending={len(matcher._pending)}")

    # Register many tool calls without matching them
    for i in range(1000):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

        if (i + 1) % 100 == 0:
            print(f"After {i+1} registers: _pending={len(matcher._pending)}")

    print(f"\nAfter 1000 registers: _pending={len(matcher._pending)}")
    print(f"Expected: small number or zero (if matched)")
    print(f"Actual: {len(matcher._pending)}")

    # Verify leak: _pending should not grow unbounded
    if len(matcher._pending) > 100:
        print(f"\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_pending ({len(matcher._pending)}) grows unbounded")
        print(f"This happens because unmatched tool calls never get removed")
        return True

    return False


def test_partial_match_still_leaks():
    """
    Test that partial matching still causes leaks.

    Even with some matches, unmatched entries accumulate.
    """
    matcher = _TextToolCallMatcher()

    print("\n" + "="*60)
    print("Test: Partial matching still causes growth")
    print("="*60)

    # Register 100 tool calls, only match half of them
    for i in range(100):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

        # Match every other tool call
        if i % 2 == 0:
            from connectors._openai_codex_request_translator import TextToolResult
            result = TextToolResult(
                canonical_name=f"tool_{i}",
                command_text=f"command_{i}",
                output_text="output"
            )
            matcher.match_textual_result(result)

    print(f"Registered 100 tool calls, matched 50")
    print(f"_pending size: {len(matcher._pending)}")
    print(f"Expected: 0 (all matched) or small (unmatched)")
    print(f"Actual: {len(matcher._pending)}")

    if len(matcher._pending) > 50:
        print(f"\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_pending ({len(matcher._pending)}) is larger than expected")
        print(f"Unmatched tool calls are never cleaned up")
        return True

    return False


def main():
    """Run all tests."""
    leak_detected = False

    leak_detected |= test_unbounded_pending_growth()
    leak_detected |= test_partial_match_still_leaks()

    if leak_detected:
        print("\n" + "="*60)
        print("MEMORY LEAK CONFIRMED!")
        print("="*60)
        sys.exit(1)
    else:
        print("\nNo memory leak detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
