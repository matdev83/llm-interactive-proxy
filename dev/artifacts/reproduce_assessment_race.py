"""
Reproduction script for race condition in Assessment domain models.

This script simulates concurrent access to SessionAssessmentState which
modifies mutable fields without lock protection.
"""

import asyncio
import sys

sys.path.insert(0, ".")

from src.core.domain.assessment import (
    AssessmentResult,
    SessionAssessmentState,
    ToolCallPattern,
)


async def test_session_state_concurrency():
    """Test concurrent modifications to SessionAssessmentState."""
    state = SessionAssessmentState(session_id="test-session")
    errors = []

    async def add_assessments(iter_id: int):
        try:
            for i in range(100):
                result = AssessmentResult(
                    reasoning=f"Test reasoning {i}",
                    confidence=0.5,
                    session_id="test-session",
                    turn_count=i,
                )
                state.add_assessment_result(result)
        except Exception as e:
            errors.append(f"Add task {iter_id}: {e}")

    async def increment_turns(iter_id: int):
        try:
            for i in range(100):
                state.increment_turn()
        except Exception as e:
            errors.append(f"Increment task {iter_id}: {e}")

    async def read_state(iter_id: int):
        try:
            for i in range(100):
                _ = state.turn_count
                _ = state.assessment_history
                _ = state.last_check_turn
        except Exception as e:
            errors.append(f"Read task {iter_id}: {e}")

    # Launch concurrent tasks
    tasks = []
    for i in range(5):
        tasks.append(asyncio.create_task(add_assessments(i)))
        tasks.append(asyncio.create_task(increment_turns(i)))
        tasks.append(asyncio.create_task(read_state(i)))

    await asyncio.gather(*tasks)

    if errors:
        print(f"RACE CONDITION DETECTED: {len(errors)} errors occurred")
        for err in errors[:5]:
            print(f"  - {err}")
        return True
    else:
        print("No errors detected (race condition may still exist)")
        return False


async def test_tool_call_pattern_concurrency():
    """Test concurrent modifications to ToolCallPattern."""
    pattern = ToolCallPattern(tool_name="test_tool", args_hash="hash123")
    errors = []

    async def increment_pattern(iter_id: int):
        try:
            for i in range(100):
                pattern.increment()
        except Exception as e:
            errors.append(f"Increment task {iter_id}: {e}")

    async def read_pattern(iter_id: int):
        try:
            for i in range(100):
                _ = pattern.count
                _ = pattern.last_seen
        except Exception as e:
            errors.append(f"Read task {iter_id}: {e}")

    # Launch concurrent tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(increment_pattern(i)))
        tasks.append(asyncio.create_task(read_pattern(i)))

    await asyncio.gather(*tasks)

    if errors:
        print(f"RACE CONDITION DETECTED in ToolCallPattern: {len(errors)} errors")
        for err in errors[:5]:
            print(f"  - {err}")
        return True
    else:
        print("No ToolCallPattern errors detected")
        return False


async def main():
    print("=" * 60)
    print("Testing Assessment domain models for race conditions")
    print("=" * 60)

    print("\n1. Testing SessionAssessmentState concurrent access...")
    result1 = await test_session_state_concurrency()

    print("\n2. Testing ToolCallPattern concurrent access...")
    result2 = await test_tool_call_pattern_concurrency()

    if result1 or result2:
        print("\n" + "=" * 60)
        print("RACE CONDITIONS FOUND - FIX REQUIRED")
        print("=" * 60)
        sys.exit(1)
    else:
        print("\n" + "=" * 60)
        print("No explicit errors (race conditions may still exist)")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
