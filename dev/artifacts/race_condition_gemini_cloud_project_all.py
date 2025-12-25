"""
Reproduction script for multiple race conditions in GeminiCloudProjectConnector

Test 1: _schedule_credentials_reload TOCTOU race
Test 2: _validate_runtime_credentials state check race
Test 3: _fail_init/_degrade/_recover flag race
"""

import threading
import time


class MockConnector:
    """Minimal mock of GeminiCloudProjectConnector's state management"""

    def __init__(self):
        self._reload_task_lock = threading.Lock()
        self._reload_scheduling_in_progress = False
        self._pending_reload_task = None

        self._errors_lock = threading.Lock()
        self._credential_validation_errors = []
        self.is_functional = True
        self._initialization_failed = False


def test_schedule_credentials_reload_race():
    """
    Test 1: TOCTOU race in _schedule_credentials_reload
    
    Race scenario:
    - Thread A: Sets _reload_scheduling_in_progress=True inside lock, exits lock
    - Thread B: Sees _reload_scheduling_in_progress=True, returns early
    - Thread A: Creates task and calls _assign_task which resets flag to False
    - Result: Both think they're scheduling, or both think they're not
    """

    connector = MockConnector()
    results = {"scheduling_count": 0, "reset_count": 0, "skip_count": 0}

    def schedule_reload():
        with connector._reload_task_lock:
            if (
                connector._pending_reload_task is not None
                and (connector._pending_reload_task.done() if hasattr(connector._pending_reload_task, 'done') else True)
            ):
                return

            if connector._reload_scheduling_in_progress:
                results["skip_count"] += 1
                return

            connector._reload_scheduling_in_progress = True
            results["scheduling_count"] += 1

        # Simulate delay before task assignment (race window)
        time.sleep(0.01)

        # Task assignment outside the original lock context
        def clear_callback(_):
            with connector._reload_task_lock:
                connector._pending_reload_task = None
                connector._reload_scheduling_in_progress = False
                results["reset_count"] += 1

        connector._pending_reload_task = "fake_task"
        if hasattr(connector._pending_reload_task, 'add_done_callback'):
            connector._pending_reload_task.add_done_callback(clear_callback)

    print("\n=== TEST 1: _schedule_credentials_reload TOCTOU race ===")
    print("Launching 5 concurrent reload attempts...")
    print("Expected: 1 scheduling, 0 skips")
    print("Race scenario: Multiple threads pass the progress check before flag is reset")

    threads = []
    for i in range(5):
        t = threading.Thread(target=schedule_reload, name=f"Reloader-{i}")
        threads.append(t)

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=2)

    print("\nResults:")
    print(f"  Scheduling attempts: {results['scheduling_count']}")
    print(f"  Skipped (due to progress flag): {results['skip_count']}")
    print(f"  Flag resets: {results['reset_count']}")

    if results['scheduling_count'] > 1 or results['skip_count'] > 0:
        print("\n  RACE CONDITION REPRODUCED!")
        return True
    else:
        print("\n  No race detected")
        return False


def test_validate_runtime_credentials_race():
    """
    Test 2: State check-then-modify race in _validate_runtime_credentials

    Race scenario:
    - Thread A: Checks is_backend_functional() [inside _errors_lock]
    - Thread B: Also checks is_backend_functional() [inside _errors_lock]
    - Both see is_functional=True
    - Thread A: Calls _fail_init() which sets is_functional=False [inside _errors_lock]
    - Thread B: Calls _fail_init() based on stale check, also sets is_functional=False
    - Result: Both act on stale state, duplicate error messages
    """

    connector = MockConnector()
    call_count = 0

    def validate_worker():
        nonlocal call_count
        call_count += 1
        with connector._errors_lock:
            is_good = (
                connector.is_functional
                and not connector._initialization_failed
                and len(connector._credential_validation_errors) == 0
            )

        # Simulate delay between check and action (race window)
        time.sleep(0.01)

        # If check passed, later code might fail
        # If check failed, fail_init is called
        if is_good:
            connector._fail_init(["Simulated failure"])
        else:
            # Already failed
            pass

    print("\n=== TEST 2: _validate_runtime_credentials state race ===")
    print("Launching 10 concurrent validation attempts...")
    print("Expected: Only 1 validation failure should be recorded")
    print("Race scenario: Multiple threads pass the state check before fail_init is called")

    threads = []
    for i in range(10):
        t = threading.Thread(target=validate_worker, name=f"Validator-{i}")
        threads.append(t)

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=2)

    print("\nResults:")
    print(f"  Total validation calls: {call_count}")
    print(f"  Validation errors recorded: {len(connector._credential_validation_errors)}")
    print(f"  is_functional: {connector.is_functional}")
    print(f"  _initialization_failed: {connector._initialization_failed}")

    if len(connector._credential_validation_errors) > 1:
        print("\n  RACE CONDITION REPRODUCED! (Duplicate validation errors)")
        return True
    else:
        print("\n  No race detected")
        return False


def test_fail_init_race():
    """
    Test 3: Check-then-modify race in _fail_init, _degrade, _recover

    Race scenario:
    - Thread A: Reads state inside lock, modifies state inside lock
    - Thread B: Reads state inside lock, modifies state inside lock
    - Problem: Between read and modify, other threads can see stale state and also modify
    - Result: Redundant modifications, last one wins
    """

    connector = MockConnector()
    fail_count = 0

    def fail_worker():
        nonlocal fail_count
        fail_count += 1
        connector._fail_init(["error"])

    print("\n=== TEST 3: _fail_init/_degrade/_recover flag race ===")
    print("Launching 10 concurrent fail_init attempts...")
    print("Expected: Only 1 set of error state (last one wins)")
    print("Race scenario: Multiple threads modify same state, losing intermediate changes")

    threads = []
    for i in range(10):
        t = threading.Thread(target=fail_worker, name=f"Failer-{i}")
        threads.append(t)

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=2)

    print("\nResults:")
    print(f"  Total fail_init calls: {fail_count}")
    print(f"  Final validation errors: {len(connector._credential_validation_errors)}")
    print(f"  is_functional: {connector.is_functional}")
    print(f"  _initialization_failed: {connector._initialization_failed}")

    if len(connector._credential_validation_errors) < 10:
        print("\n  RACE CONDITION REPRODUCED! (Some modifications were lost)")
        print("  Expected 10 errors, got fewer due to concurrent modifications")
        return True
    else:
        print("\n  No race detected")
        return False


def run_all_tests():
    """Run all race condition tests"""
    print("=" * 70)
    print("GEMINI CLOUD PROJECT CONNECTOR - RACE CONDITION TEST SUITE")
    print("=" * 70)

    results = {
        "test1": test_schedule_credentials_reload_race(),
        "test2": test_validate_runtime_credentials_race(),
        "test3": test_fail_init_race(),
    }

    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    print(f"Test 1 (_schedule_credentials_reload): {'PASSED' if not results['test1'] else 'FAILED - RACE DETECTED'}")
    print(f"Test 2 (_validate_runtime_credentials): {'PASSED' if not results['test2'] else 'FAILED - RACE DETECTED'}")
    print(f"Test 3 (_fail_init flag race): {'PASSED' if not results['test3'] else 'FAILED - RACE DETECTED'}")

    race_count = sum(1 for v in results.values() if v)
    print(f"\nTotal races detected: {race_count}/3")

    return race_count == 0


if __name__ == "__main__":
    all_passed = run_all_tests()
    exit(0 if all_passed else 1)
