#!/usr/bin/env python3
"""
Test the fixed memory management in InMemoryToolCallHistoryTracker.
"""

import asyncio
import os

# Add src directory to path
import sys

import psutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker


async def test_fixed_memory_management():
    """Test that memory growth is now controlled."""
    
    # Get initial memory usage
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Create tracker with new limits
    tracker = InMemoryToolCallHistoryTracker(
        session_ttl_seconds=10,  # 10 seconds TTL
        max_sessions=500,       # Reduced max sessions
        max_entries_per_session=50  # New parameter - much lower than 1000
    )
    
    # Simulate many sessions with many tool calls
    num_sessions = 600  # More than max_sessions to test eviction
    calls_per_session = 100  # More than per-session limit to test truncation
    
    print(f"Creating {num_sessions} sessions with {calls_per_session} tool calls each...")
    
    for session_id in range(num_sessions):
        session_key = f"test_session_{session_id}"
        
        for call_id in range(calls_per_session):
            context = {
                "backend_name": "test_backend",
                "model_name": "test_model", 
                "calling_agent": "test_agent",
                "tool_arguments": {"arg1": f"value_{call_id}", "arg2": f"data_{call_id}" * 5}
            }
            
            await tracker.record_tool_call(session_key, f"tool_{call_id}", context)
    
    # Measure memory after adding data
    after_memory = process.memory_info().rss / 1024 / 1024  # MB
    memory_growth = after_memory - initial_memory
    print(f"Memory after adding data: {after_memory:.2f} MB")
    print(f"Memory growth: {memory_growth:.2f} MB")
    
    # Check internal state
    total_entries = await tracker.get_total_entries_count()
    print("\nInternal state:")
    print(f"Number of sessions tracked: {len(tracker._history)}")
    print(f"Total tool call entries: {total_entries}")
    
    # Verify limits are enforced
    max_entries_per_session = max(
        len(history) for history in tracker._history.values()
    ) if tracker._history else 0
    
    print(f"Max entries per session: {max_entries_per_session}")
    print("Expected max per session: 50")
    print("Expected max sessions: 500")
    
    # Wait for TTL to expire and periodic cleanup
    print("\nWaiting for TTL expiration and periodic cleanup...")
    await asyncio.sleep(15)  # Wait for TTL + periodic cleanup
    
    # Trigger some access to potentially wake up cleanup
    for session_id in range(10):
        await tracker.get_call_count(f"test_session_{session_id}", "tool_0", 3600)
    
    # Check final state
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    final_total_entries = await tracker.get_total_entries_count()
    
    print("\nFinal state:")
    print(f"Memory after cleanup: {final_memory:.2f} MB")
    print(f"Final memory growth: {final_memory - initial_memory:.2f} MB")
    print(f"Final sessions tracked: {len(tracker._history)}")
    print(f"Final total entries: {final_total_entries}")
    
    # Shutdown tracker
    await tracker.shutdown()
    
    # Evaluate if fix is successful
    # Memory should be much more reasonable now
    reasonable_memory_growth = 50  # MB - much lower than before
    reasonable_total_entries = 500 * 50  # max_sessions * max_entries_per_session
    
    is_successful = (
        (final_memory - initial_memory) < reasonable_memory_growth and
        len(tracker._history) <= 500 and
        final_total_entries <= reasonable_total_entries and
        max_entries_per_session <= 50
    )
    
    if is_successful:
        print("\n✅ MEMORY LEAK FIX SUCCESSFUL!")
        print("Evidence:")
        print(f"  - Controlled memory growth: {final_memory - initial_memory:.2f} MB < {reasonable_memory_growth} MB")
        print(f"  - Session limit enforced: {len(tracker._history)} <= 500")
        print(f"  - Per-session limit enforced: {max_entries_per_session} <= 50")
        print(f"  - Total entries controlled: {final_total_entries} <= {reasonable_total_entries}")
    else:
        print("\n❌ Memory leak fix needs improvement")
        print("Issues:")
        if (final_memory - initial_memory) >= reasonable_memory_growth:
            print(f"  - Memory growth still high: {final_memory - initial_memory:.2f} MB")
        if len(tracker._history) > 500:
            print(f"  - Session limit not enforced: {len(tracker._history)} > 500")
        if final_total_entries > reasonable_total_entries:
            print(f"  - Total entries too high: {final_total_entries} > {reasonable_total_entries}")
        if max_entries_per_session > 50:
            print(f"  - Per-session limit not enforced: {max_entries_per_session} > 50")
    
    return is_successful

if __name__ == "__main__":
    asyncio.run(test_fixed_memory_management())