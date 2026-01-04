import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.rate_limit import RateLimitRegistry


def test_leak():
    registry = RateLimitRegistry()

    print("Populating RateLimitRegistry with unique keys...")

    initial_size = len(registry._until)
    print(f"Initial size: {initial_size}")

    # Add 10,000 entries
    for i in range(10000):
        # Use unique keys
        registry.set("backend", "model", f"key_{i}", 3600)

    size_after = len(registry._until)
    print(f"Size after 10,000 adds: {size_after}")

    if size_after >= 10000:
        print("Confirmed: Registry grew to 10,000 entries.")

    # Simulate time passing (not really needed for growth check, but for cleanup check)
    # Even if they expire, 'set' doesn't clean them up.

    # Add 10,000 more
    for i in range(10000, 20000):
        registry.set("backend", "model", f"key_{i}", 1)  # Short TTL

    size_final = len(registry._until)
    print(f"Size after 20,000 adds: {size_final}")

    if size_final >= 20000:
        print("FAIL: Registry size is unbounded!")
        return True
    else:
        print("PASS: Registry size is bounded.")
        return False


if __name__ == "__main__":
    if test_leak():
        sys.exit(1)
    else:
        sys.exit(0)
