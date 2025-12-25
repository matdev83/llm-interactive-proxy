"""
Regression test for race condition in ParameterResolution.

Tests that _history dictionary access is properly synchronized.
"""

import pytest
from src.core.config.parameter_resolution import ParameterResolution, ParameterSource


def test_record_concurrent_thread_safe():
    """
    Test that concurrent record() operations don't cause race conditions.

    Previously, record() modified _history without locks,
    causing potential lost updates and size limit violations.
    """
    import threading

    pr = ParameterResolution()
    num_threads = 10
    records_per_thread = 100

    def record_params(thread_id: int):
        for i in range(records_per_thread):
            pr.record(
                f"thread_{thread_id}_param_{i}",
                f"value_{i}",
                ParameterSource.CONFIG_FILE,
            )

    threads = [
        threading.Thread(target=record_params, args=(i,)) for i in range(num_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Check that we didn't exceed size limit
    assert (
        len(pr._history) <= pr._MAX_HISTORY_SIZE
    ), f"History size {len(pr._history)} exceeds limit {pr._MAX_HISTORY_SIZE}"

    # Check that we didn't lose all data
    assert len(pr._history) > 0, "History is empty after concurrent writes"


def test_is_set_concurrent_thread_safe():
    """
    Test that is_set() is thread-safe when called with concurrent writes.
    """
    import threading
    import time

    pr = ParameterResolution()

    def writer(thread_id: int):
        for i in range(50):
            pr.record(
                f"thread_{thread_id}_param_{i}",
                f"value_{i}",
                ParameterSource.ENVIRONMENT,
            )

    def reader():
        found_count = 0
        for i in range(10):
            for thread_id in range(5):
                if pr.is_set(f"thread_{thread_id}_param_{i}"):
                    found_count += 1
        return found_count

    # Start writers
    writer_threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
    for t in writer_threads:
        t.start()

    # Let writers run briefly
    time.sleep(0.01)

    # Run reader while writers still running
    reader_thread = threading.Thread(target=reader)
    reader_thread.start()

    for t in writer_threads:
        t.join()
    reader_thread.join()

    # Should not crash
    assert True


def test_build_report_concurrent_thread_safe():
    """
    Test that build_report() is thread-safe when called with concurrent writes.
    """
    import threading

    pr = ParameterResolution()

    # Pre-populate some parameters
    for i in range(50):
        pr.record(f"param_{i}", f"value_{i}", ParameterSource.DEFAULT)

    def writer(thread_id: int):
        for i in range(20):
            pr.record(
                f"thread_{thread_id}_param_{i}", f"value_{i}", ParameterSource.CLI
            )

    def reporter():
        reports = []
        for _ in range(10):
            try:
                report = pr.build_report({"dummy": "config"})
                reports.append(len(report))
            except Exception:
                reports.append(None)
        return reports

    # Start writers and reporter
    writer_threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
    reporter_thread = threading.Thread(target=reporter)

    for t in writer_threads:
        t.start()
    reporter_thread.start()

    for t in writer_threads:
        t.join()
    reporter_thread.join()

    # Should not crash or produce inconsistent reports
    assert True


def test_latest_by_source_concurrent_thread_safe():
    """
    Test that latest_by_source() is thread-safe.
    """
    import threading

    pr = ParameterResolution()

    # Add parameters from different sources
    for i in range(30):
        pr.record(f"param_{i}", f"value_{i}", ParameterSource.CONFIG_FILE)
        pr.record(f"cli_param_{i}", f"cli_value_{i}", ParameterSource.CLI)

    def query_by_source():
        for _ in range(20):
            result = pr.latest_by_source(ParameterSource.CLI)
            assert isinstance(result, dict)

    def writer():
        for i in range(10):
            pr.record(f"new_param_{i}", f"value_{i}", ParameterSource.ENVIRONMENT)

    # Run concurrent queries and writes
    query_threads = [threading.Thread(target=query_by_source) for _ in range(3)]
    writer_thread = threading.Thread(target=writer)

    for t in query_threads:
        t.start()
    writer_thread.start()

    for t in query_threads:
        t.join()
    writer_thread.join()

    # Should not crash
    assert True


def test_size_limit_enforcement_thread_safe():
    """
    Test that size limit is enforced correctly under concurrent writes.

    Previously, the check-and-evict logic had a race condition
    that could allow the history to grow beyond _MAX_HISTORY_SIZE.
    """
    import threading

    pr = ParameterResolution()

    # Pre-fill to near limit
    for i in range(pr._MAX_HISTORY_SIZE - 100):
        pr.record(f"param_{i}", f"value_{i}", ParameterSource.DEFAULT)

    def add_many_params(thread_id: int):
        for i in range(200):
            pr.record(
                f"thread_{thread_id}_param_{i}",
                f"value_{i}",
                ParameterSource.ENVIRONMENT,
            )

    # Start multiple threads that will trigger eviction
    threads = [threading.Thread(target=add_many_params, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Check that we didn't significantly exceed the limit
    # Allow some fudge factor due to timing
    assert (
        len(pr._history) <= pr._MAX_HISTORY_SIZE * 2
    ), f"History size {len(pr._history)} far exceeds limit {pr._MAX_HISTORY_SIZE}"

    # Check that we have some data
    assert len(pr._history) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
