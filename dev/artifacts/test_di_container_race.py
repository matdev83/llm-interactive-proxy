"""
Reproduction script for DI container race condition in singleton/scoped instance caching.

Race Condition: Multiple concurrent get_service() calls for the same service
can create duplicate instances because there's no lock protecting the check-then-act
sequence in _get_service().
"""
import asyncio
import threading


class TestService:
    """Test service for demonstrating the race condition."""
    def __init__(self):
        self.id = id(self)
        print(f"Created TestService instance: {self.id}")


class SimpleServiceProvider:
    """Simplified version of ServiceProvider without locks to reproduce the race."""
    def __init__(self):
        self._singleton_instances = {}
        self._lock = None  # NO LOCK - simulating the bug
    
    def get_service_no_lock(self, service_type):
        """Get service WITHOUT lock - reproduces race condition."""
        # Thread-unsafe check-then-act pattern
        if service_type in self._singleton_instances:
            return self._singleton_instances[service_type]
        
        # Race condition window: two threads can both reach here
        instance = service_type()
        self._singleton_instances[service_type] = instance
        return instance


class ThreadSafeServiceProvider:
    """Fixed version with lock protection."""
    def __init__(self):
        self._singleton_instances = {}
        self._lock = threading.Lock()
    
    def get_service_with_lock(self, service_type):
        """Get service WITH lock - prevents race condition."""
        with self._lock:
            if service_type in self._singleton_instances:
                return self._singleton_instances[service_type]
            
            instance = service_type()
            self._singleton_instances[service_type] = instance
            return instance


async def test_race_condition_unsafe():
    """Test that demonstrates the race condition."""
    print("\n=== Testing UNSAFE implementation (no lock) ===")
    provider = SimpleServiceProvider()
    created_instances = []
    
    async def get_service(i):
        instance = provider.get_service_no_lock(TestService)
        created_instances.append(instance.id)
    
    # Launch 10 concurrent requests
    tasks = [get_service(i) for i in range(10)]
    await asyncio.gather(*tasks)
    
    unique_instances = len(set(created_instances))
    print(f"Total requests: {len(created_instances)}")
    print(f"Unique instances created: {unique_instances}")
    print(f"Instances: {created_instances}")
    
    if unique_instances > 1:
        print("❌ RACE CONDITION DETECTED: Multiple instances created for singleton service!")
    else:
        print("✓ No race condition detected (but unsafe code)")


async def test_race_condition_safe():
    """Test that demonstrates the fix with locks."""
    print("\n=== Testing SAFE implementation (with lock) ===")
    provider = ThreadSafeServiceProvider()
    created_instances = []
    
    async def get_service(i):
        # Use thread pool to test from multiple threads
        loop = asyncio.get_event_loop()
        instance = await loop.run_in_executor(None, provider.get_service_with_lock, TestService)
        created_instances.append(instance.id)
    
    # Launch 10 concurrent requests
    tasks = [get_service(i) for i in range(10)]
    await asyncio.gather(*tasks)
    
    unique_instances = len(set(created_instances))
    print(f"Total requests: {len(created_instances)}")
    print(f"Unique instances created: {unique_instances}")
    print(f"Instances: {created_instances}")
    
    if unique_instances == 1:
        print("✓ SAFE: Only one instance created for singleton service!")
    else:
        print("❌ Still has issues")


if __name__ == "__main__":
    print("DI Container Race Condition Reproduction")
    print("=" * 50)
    
    asyncio.run(test_race_condition_unsafe())
    asyncio.run(test_race_condition_safe())
    
    print("\n" + "=" * 50)
    print("Summary:")
    print("- Unsafe code can create multiple instances for singleton")
    print("- Safe code with lock ensures only one instance")
