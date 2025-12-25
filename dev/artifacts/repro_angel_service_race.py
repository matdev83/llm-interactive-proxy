"""Repro script for angel_service.py race condition in global _prompt_loader."""

import threading


# Simulate actual angel_service.py code structure
class MockAngelPromptLoader:
    """Mock prompt loader for testing."""
    def __init__(self):
        self.load_count = 0

    def load_prompts(self):
        self.load_count += 1


# Global variable (copy of actual code pattern)
_prompt_loader: MockAngelPromptLoader | None = None
_prompt_loader_lock = threading.Lock()


def get_prompt_loader_unsafe() -> MockAngelPromptLoader:
    """Get or initialize the global prompt loader instance.

    This is ACTUAL code from angel_service.py lines 20-26.
    RACE CONDITION: Multiple threads can enter the if block simultaneously.
    """
    global _prompt_loader
    if _prompt_loader is None:
        # RACE WINDOW: Between checking None and assigning, another thread can also check
        _prompt_loader = MockAngelPromptLoader()
        _prompt_loader.load_prompts()
    return _prompt_loader


def get_prompt_loader_safe() -> MockAngelPromptLoader:
    """Thread-safe version with lock protection."""
    global _prompt_loader
    with _prompt_loader_lock:
        if _prompt_loader is None:
            _prompt_loader = MockAngelPromptLoader()
            _prompt_loader.load_prompts()
    return _prompt_loader


def simulate_call_unsafe(index: int):
    """Simulate a call that accesses the unsafe global prompt loader."""
    loader = get_prompt_loader_unsafe()
    return loader.load_count


def simulate_call_safe(index: int):
    """Simulate a call that accesses the safe global prompt loader."""
    loader = get_prompt_loader_safe()
    return loader.load_count


def test_unsafe():
    """Test unsafe version for race condition."""
    global _prompt_loader
    _prompt_loader = None

    threads = []
    for i in range(100):
        t = threading.Thread(target=simulate_call_unsafe, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return _prompt_loader.load_count if _prompt_loader else 0


def test_safe():
    """Test safe version."""
    global _prompt_loader
    _prompt_loader = None

    threads = []
    for i in range(100):
        t = threading.Thread(target=simulate_call_safe, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return _prompt_loader.load_count if _prompt_loader else 0


def main():
    """Run race condition reproduction."""
    print("Starting race condition reproduction for angel_service.py...")
    print("This demonstrates the race condition in get_prompt_loader()")
    print()

    # Test unsafe version
    print("Testing UNSAFE version (no lock)...")
    unsafe_count = test_unsafe()
    print(f"Result: load_prompts() was called {unsafe_count} times")
    print("Expected: 1 time")
    print()

    if unsafe_count > 1:
        print("RACE CONDITION CONFIRMED!")
        print(f"Multiple initializations ({unsafe_count}) occurred due to lack of lock protection.")
        print()

        # Test safe version to show fix works
        print("Testing SAFE version (with lock)...")
        safe_count = test_safe()
        print(f"Result: load_prompts() was called {safe_count} times")
        print("Expected: 1 time")

        if safe_count == 1:
            print("\nLock protection successfully prevents race condition!")
            return True
    else:
        print("Race condition not detected with current thread count.")
        return False


if __name__ == "__main__":
    result = main()
    exit(0 if result else 1)
