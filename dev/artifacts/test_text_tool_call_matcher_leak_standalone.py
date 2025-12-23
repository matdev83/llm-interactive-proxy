"""
Reproduction script for _TextToolCallMatcher memory leak.

The _pending list grows unbounded because:
1. register() appends to _pending
2. match_textual_result() only pops when a match is found
3. If tool calls are never matched, entries accumulate indefinitely
4. No size limit, no cleanup, no TTL

This is a standalone version that doesn't need imports.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TextToolResult:
    canonical_name: str
    command_text: str
    output_text: str


@dataclass(frozen=True, slots=True)
class _PendingToolCallRecord:
    id: str
    name: str
    command_text: str


def _normalize_command_text(command_text: str | None) -> str:
    if not command_text:
        return ""
    return " ".join(str(command_text).split())


class _TextToolCallMatcher:
    def __init__(self) -> None:
        self._pending: list[_PendingToolCallRecord] = []

    def register(self, call_id: str, name: str, command_text: str | None) -> None:
        self._pending.append(
            _PendingToolCallRecord(
                id=call_id,
                name=(name or "").lower(),
                command_text=_normalize_command_text(command_text),
            )
        )

    def match_textual_result(
        self, result: TextToolResult
    ) -> _PendingToolCallRecord | None:
        normalized_name = (result.canonical_name or "").lower()
        normalized_command = _normalize_command_text(result.command_text)

        for idx, record in enumerate(self._pending):
            if record.name != normalized_name:
                continue
            if (
                normalized_command
                and record.command_text
                and record.command_text != normalized_command
            ):
                continue
            return self._pending.pop(idx)

        if self._pending:
            return self._pending.pop(0)
        return None


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
    print(f"Expected: 0 (if matched) or small (if unmatched)")
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


def test_name_mismatch_still_leaks():
    """
    Test that name mismatches cause leaks.

    If names don't match, entries are never removed.
    """
    matcher = _TextToolCallMatcher()

    print("\n" + "="*60)
    print("Test: Name mismatches cause leaks")
    print("="*60)

    # Register tool calls with one name
    for i in range(100):
        matcher.register(
            call_id=f"call_{i}",
            name="execute_command",  # Same name
            command_text=f"command_{i}"
        )

    # Try to match with different name
    result = TextToolResult(
        canonical_name="run_shell",  # Different name - won't match
        command_text="command_0",
        output_text="output"
    )
    matcher.match_textual_result(result)

    print(f"Registered 100 tool calls, tried 1 mismatch")
    print(f"_pending size: {len(matcher._pending)}")
    print(f"Expected: 0 (if matched) or close to 100 (if mismatched)")
    print(f"Actual: {len(matcher._pending)}")

    if len(matcher._pending) > 90:
        print(f"\n!!! MEMORY LEAK DETECTED !!!")
        print(f"_pending ({len(matcher._pending)}) has accumulated all entries")
        print(f"Name mismatches prevent removal")
        return True

    return False


def main():
    """Run all tests."""
    leak_detected = False

    leak_detected |= test_unbounded_pending_growth()
    leak_detected |= test_partial_match_still_leaks()
    leak_detected |= test_name_mismatch_still_leaks()

    if leak_detected:
        print("\n" + "="*60)
        print("MEMORY LEAK CONFIRMED!")
        print("="*60)
        print("\nFix: Add max_size parameter and enforce limit in register()")
        print("     Clear _pending in constructor")
        import sys
        sys.exit(1)
    else:
        print("\nNo memory leak detected")
        import sys
        sys.exit(0)


if __name__ == "__main__":
    main()
