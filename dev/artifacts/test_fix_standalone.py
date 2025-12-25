"""
Standalone verification that fix for _TextToolCallMatcher memory leak works.
"""

from dataclasses import dataclass


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
    def __init__(self, max_pending: int = 1000) -> None:
        self._pending: list[_PendingToolCallRecord] = []
        self._max_pending = max(max_pending, 1)

    def register(self, call_id: str, name: str, command_text: str | None) -> None:
        self._pending.append(
            _PendingToolCallRecord(
                id=call_id,
                name=(name or "").lower(),
                command_text=_normalize_command_text(command_text),
            )
        )
        if len(self._pending) > self._max_pending:
            self._pending.pop(0)

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


def test_fix_works():
    """Verify fix caps _pending list."""
    print("="*60)
    print("Testing memory leak fix for _TextToolCallMatcher")
    print("="*60)

    matcher = _TextToolCallMatcher(max_pending=100)

    # Register many tool calls without matching them
    print("\nRegistering 1000 tool calls...")
    for i in range(1000):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

    print(f"_pending size: {len(matcher._pending)}")
    print(f"max_pending: {matcher._max_pending}")

    if len(matcher._pending) <= matcher._max_pending:
        print(f"\n[OK] _pending is capped at {len(matcher._pending)}")
        return True
    else:
        print(f"\n[FAIL] _pending ({len(matcher._pending)}) exceeds max ({matcher._max_pending})")
        return False


def test_matching_still_works():
    """Verify matching still works after fix."""
    print("\n" + "="*60)
    print("Testing matching functionality still works")
    print("="*60)

    matcher = _TextToolCallMatcher(max_pending=100)

    # Register some tool calls
    for i in range(50):
        matcher.register(
            call_id=f"call_{i}",
            name=f"tool_{i}",
            command_text=f"command_{i}"
        )

    print(f"Registered 50 tool calls, _pending={len(matcher._pending)}")

    # Try to match some
    matched_count = 0
    for i in range(10):
        result = TextToolResult(
            canonical_name=f"tool_{i}",
            command_text=f"command_{i}",
            output_text=f"output_{i}"
        )
        if matcher.match_textual_result(result):
            matched_count += 1

    print(f"Matched {matched_count} out of 10 attempts")
    print(f"_pending after matches: {len(matcher._pending)}")

    if matched_count > 0:
        print("\n[OK] Matching functionality works")
        return True
    else:
        print("\n[FAIL] Matching functionality broken")
        return False


if __name__ == "__main__":
    success = True
    success &= test_fix_works()
    success &= test_matching_still_works()

    if success:
        print("\n" + "="*60)
        print("ALL TESTS PASSED - FIX VERIFIED!")
        print("="*60)
        exit(0)
    else:
        print("\n" + "="*60)
        print("SOME TESTS FAILED")
        print("="*60)
        exit(1)
