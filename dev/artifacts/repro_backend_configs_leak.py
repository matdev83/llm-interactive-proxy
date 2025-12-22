"""
Repro script to test if _backend_configs in BackendLifecycleManager grows unbounded.

This script tests if backend configs accumulate without cleanup when backends
are accessed with different configs repeatedly.
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.core.services.backend_lifecycle_manager import BackendLifecycleManager
from src.core.config.app_config import BackendConfig


class MockFactory:
    """Mock factory for testing."""
    
    async def ensure_backend(self, backend_type, app_config, provider_backend_config):
        """Return a mock backend."""
        class MockBackend:
            def __init__(self, backend_type):
                self.backend_type = backend_type
        
        return MockBackend(backend_type)
    
    def unregister_backend_notifications(self, backend):
        pass
    
    def unregister_backend(self, cache_key):
        pass


class MockConfigProvider:
    """Mock config provider that returns configs."""
    
    def __init__(self):
        self._call_count = 0
    
    def get_backend_config(self, backend_type):
        """Return a config, incrementing call count."""
        self._call_count += 1
        # Return a config with unique data to simulate different configs
        return BackendConfig(
            type=backend_type,
            api_key=f"key_{self._call_count}",
        )


async def test_backend_configs_accumulation():
    """Test if _backend_configs accumulates without bounds."""
    print("Testing _backend_configs accumulation...")
    
    factory = MockFactory()
    config_provider = MockConfigProvider()
    manager = BackendLifecycleManager(
        factory=factory,
        backend_config_provider=config_provider,
        global_backend_limit=10,  # Small limit to force eviction
    )
    
    # Initial state
    initial_size = len(manager._backend_configs)
    print(f"Initial _backend_configs size: {initial_size}")
    
    # Access many different backend types with configs
    # This should trigger eviction and cleanup
    backend_types = [f"backend_{i}" for i in range(100)]
    
    for backend_type in backend_types:
        try:
            await manager.get_or_create(backend_type)
        except Exception as e:
            # Ignore errors, we're just testing accumulation
            pass
    
    # Check final size - should be bounded by the limit, not the number of backends accessed
    final_size = len(manager._backend_configs)
    print(f"Final _backend_configs size: {final_size}")
    print(f"Growth: {final_size - initial_size} entries")
    print(f"Backend limit: {manager._global_backend_limit}")
    print(f"Backends accessed: {len(backend_types)}")
    
    # Check if it grew unbounded - configs should be cleaned up when backends are evicted
    # So final size should be <= limit, not >= number of backend types
    if final_size > manager._global_backend_limit * 2:  # Allow some buffer for per-session backends
        print("[LEAK CONFIRMED] _backend_configs grew beyond reasonable limit")
        print(f"   {final_size} backend configs in memory (limit: {manager._global_backend_limit})")
        return True
    else:
        print("[OK] No leak detected: _backend_configs size is bounded")
        return False


async def test_disabled_backends_accumulation():
    """Test if _disabled_backends accumulates without bounds."""
    print("\nTesting _disabled_backends accumulation...")
    
    factory = MockFactory()
    manager = BackendLifecycleManager(factory=factory)
    
    # Initial state
    initial_size = len(manager._disabled_backends)
    print(f"Initial _disabled_backends size: {initial_size}")
    
    # Disable many different backend types
    backend_types = [f"backend_{i}" for i in range(1000)]
    
    for backend_type in backend_types:
        manager.discard(backend_type, None, f"Test reason for {backend_type}")
    
    # Check final size
    final_size = len(manager._disabled_backends)
    print(f"Final _disabled_backends size: {final_size}")
    print(f"Growth: {final_size - initial_size} entries")
    
    # Check if it grew unbounded
    if final_size >= len(backend_types):
        print("[LEAK CONFIRMED] _disabled_backends grew to match number of backend types")
        print(f"   All {len(backend_types)} disabled backend entries are still in memory")
        return True
    else:
        print("[OK] No leak detected: _disabled_backends size is bounded")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("BackendLifecycleManager Memory Leak Tests")
    print("=" * 60)
    
    configs_leak = await test_backend_configs_accumulation()
    disabled_leak = await test_disabled_backends_accumulation()
    
    print("\n" + "=" * 60)
    print("Summary:")
    print("=" * 60)
    
    if configs_leak:
        print("[LEAK] _backend_configs has a memory leak")
    else:
        print("[OK] _backend_configs is safe")
    
    if disabled_leak:
        print("[LEAK] _disabled_backends has a memory leak")
    else:
        print("[OK] _disabled_backends is safe")
    
    if configs_leak or disabled_leak:
        print("\n[WARNING] Memory leak(s) confirmed!")
        return 1
    else:
        print("\n[OK] No memory leaks detected")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
