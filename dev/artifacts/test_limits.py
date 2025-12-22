#!/usr/bin/env python3
"""
Simple test to verify the memory leak fix works correctly.
"""

import asyncio
import os
import sys
from datetime import datetime, timezone

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

async def test_memory_limits():
    """Test that new memory limits are enforced."""
    
    from core.services.tool_call_reactor_service import InMemoryToolCallHistoryTracker
    
    # Create tracker with new strict limits
    tracker = InMemoryToolCallHistoryTracker(
        session_ttl_seconds=60,  # 1 minute TTL
        max_sessions=50,       # Small number for testing
        max_entries_per_session=10  # Very small limit to test enforcement
    )
    
    print("Testing new memory limits enforcement...")
    
    # Test 1: Per-session limit enforcement
    session_id = "test_session_1"
    for i in range(25):  # More than the limit of 10
        context = {
            "backend_name": "test_backend",
            "model_name": "test_model", 
            "calling_agent": "test_agent",
            "tool_arguments": {"counter": i}
        }
        await tracker.record_tool_call(session_id, f"tool_{i}", context)
    
    # Check session has at most 10 entries
    session_count = len(tracker._history.get(session_id, []))
    print(f"Session entry count: {session_count} (max allowed: 10)")
    assert session_count <= 10, f"Per-session limit not enforced: {session_count} > 10"
    
    # Test 2: Total entries tracking
    total_entries = await tracker.get_total_entries_count()
    print(f"Total entries tracked: {total_entries}")
    
    # Test 3: Max sessions enforcement  
    for i in range(60):  # More than max_sessions of 50
        await tracker.record_tool_call(f"session_{i}", "test_tool", {"test": True})
    
    total_sessions = len(tracker._history)
    print(f"Total sessions tracked: {total_sessions} (max allowed: 50)")
    assert total_sessions <= 50, f"Max sessions limit not enforced: {total_sessions} > 50"
    
    # Test 4: Total entries after adding many sessions
    final_total = await tracker.get_total_entries_count()
    print(f"Final total entries: {final_total}")
    
    # The total should be reasonable (50 sessions * 10 entries per session = 500 max)
    expected_max_total = 50 * 10
    print(f"Expected maximum total entries: {expected_max_total}")
    assert final_total <= expected_max_total, f"Total entries too high: {final_total} > {expected_max_total}"
    
    print("✅ All memory limits enforced correctly!")
    
    # Cleanup
    await tracker.clear_history()
    final_entries = await tracker.get_total_entries_count()
    print(f"Entries after clear: {final_entries}")
    assert final_entries == 0, f"Clear didn't work: {final_entries} > 0"
    
    print("✅ Clear functionality works correctly!")

if __name__ == "__main__":
    asyncio.run(test_memory_limits())