#!/usr/bin/env python3
"""
Memory leak reproduction script for tool call reactor service.

This script tests potential memory leaks in the InMemoryToolCallHistoryTracker
by simulating many sessions with many tool calls.
"""

import asyncio
import os

# Add the src directory to the path
import sys
from datetime import datetime, timezone

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


async def test_memory_growth():
    """Test memory growth with many sessions and tool calls."""
    
    # Get initial memory usage
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Create the tracker with short TTL to test cleanup
    tracker = InMemoryToolCallHistoryTracker(
        session_ttl_seconds=60,  # 1 minute TTL
        max_sessions=1000
    )
    
    # Simulate many sessions with many tool calls
    num_sessions = 500
    calls_per_session = 1500  # More than the 1000 limit per session
    
    print(f"Creating {num_sessions} sessions with {calls_per_session} tool calls each...")
    
    for session_id in range(num_sessions):
        session_key = f"test_session_{session_id}"
        
        for call_id in range(calls_per_session):
            context = {
                "backend_name": "test_backend",
                "model_name": "test_model", 
                "calling_agent": "test_agent",
                "timestamp": datetime.now(timezone.utc),
                "tool_arguments": {"arg1": f"value_{call_id}", "arg2": f"data_{call_id}" * 10}
            }
            
            await tracker.record_tool_call(session_key, f"tool_{call_id}", context)
    
    # Measure memory after adding data
    after_memory = process.memory_info().rss / 1024 / 1024  # MB
    memory_growth = after_memory - initial_memory
    print(f"Memory after adding data: {after_memory:.2f} MB")
    print(f"Memory growth: {memory_growth:.2f} MB")
    
    # Check the internal state sizes
    print("\nInternal state:")
    print(f"Number of sessions tracked: {len(tracker._history)}")
    
    total_entries = 0
    for session_id, history in tracker._history.items():
        total_entries += len(history)
        if len(history) > 1000:
            print(f"Session {session_id} has {len(history)} entries (exceeds 1000 limit!)")
    
    print(f"Total tool call entries: {total_entries}")
    print(f"Expected maximum entries: {num_sessions * 1000}")
    
    # Wait for TTL to expire
    print("\nWaiting for TTL to expire...")
    await asyncio.sleep(65)  # Wait longer than TTL
    
    # Try to trigger cleanup by accessing data
    for session_id in range(10):  # Try to access some sessions
        await tracker.get_call_count(f"test_session_{session_id}", "tool_0", 3600)
    
    # Check if cleanup happened
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    print(f"\nMemory after TTL expiration: {final_memory:.2f} MB")
    print(f"Final memory growth: {final_memory - initial_memory:.2f} MB")
    print(f"Number of sessions tracked after cleanup: {len(tracker._history)}")
    
    # Memory is leaked if:
    # 1. Memory growth is significant (> 50MB for this test)
    # 2. Session count doesn't decrease after TTL
    # 3. Individual sessions have more than 1000 entries
    
    is_leaked = (
        (final_memory - initial_memory) > 50 or
        len(tracker._history) > 50 or  # Should be mostly cleared after TTL
        any(len(history) > 1000 for history in tracker._history.values())
    )
    
    if is_leaked:
        print("\n🚨 MEMORY LEAK DETECTED!")
        print("Evidence:")
        if (final_memory - initial_memory) > 50:
            print(f"  - Excessive memory growth: {final_memory - initial_memory:.2f} MB")
        if len(tracker._history) > 50:
            print(f"  - Sessions not cleaned up: {len(tracker._history)} remaining")
        if any(len(history) > 1000 for history in tracker._history.values()):
            print("  - Per-session limit exceeded")
    else:
        print("\n✅ No significant memory leak detected")
    
    return is_leaked

if __name__ == "__main__":
    asyncio.run(test_memory_growth())