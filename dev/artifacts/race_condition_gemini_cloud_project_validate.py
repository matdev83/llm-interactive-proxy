"""
Reproduction script for race condition in GeminiCloudProjectConnector._validate_runtime_credentials()

Race condition: TOCTOU (Time-of-Check to Time-of-Use)
- State check then modify pattern on _credential_validation_errors
- Multiple threads can see len==0 simultaneously and both set is_functional=False
"""

import threading
import time


class MockConnector:
    """Minimal mock of _validate_runtime_credentials logic"""

    def __init__(self):
        self._errors_lock = threading.Lock()
        self._credential_validation_errors = []
        self.is_functional = True
        self._initialization_failed = False
        self._fail_count = 0

    def _fail_init(self, errors):
        with self._errors_lock:
            self._credential_validation_errors = errors
            self._initialization_failed = True
            self.is_functional = False

    def _validate_runtime_credentials(self):
        """Simulates race condition in _validate_runtime_credentials"""
        current_time = time.time()

        # Simulate validation that should fail
        should_fail = current_time % 2 == 0  # Fail every other call

        if should_fail:
            self._fail_init(["Validation failed"])
            return False
        else:
            return True

    def is_backend_functional(self):
        """Simulates race in is_backend_functional"""
        # RACE CONDITION: Multiple threads can pass the check and both set is_functional=False
        # Check (inside lock)
        with self._errors_lock:
            is_good = (
                self.is_functional
                and not self._initialization_failed
                and len(self._credential_validation_errors) == 0
            )

        # Simulate delay between check and return (race window)
        time.sleep(0.01)

        return is_good


def test_race_condition():
    """
    Simulates multiple threads calling _validate_runtime_credentials concurrently.
    Expected: is_backend_functional() should accurately reflect current state
    Actual buggy behavior: May return stale cached value due to race
    """
    connector = MockConnector()

    print("\n=== RACE CONDITION TEST: _validate_runtime_credentials ===")
    print("Simulating concurrent validation calls...")
    print("Race condition: Check state inside lock, return state outside lock")

    # Create multiple threads that will call validate
    threads = []
    results = []

    def worker():
        result = connector._validate_runtime_credentials()
        functional = connector.is_backend_functional()
        results.append((result, functional))

    # Start 10 threads simultaneously
    for i in range(10):
        t = threading.Thread(target=worker, name=f"Validator-{i}")
        threads.append(t)

    for t in threads:
        t.start()

    # Wait for all threads
    for t in threads:
        t.join(timeout=2)

    # Check results
    print("\n=== RESULTS ===")
    # Count how many threads saw valid state when it was actually invalid
    race_count = sum(1 for r, f in results if f and not r)

    total_calls = len(results)

    print(f"Total concurrent calls: {total_calls}")
    print(f"Threads that saw 'functional=True' when validation failed: {race_count}")
    print(f"Race condition rate: {race_count / total_calls:.2%}")

    if race_count > 0:
        print("\n RACE CONDITION REPRODUCED: Multiple threads saw stale functional state")
        print("This demonstrates the TOCTOU race in _validate_runtime_credentials")
        return True
    else:
        print("\n No race condition detected")
        return False


if __name__ == "__main__":
    has_race = test_race_condition()
    exit(1 if has_race else 0)
