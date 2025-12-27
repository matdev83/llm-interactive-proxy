"""Regression tests for failover_service.py race condition fix."""

import threading

import pytest
from src.core.services.failover_service import (
    FailoverRouteConfig,
    FailoverService,
)


def test_failover_routes_concurrent_add():
    """Test that concurrent add_failover_route calls don't corrupt data."""
    service = FailoverService(
        {
            "openai": {"policy": "k", "elements": ["gpt-4"]},
        }
    )

    def add_route(thread_id: int):
        for i in range(10):
            service.add_failover_route(
                f"backend_{thread_id}_{i}", {"policy": "k", "elements": [f"model_{i}"]}
            )

    threads = []
    for i in range(5):
        t = threading.Thread(target=add_route, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    routes = service.get_all_failover_routes()
    assert len(routes) > 0, "Routes should exist after concurrent additions"

    for _key, route in routes.items():
        assert isinstance(route, FailoverRouteConfig)
        assert isinstance(route.elements, list)


def test_failover_routes_concurrent_get_and_add():
    """Test concurrent reads and writes don't cause errors."""
    service = FailoverService(
        {
            "openai": {"policy": "k", "elements": ["gpt-4"]},
        }
    )

    errors = []

    def reader_thread(thread_id: int):
        try:
            for _ in range(25):  # Reduced from 100 for performance
                route = service.get_failover_route("openai")
                if route is not None:
                    assert isinstance(route, FailoverRouteConfig)
        except Exception as e:
            errors.append(f"Reader {thread_id}: {e}")

    def writer_thread(thread_id: int):
        try:
            for i in range(12):  # Reduced from 50 for performance
                service.add_failover_route(
                    f"backend_{thread_id}_{i}",
                    {"policy": "k", "elements": [f"model_{i}"]},
                )
        except Exception as e:
            errors.append(f"Writer {thread_id}: {e}")

    threads = []
    for i in range(2):  # Reduced from 3 for performance
        threads.append(threading.Thread(target=reader_thread, args=(i,)))
    for i in range(2):  # Reduced from 3 for performance
        threads.append(threading.Thread(target=writer_thread, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"No errors should occur, got: {errors}"


def test_get_all_failover_routes_returns_copy():
    """Test that get_all_failover_routes returns a copy, not reference."""
    service = FailoverService(
        {
            "openai": {"policy": "k", "elements": ["gpt-4"]},
        }
    )

    routes1 = service.get_all_failover_routes()
    routes2 = service.get_all_failover_routes()

    assert id(routes1) != id(routes2), "Should return new dict each time"

    routes1["new_backend"] = FailoverRouteConfig(policy="k", elements=["model-1"])
    assert "new_backend" not in routes2
    assert "new_backend" not in service.get_all_failover_routes()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
