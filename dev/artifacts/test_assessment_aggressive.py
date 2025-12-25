"""
More aggressive race condition test to detect lost updates.
"""
import asyncio
import sys
sys.path.insert(0, '.')

from src.core.domain.assessment import (
    SessionAssessmentState,
    AssessmentResult,
)


async def test_assessment_history_lost_updates():
    """Test for lost updates in assessment_history list."""
    state = SessionAssessmentState(session_id="test-session")
    total_expected = 0
    completion_tasks = []

    async def add_assessments(iter_id: int):
        nonlocal total_expected
        added = 0
        for i in range(100):
            result = AssessmentResult(
                reasoning=f"Test {iter_id}_{i}",
                confidence=0.5,
                session_id="test-session",
                turn_count=i,
            )
            state.add_assessment_result(result)
            added += 1
        total_expected += added
        print(f"Task {iter_id}: Added {added} assessments")

    async def track_completion(iter_id: int):
        """Track when tasks complete."""
        for i in range(100):
            count = state.len()
            completion_tasks.append(count)
            await asyncio.sleep(0.001)

    # Launch concurrent add tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(add_assessments(i)))

    # Launch a monitoring task
    tasks.append(asyncio.create_task(track_completion(0)))

    await asyncio.gather(*tasks)

    # Check for lost updates
    final_count = len(state.assessment_history)
    print(f"\nExpected: {total_expected} assessments")
    print(f"Actual: {final_count} assessments")
    print(f"Lost updates: {total_expected - final_count}")

    if final_count < total_expected:
        print("\nRACE CONDITION CONFIRMED: Lost updates detected!")
        print("This happens when concurrent list.append() calls race and overwrite each other")
        return True
    else:
        print("\nNo lost updates detected in this run")
        return False


async def test_turn_count_lost_updates():
    """Test for lost updates in turn_count."""
    state = SessionAssessmentState(session_id="test-session")
    total_increments = 0

    async def increment_turns(iter_id: int):
        nonlocal total_increments
        increments = 0
        for i in range(100):
            state.increment_turn()
            increments += 1
        total_increments += increments
        print(f"Task {iter_id}: Incremented {increments} times")

    # Launch concurrent increment tasks
    tasks = []
    for i in range(10):
        tasks.append(asyncio.create_task(increment_turns(i)))

    await asyncio.gather(*tasks)

    # Check for lost updates
    final_count = state.turn_count
    print(f"\nExpected: {total_increments} increments")
    print(f"Actual: {final_count} turns")
    print(f"Lost increments: {total_increments - final_count}")

    if final_count < total_increments:
        print("\nRACE CONDITION CONFIRMED: Lost updates in turn_count!")
        print("This happens when read-modify-write operations on turn_count race")
        return True
    else:
        print("\nNo lost increments detected in this run")
        return False


async def main():
    print("=" * 60)
    print("Aggressive Race Condition Tests for Assessment Models")
    print("=" * 60)

    print("\n1. Testing assessment_history list for lost updates...")
    result1 = await test_assessment_history_lost_updates()

    print("\n" + "=" * 60)
    print("2. Testing turn_count for lost updates...")
    print("=" * 60)
    result2 = await test_turn_count_lost_updates()

    if result1 or result2:
        print("\n" + "=" * 60)
        print("RACE CONDITIONS FOUND - FIX REQUIRED")
        print("=" * 60)
        sys.exit(1)
    else:
        print("\n" + "=" * 60)
        print("No lost updates detected in this run")
        print("(May need multiple runs to trigger race conditions)")
        print("=" * 60)
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
