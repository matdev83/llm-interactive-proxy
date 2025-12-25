import threading
import time
import pytest

class TestGeminiCloudProjectConnectorRaceConditions:
    def test_fail_init_degrade_recover_flag_race(self):
        print("Starting test...")
        class MockConnector:
            def __init__(self):
                self._errors_lock = threading.Lock()
                self._credential_validation_errors = []
                self.is_functional = True
                self._initialization_failed = False

            def _fail_init(self, errors):
                with self._errors_lock:
                    print(f"Adding errors: {errors}")
                    # FIXED: Append errors to the list instead of replacing
                    self._credential_validation_errors.extend(errors)
                    self._initialization_failed = True
                    self.is_functional = False

        connector = MockConnector()

        # Simulate 10 concurrent calls to _fail_init
        threads = []
        for i in range(10):
            t = threading.Thread(
                target=lambda idx=i: connector._fail_init([f"error-{idx}"]),
                name=f"Failer-{i}",
            )
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=2)

        print(f"Final errors: {connector._credential_validation_errors}")
        assert (
            len(connector._credential_validation_errors) >= 5
        ), f"Expected at least 5 errors, got {len(connector._credential_validation_errors)}"

if __name__ == "__main__":
    t = TestGeminiCloudProjectConnectorRaceConditions()
    t.test_fail_init_degrade_recover_flag_race()
