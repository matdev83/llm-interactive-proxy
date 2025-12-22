#!/usr/bin/env python3
"""
Memory leak test for FileWatcher background task scheduling.

This test focuses on the FileWatcher.schedule_credentials_reload method
which may create tasks that don't get properly cleaned up.
"""

import asyncio
import gc
import sys
import threading
import time
from pathlib import Path
from unittest.mock import Mock

# Add src directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.connectors.gemini_base.file_watcher import FileWatcher, FileWatcherState


def test_file_watcher_task_leak():
    """Test if FileWatcher creates background tasks that aren't cleaned up."""
    
    print("Testing FileWatcher for potential memory leaks...")
    
    # Create mock callbacks
    async def mock_reload_callback():
        await asyncio.sleep(0.1)  # Simulate some async work
        print("  Reload callback executed")
    
    def mock_stop_callback():
        print("  Stop callback executed")
    
    # Test multiple rapid scheduling calls
    state = FileWatcherState()
    state.main_loop = asyncio.new_event_loop()
    
    initial_tasks = len(asyncio.all_tasks())
    print(f"Initial task count: {initial_tasks}")
    
    async def run_test():
        # Schedule multiple reload tasks rapidly
        for i in range(20):
            print(f"Scheduling reload {i+1}/20")
            FileWatcher.schedule_credentials_reload(
                state,
                mock_reload_callback,
                mock_stop_callback
            )
            # Small delay between schedules
            await asyncio.sleep(0.01)
        
        # Wait for all tasks to potentially complete
        await asyncio.sleep(2.0)
        
        # Check final task count
        final_tasks = len(asyncio.all_tasks())
        print(f"Final task count: {final_tasks}")
        print(f"Task increase: {final_tasks - initial_tasks}")
        
        if final_tasks > initial_tasks + 2:  # Allow some tolerance
            print("❌ MEMORY LEAK DETECTED: Tasks are accumulating!")
            return False
        else:
            print("✅ No significant task accumulation")
            return True
    
    # Run the test
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(run_test())
        loop.close()
        return result
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_state_object_leak():
    """Test if FileWatcherState objects retain references improperly."""
    
    print("\nTesting FileWatcherState for reference leaks...")
    
    states = []
    
    # Create many FileWatcherState objects
    for i in range(100):
        state = FileWatcherState()
        state.main_loop = asyncio.new_event_loop()
        state.pending_reload_task = Mock()
        states.append(state)
    
    print(f"Created {len(states)} FileWatcherState objects")
    
    # Clear references
    states.clear()
    gc.collect()
    
    # Check if objects were collected
    remaining_states = [obj for obj in gc.get_objects() 
                      if isinstance(obj, FileWatcherState)]
    
    if len(remaining_states) > 10:  # Allow some to remain temporarily
        print(f"❌ MEMORY LEAK DETECTED: {len(remaining_states)} FileWatcherState objects still exist!")
        return False
    else:
        print("✅ FileWatcherState objects properly cleaned up")
        return True


def main():
    """Main test function."""
    print("FileWatcher Memory Leak Tests")
    print("=" * 40)
    
    success1 = test_file_watcher_task_leak()
    success2 = test_state_object_leak()
    
    print("\n" + "=" * 40)
    if success1 and success2:
        print("✅ All tests passed - no memory leaks detected")
        return 0
    else:
        print("❌ Memory leaks detected!")
        return 1


if __name__ == "__main__":
    sys.exit(main())