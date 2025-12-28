"""Test logging_utils security warnings thread safety."""

import concurrent.futures
import threading

from src.core.common.logging_utils import (
    _logged_security_warnings,
    _logged_warnings_lock,
)


def test_security_warnings_thread_safety() -> None:
    """Test that concurrent security warning checks don't corrupt the warnings set."""
    with _logged_warnings_lock:
        _logged_security_warnings.clear()
    errors = []

    def simulate_warning_check(warn_key: str, iterations: int) -> None:
        """Simulate the check-then-add pattern used in logging_utils."""
        for _ in range(iterations):
            try:
                # This mimics the pattern in _discover_api_keys_from_config_auth
                with _logged_warnings_lock:
                    if warn_key not in _logged_security_warnings:
                        # In real code, this is where logging happens
                        _logged_security_warnings.add(warn_key)
            except Exception as e:
                errors.append(e)

    # Use thread pool to simulate concurrent access
    warn_keys = [
        "auth.api_keys",
        "backends.openai.api_key",
        "backends.anthropic.api_key",
        "backends.gemini.api_key",
        "backends.openrouter.api_key",
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = []
        for key in warn_keys:
            # Submit multiple tasks per key to increase contention
            for i in range(20):
                future = executor.submit(simulate_warning_check, f"{key}.{i}", 5)
                futures.append(future)

        # Wait for all to complete
        concurrent.futures.wait(futures)

    # Verify no errors occurred
    assert len(errors) == 0, f"Errors occurred: {errors}"

    # Verify the set contains all expected keys (no duplicates lost due to races)
    with _logged_warnings_lock:
        final_warnings = _logged_security_warnings.copy()

    # All unique keys should be present
    expected_count = len(warn_keys) * 20
    assert (
        len(final_warnings) == expected_count
    ), f"Expected {expected_count} unique warnings, got {len(final_warnings)}"

    # Clear for other tests
    with _logged_warnings_lock:
        _logged_security_warnings.clear()


def test_concurrent_warning_additions() -> None:
    """Test that warning additions work correctly under high concurrency."""
    with _logged_warnings_lock:
        _logged_security_warnings.clear()

    def add_warning(batch_id: int) -> None:
        """Add a batch of warnings."""
        for i in range(100):
            warn_key = f"test.{batch_id}.{i}"
            with _logged_warnings_lock:
                if warn_key not in _logged_security_warnings:
                    _logged_security_warnings.add(warn_key)

    # Create 10 threads, each adding 100 unique warnings
    threads = []
    for batch_id in range(10):
        t = threading.Thread(target=add_warning, args=(batch_id,))
        threads.append(t)
        t.start()

    # Wait for all to complete
    for t in threads:
        t.join()

    # Verify all 1000 unique warnings are present
    with _logged_warnings_lock:
        final_count = len(_logged_security_warnings)

    assert final_count == 1000, f"Expected 1000 warnings, got {final_count}"

    # Clear for other tests
    with _logged_warnings_lock:
        _logged_security_warnings.clear()
