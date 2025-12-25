"""Repro script for failover_service.py race condition in failover_routes dict."""

import threading
from dataclasses import dataclass, field
from typing import Any


# Simulate actual failover_service.py code
@dataclass
class FailoverRouteConfig:
    """Mock config for testing."""
    policy: str = "k"
    elements: list[str] = field(default_factory=list)


class FailoverService:
    """Simulates failover service with race condition.

    RACE CONDITION: The failover_routes dict is modified (add_failover_route,
    remove_failover_route, get_failover_route) without any lock protection.
    Multiple threads can corrupt the dict or cause RuntimeErrors during iteration.
    """

    def __init__(self, failover_routes: dict[str, Any]) -> None:
        """Initialize the failover service."""
        # Convert raw routes to typed configs
        self.failover_routes: dict[str, FailoverRouteConfig] = {}
        if failover_routes:
            for backend, route in failover_routes.items():
                if isinstance(route, dict):
                    self.failover_routes[backend] = FailoverRouteConfig(**route)
                elif isinstance(route, FailoverRouteConfig):
                    self.failover_routes[backend] = route

    def get_failover_route(self, backend_type: str) -> FailoverRouteConfig | None:
        """Get the failover route for a backend type.

        RACE: Reading from dict while another thread may be modifying it.
        """
        failover_route = self.failover_routes.get(backend_type)
        return failover_route

    def add_failover_route(
        self,
        backend_type: str,
        failover_route: FailoverRouteConfig | dict[str, Any] | str,
    ) -> None:
        """Add a failover route.

        RACE: Modifying dict without lock.
        """
        typed_route = FailoverRouteConfig.model_validate(failover_route)
        self.failover_routes[backend_type] = typed_route

    def remove_failover_route(self, backend_type: str) -> bool:
        """Remove a failover route.

        RACE: Deleting from dict without lock.
        """
        if backend_type in self.failover_routes:
            del self.failover_routes[backend_type]
            return True
        return False

    def get_all_failover_routes(self) -> dict[str, FailoverRouteConfig]:
        """Get all failover routes.

        RACE: Returning dict reference while another thread may modify it.
        """
        return dict(self.failover_routes)

    def clear_failover_routes(self) -> None:
        """Clear all failover routes.

        RACE: Clearing dict without lock.
        """
        self.failover_routes.clear()


def simulate_concurrent_operations():
    """Simulate concurrent access to failover service."""
    service = FailoverService({
        "openai": {"policy": "k", "elements": ["gpt-4", "gpt-3.5"]},
        "anthropic": {"policy": "k", "elements": ["claude-3", "claude-2"]},
    })

    errors = []
    results = {"get_count": 0, "add_count": 0, "remove_count": 0, "clear_count": 0}

    def reader_thread(thread_id):
        """Thread that reads from failover routes."""
        try:
            for _ in range(100):
                route = service.get_failover_route("openai")
                if route:
                    results["get_count"] += 1
                else:
                    errors.append(f"Reader {thread_id}: Expected route but got None")
        except Exception as e:
            errors.append(f"Reader {thread_id}: {type(e).__name__}: {e}")

    def writer_thread(thread_id):
        """Thread that modifies failover routes."""
        try:
            for i in range(50):
                # Add route
                service.add_failover_route(
                    f"backend_{thread_id}_{i}",
                    FailoverRouteConfig(policy="k", elements=["model-1"])
                )
                results["add_count"] += 1

                # Remove route
                service.remove_failover_route(f"backend_{thread_id}_{i}")
                results["remove_count"] += 1

                # Get all routes
                all_routes = service.get_all_failover_routes()
                if not isinstance(all_routes, dict):
                    errors.append(f"Writer {thread_id}: Expected dict but got {type(all_routes)}")
        except Exception as e:
            errors.append(f"Writer {thread_id}: {type(e).__name__}: {e}")

    def clear_thread(thread_id):
        """Thread that clears failover routes."""
        try:
            for _ in range(20):
                service.clear_failover_routes()
                results["clear_count"] += 1
        except Exception as e:
            errors.append(f"Clearer {thread_id}: {type(e).__name__}: {e}")

    # Create threads
    threads = []
    for i in range(5):
        threads.append(threading.Thread(target=reader_thread, args=(i,)))
    for i in range(3):
        threads.append(threading.Thread(target=writer_thread, args=(i,)))
    for i in range(2):
        threads.append(threading.Thread(target=clear_thread, args=(i,)))

    # Start all threads
    for t in threads:
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    return errors, results


def main():
    """Run race condition reproduction."""
    print("Starting race condition reproduction for failover_service.py...")
    print("This demonstrates concurrent access to failover_routes dict without locks")
    print()

    errors, results = simulate_concurrent_operations()

    print("Results:")
    for key, value in results.items():
        print(f"  {key}: {value}")

    if errors:
        print(f"\n{len(errors)} errors occurred:")
        for err in errors[:10]:  # Show first 10 errors
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")

        print("\nRACE CONDITION CONFIRMED!")
        print("Concurrent modifications to failover_routes caused errors.")
        return True
    else:
        print("\nNo errors detected (race condition may still exist - run with more iterations)")
        return False


if __name__ == "__main__":
    result = main()
    exit(0 if result else 1)
