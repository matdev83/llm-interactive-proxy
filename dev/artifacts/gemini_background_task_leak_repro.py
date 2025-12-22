#!/usr/bin/env python3
"""
Memory leak reproduction script for background tasks in gemini_base connector.

This script simulates scenario where background tasks might accumulate
without proper cleanup, potentially causing memory leaks.
"""

import asyncio
import gc
import os
import sys
import time
import tracemalloc
from pathlib import Path

# Add src directory to Python path
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from src.connectors.gemini_base.connector import GeminiOAuthPersonalConnector
from src.core.common.config import AppConfig


async def test_background_task_accumulation():
    """Test if background tasks accumulate without proper cleanup."""
    
    # Enable memory tracing
    tracemalloc.start()
    
    # Get initial memory snapshot
    snapshot1 = tracemalloc.take_snapshot()
    initial_tasks = len(asyncio.all_tasks())
    print(f"Initial asyncio tasks: {initial_tasks}")
    
    # Create multiple connector instances to simulate multiple reloads
    connectors = []
    
    for i in range(10):
        print(f"\nCreating connector {i+1}/10...")
        
        # Create connector with minimal config
        config = AppConfig({})
        connector = GeminiOAuthPersonalConnector(config=config)
        
        # Initialize to start background services
        try:
            await connector.initialize()
            connectors.append(connector)
            
            # Simulate credential reload attempts that create background tasks
            for j in range(5):
                try:
                    # This should trigger background task creation
                    await connector._handle_credentials_file_change()
                    print(f"  Connector {i+1}: Reload {j+1}/5 completed")
                except Exception as e:
                    print(f"  Connector {i+1}: Reload {j+1} failed: {e}")
                    
        except Exception as e:
            print(f"  Connector {i+1}: Initialization failed: {e}")
        
        # Check task count
        current_tasks = len(asyncio.all_tasks())
        print(f"  Current asyncio tasks: {current_tasks}")
        
        # Small delay to allow tasks to complete
        await asyncio.sleep(0.1)
    
    # Final task count
    final_tasks = len(asyncio.all_tasks())
    print(f"\nFinal asyncio tasks: {final_tasks}")
    print(f"Task increase: {final_tasks - initial_tasks}")
    
    # Check memory usage
    snapshot2 = tracemalloc.take_snapshot()
    top_stats = snapshot2.compare_to(snapshot1, 'lineno')
    
    print("\nTop memory allocations:")
    for stat in top_stats[:10]:
        print(f"  {stat}")
    
    # Try to clean up connectors
    print("\nCleaning up connectors...")
    for connector in connectors:
        try:
            # Attempt to shutdown file watching
            if hasattr(connector, '_stop_file_watching'):
                connector._stop_file_watching()
            
            # Clear background tasks if possible
            if hasattr(connector, '_background_tasks'):
                for task in connector._background_tasks:
                    if not task.done():
                        task.cancel()
                connector._background_tasks.clear()
                
        except Exception as e:
            print(f"  Cleanup error: {e}")
    
    # Force garbage collection
    gc.collect()
    await asyncio.sleep(0.5)
    
    # Final check
    final_tasks_after_cleanup = len(asyncio.all_tasks())
    print(f"\nTasks after cleanup: {final_tasks_after_cleanup}")
    print(f"Persistent tasks: {final_tasks_after_cleanup - initial_tasks}")
    
    # If tasks persist, we have a memory leak
    if final_tasks_after_cleanup > initial_tasks + 5:  # Allow some tolerance
        print("❌ MEMORY LEAK DETECTED: Background tasks are not being cleaned up properly!")
        return False
    else:
        print("✅ No significant memory leak detected in background tasks")
        return True


async def main():
    """Main test function."""
    print("Testing for background task memory leaks...")
    
    try:
        success = await test_background_task_accumulation()
        return 0 if success else 1
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)