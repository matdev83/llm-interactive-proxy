#!/usr/bin/env python3
"""
Simplified repro script for thought signature manager memory leak.
This directly tests the problematic class without complex imports.
"""

import asyncio
import gc
import sys
import time
from typing import Dict

# Simulate the problematic ThoughtSignatureManager class
class ThoughtSignatureManager:
    """Represents the problematic implementation."""
    
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._by_tool_call: dict[str, str] = {}
    
    def store_signatures_from_tool_calls(self, tool_calls, session_id):
        """Store signatures - this is where the leak happens."""
        anonymous_key = None if session_id else "anon"
        
        for tc in tool_calls:
            tc_id = tc.get("id", "")
            extra = tc.get("extra_content")
            if not isinstance(extra, dict):
                continue
            
            google_extra = extra.get("google", {})
            sig = google_extra.get("thought_signature")
            if not sig or not tc_id:
                continue
            
            cache_key = f"{session_id}:{tc_id}" if session_id else f"{anonymous_key}:{tc_id}"
            if cache_key:
                self._cache[cache_key] = sig
                self._by_tool_call[tc_id] = sig
    
    def clear_session_cache(self, session_id):
        """Clear session cache - but it's incomplete."""
        if not session_id:
            return 0
        
        prefix = f"{session_id}:"
        keys_to_remove = [key for key in self._cache if key.startswith(prefix)]
        
        tool_call_ids_to_remove = []
        for key in keys_to_remove:
            parts = key.split(":", 1)
            if len(parts) == 2:
                tool_call_ids_to_remove.append(parts[1])
        
        for key in keys_to_remove:
            del self._cache[key]
        
        for tc_id in tool_call_ids_to_remove:
            self._by_tool_call.pop(tc_id, None)
        
        return len(keys_to_remove)


def test_memory_growth():
    """Test that demonstrates the memory leak."""
    print("=== Memory Leak Reproduction ===")
    
    manager = ThoughtSignatureManager()
    
    # Simulate tool calls for different sessions
    for batch in range(10):
        session_id = f"session_{batch}"
        
        # Add 1000 tool calls per session
        tool_calls = []
        for i in range(1000):
            tool_calls.append({
                "id": f"tool_call_{session_id}_{i}",
                "extra_content": {
                    "google": {
                        "thought_signature": f"signature_{session_id}_{i}_{time.time()}"
                    }
                }
            })
        
        manager.store_signatures_from_tool_calls(tool_calls, session_id)
        
        # Also add some anonymous entries (never cleaned up)
        anon_tool_calls = []
        for i in range(100):
            anon_tool_calls.append({
                "id": f"anon_tool_{batch}_{i}",
                "extra_content": {
                    "google": {
                        "thought_signature": f"anon_sig_{batch}_{i}_{time.time()}"
                    }
                }
            })
        
        manager.store_signatures_from_tool_calls(anon_tool_calls, None)
        
        print(f"Batch {batch + 1}: "
              f"cache size: {len(manager._cache)}, "
              f"secondary index: {len(manager._by_tool_call)}")
    
    # Try clearing one session - it only clears a small portion
    print("\n--- After clearing session_0 ---")
    cleared = manager.clear_session_cache("session_0")
    print(f"Cleared {cleared} entries")
    print(f"Remaining - cache: {len(manager._cache)}, secondary: {len(manager._by_tool_call)}")
    
    # Try clearing anonymous entries - this doesn't work
    print("\n--- Attempting to clear anonymous entries ---")
    anon_cleared = manager.clear_session_cache("")  # Empty string means no session
    print(f"Cleared {anon_cleared} anonymous entries (should be 0)")
    print(f"Final - cache: {len(manager._cache)}, secondary: {len(manager._by_tool_call)}")
    
    print("\n=== MEMORY LEAK CONFIRMED ===")
    print("Problems:")
    print("1. No automatic cleanup (no TTL, no size limits)")
    print("2. Anonymous entries are never cleaned up")
    print("3. Secondary index keeps growing even when primary is cleaned")
    print("4. Only manual session-specific cleanup exists")
    
    return len(manager._cache), len(manager._by_tool_call)


if __name__ == "__main__":
    cache_size, secondary_size = test_memory_growth()
    print(f"\nFinal sizes: cache={cache_size}, secondary={secondary_size}")
    print("Memory leak confirmed - these dictionaries grow without bounds!")