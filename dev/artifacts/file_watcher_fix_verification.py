#!/usr/bin/env python3
"""
Test script to verify FileWatcher memory leak fix.
"""

import asyncio
import gc
import sys
import time
from pathlib import Path

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState


async def test_fixed_file_watcher():
    """Test that the fix prevents memory leaks."""
    
    print("Testing FileWatcher memory leak fix...")
    
    # Create mock callbacks
    reload_count = 0
    
    async def mock_reload_callback():
        nonlocal reload_count
        reload_count += 1
        await asyncio.sleep(0.05)  # Simulate async work
        if reload_count % 5 == 0:
            raise Exception("Simulated reload error")  # Test exception path
    
    def mock_stop_callback():
        pass
    
    # Create state and loop
    state = FileWatcherState()
    loop = asyncio.get_running_loop()
    state.main_loop = loop
    
    initial_tasks = len(asyncio.all_tasks())
    print(f"Initial task count: {initial_tasks}")
    
    try:
        # Schedule many reload tasks rapidly to test race conditions
        for i in range(30):
            print(f"Scheduling reload {i+1}/30")
            FileWatcher.schedule_credentials_reload(
                state,
                mock_reload_callback,
                mock_stop_callback
            )
            # Very small delay to create race conditions
            await asyncio.sleep(0.001)
        
        # Wait for tasks to complete
        await asyncio.sleep(3.0)
        
        # Check final task count
        final_tasks = len(asyncio.all_tasks())
        print(f"Final task count: {final_tasks}")
        print(f"Task increase: {final_tasks - initial_tasks}")
        print(f"Reloads executed: {reload_count}")
        
        # Test cleanup method directly
        state.cleanup_completed_task()
        
        # Allow some tolerance for system tasks
        if final_tasks <= initial_tasks + 5:
            print("✅ MEMORY LEAK FIXED: No significant task accumulation!")
            return True
        else:
            print("❌ MEMORY LEAK STILL EXISTS: Tasks are accumulating!")
            return False
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_error_handling():
    """Test error handling paths."""
    
    print("\nTesting error handling...")
    
    state = FileWatcherState()
    loop = asyncio.get_running_loop()
    state.main_loop = loop
    
    # Test with closed loop to trigger error path
    closed_loop = asyncio.new_event_loop()
    closed_loop.close()
    state.main_loop = closed_loop
    
    async def failing_callback():
        await asyncio.sleep(0.1)
    
    def stop_callback():
        pass
    
    try:
        FileWatcher.schedule_credentials_reload(
            state,
            failing_callback,
            stop_callback
        )
        await asyncio.sleep(0.5)
        
        # Check that state was cleaned up
        if state.pending_reload_task is None and not state.reload_scheduling_in_progress:
            print("✅ Error handling works correctly")
            return True
        else:
            print("❌ Error handling failed - state not cleaned up")
            return False
            
    except Exception as e:
        print(f"Error handling test failed: {e}")
        return False


async def main():
    """Main test function."""
    print("FileWatcher Memory Leak Fix Verification")
    print("=" * 50)
    
    test1_success = await test_fixed_file_watcher()
    test2_success = await test_error_handling()
    
    print("\n" + "=" * 50)
    if test1_success and test2_success:
        print("✅ ALL TESTS PASSED: Memory leak fix is working!")
        return 0
    else:
        print("❌ SOME TESTS FAILED: Fix needs more work")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))