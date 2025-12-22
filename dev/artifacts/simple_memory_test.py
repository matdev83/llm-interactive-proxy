#!/usr/bin/env python3
"""
Simplified memory leak test for tool call reactor history tracker.

This isolates the InMemoryToolCallHistoryTracker class to test for memory leaks.
"""

import asyncio
import psutil
import os
import time
from datetime import datetime, timezone
from typing import Any
from dataclasses import dataclass

# Simplified version of context for testing
@dataclass
class TestContext:
    backend_name: str
    model_name: str
    calling_agent: str
    tool_arguments: dict
    timestamp: datetime

# Simplified version of InMemoryToolCallHistoryTracker for testing
class TestToolCallHistoryTracker:
    """Simplified version of InMemoryToolCallHistoryTracker for memory testing."""
    
    def __init__(self, session_ttl_seconds: int = 3600, max_sessions: int = 10000):
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._session_last_access: dict[str, datetime] = {}
        self._session_ttl_seconds = session_ttl_seconds
        self._max_sessions = max_sessions
        self._lock = asyncio.Lock()

    async def record_tool_call(self, session_id: str, tool_name: str, context: dict[str, Any]) -> None:
        """Record a tool call - this is where the potential leak occurs."""
        async with self._lock:
            # NOTE: No cleanup called here - this is the potential issue!
            session_history = self._history.setdefault(session_id, [])
            self._session_last_access[session_id] = datetime.now(timezone.utc)

            entry = {
                "tool_name": tool_name,
                "timestamp": datetime.now(timezone.utc),
                "context": context,
            }

            session_history.append(entry)

            # Keep only recent entries (last 1000 per session)
            if len(session_history) > 1000:
                self._history[session_id] = session_history[-1000:]

async def test_memory_growth():
    """Test memory growth with many sessions and tool calls."""
    
    # Get initial memory usage
    process = psutil.Process(os.getpid())
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
    print(f"Initial memory usage: {initial_memory:.2f} MB")
    
    # Create a tracker with short TTL
    tracker = TestToolCallHistoryTracker(
        session_ttl_seconds=10,  # 10 seconds TTL for quick testing
        max_sessions=1000
    )
    
    # Simulate many sessions with many tool calls
    num_sessions = 1000
    calls_per_session = 1200  # More than the 1000 limit to test truncation
    
    print(f"Creating {num_sessions} sessions with {calls_per_session} tool calls each...")
    
    for session_id in range(num_sessions):
        session_key = f"test_session_{session_id}"
        
        for call_id in range(calls_per_session):
            context = {
                "backend_name": "test_backend",
                "model_name": "test_model", 
                "calling_agent": "test_agent",
                "tool_arguments": {"arg1": f"value_{call_id}", "arg2": f"data_{call_id}" * 10}
            }
            
            await tracker.record_tool_call(session_key, f"tool_{call_id}", context)
    
    # Measure memory after adding data
    after_memory = process.memory_info().rss / 1024 / 1024  # MB
    memory_growth = after_memory - initial_memory
    print(f"Memory after adding data: {after_memory:.2f} MB")
    print(f"Memory growth: {memory_growth:.2f} MB")
    
    # Check the internal state
    print(f"\nInternal state:")
    print(f"Number of sessions tracked: {len(tracker._history)}")
    
    total_entries = 0
    max_entries_per_session = 0
    for session_id, history in tracker._history.items():
        entries_count = len(history)
        total_entries += entries_count
        max_entries_per_session = max(max_entries_per_session, entries_count)
        
        if entries_count > 1000:
            print(f"Session {session_id} has {entries_count} entries (exceeds 1000 limit!)")
    
    print(f"Total tool call entries: {total_entries}")
    print(f"Expected maximum entries: {num_sessions * 1000}")
    print(f"Max entries per session: {max_entries_per_session}")
    
    # The issue: even with 1000 limit per session, with 1000 sessions
    # we still have 1,000,000 entries in memory!
    
    # Wait for TTL to expire (but we won't call cleanup to simulate the issue)
    print("\nWaiting for TTL to expire...")
    await asyncio.sleep(15)  # Wait longer than TTL
    
    final_memory = process.memory_info().rss / 1024 / 1024  # MB
    print(f"\nMemory after TTL expiration: {final_memory:.2f} MB")
    print(f"Final memory growth: {final_memory - initial_memory:.2f} MB")
    print(f"Number of sessions tracked: {len(tracker._history)}")
    
    # Memory leak indicators:
    # 1. Large memory growth (> 100MB for this test)
    # 2. Sessions not cleaned up after TTL
    # 3. Total entries close to num_sessions * 1000 (shows the per-session limit isn't enough)
    
    expected_max_memory = 20  # MB - reasonable for this test
    expected_max_total_entries = num_sessions * 1000
    
    is_leaked = (
        (final_memory - initial_memory) > expected_max_memory or
        len(tracker._history) > 100 or  # Should be mostly cleared after TTL
        total_entries > expected_max_total_entries * 0.9  # Close to theoretical max
    )
    
    if is_leaked:
        print("\n🚨 MEMORY LEAK DETECTED!")
        print("Evidence:")
        if (final_memory - initial_memory) > expected_max_memory:
            print(f"  - Excessive memory growth: {final_memory - initial_memory:.2f} MB (expected < {expected_max_memory} MB)")
        if len(tracker._history) > 100:
            print(f"  - Sessions not cleaned up: {len(tracker._history)} remaining (TTL = {tracker._session_ttl_seconds}s)")
        if total_entries > expected_max_total_entries * 0.9:
            print(f"  - Too many total entries: {total_entries} (max should be ~{expected_max_total_entries})")
            print("  - ISSUE: Per-session limit of 1000 is insufficient across many sessions!")
    else:
        print("\n✅ No significant memory leak detected")
    
    return is_leaked

if __name__ == "__main__":
    asyncio.run(test_memory_growth())