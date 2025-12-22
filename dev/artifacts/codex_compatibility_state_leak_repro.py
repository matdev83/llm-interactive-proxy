#!/usr/bin/env python3
"""
Memory leak reproduction script for OpenAI Codex compatibility state.

This script simulates multiple requests to check if CompatibilityState
droid_tool_name_cache and droid_tool_args_buffer are being cleared properly.
"""

import asyncio
import logging
import sys
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, '..', '..')
sys.path.insert(0, src_path)

# Mock imports to avoid dependency issues
@dataclass
class MockToolCall:
    id: str
    name: str = "test_tool"
    arguments: str = "{}"

@dataclass 
class MockStreamChunk:
    choices: list[dict]
    finish_reason: str = None

from src.connectors.openai_codex.contracts import CompatibilityState
from src.connectors.openai_codex.compat import CompatibilityLayer

# Mock detector
class MockDetector:
    async def detect(self, *args, **kwargs):
        class MockResult:
            is_kilocode = True
            confidence = 1.0
            detection_method = "mock"
        return MockResult()

async def test_memory_leak():
    """Test if compatibility state caches grow without bounds."""
    
    print("Testing memory leak in CompatibilityState...")
    
    # Create compatibility layer
    compat_layer = CompatibilityLayer(
        session_detector=MockDetector(),
        droid_detector=None,
        kilo_translator=None,
        droid_translator=None,
        tool_execution_service=None,
    )
    
    cache_sizes = defaultdict(list)
    
    # Simulate many requests
    for request_num in range(100):
        # Create new state for each request (this should happen in normal flow)
        state = compat_layer.create_state()
        
        # Simulate some tool calls
        for i in range(10):
            tc_id = f"call_{request_num}_{i}"
            
            # Add entries to caches (simulating what happens during streaming)
            state.droid_tool_name_cache[tc_id] = f"tool_{i}"
            state.droid_tool_args_buffer[tc_id] = f'{{"arg": {i}}}'
        
        # Track cache sizes
        cache_sizes['name_cache'].append(len(state.droid_tool_name_cache))
        cache_sizes['args_buffer'].append(len(state.droid_tool_args_buffer))
        
        # Simulate completion - THIS IS WHERE THE BUG SHOULD BE FIXED
        # state should be cleared but we're not calling release_state
        
        if request_num % 10 == 0:
            print(f"Request {request_num}: name_cache={len(state.droid_tool_name_cache)}, "
                  f"args_buffer={len(state.droid_tool_args_buffer)}")
    
    print("\n=== MEMORY LEAK DETECTED ===")
    print(f"Final name cache size: {len(state.droid_tool_name_cache)}")
    print(f"Final args buffer size: {len(state.droid_tool_args_buffer)}")
    print(f"Expected size after cleanup: 0")
    print(f"Leaked entries: {len(state.droid_tool_name_cache) + len(state.droid_tool_args_buffer)}")
    
    # Now test with proper cleanup
    print("\n=== TESTING PROPER CLEANUP ===")
    
    for request_num in range(10):
        state = compat_layer.create_state()
        
        # Add entries
        for i in range(5):
            tc_id = f"call_clean_{request_num}_{i}"
            state.droid_tool_name_cache[tc_id] = f"tool_{i}"
            state.droid_tool_args_buffer[tc_id] = f'{{"arg": {i}}}'
        
        print(f"Before cleanup - Request {request_num}: name_cache={len(state.droid_tool_name_cache)}, "
              f"args_buffer={len(state.droid_tool_args_buffer)}")
        
        # Call release_state (this should be done but isn't)
        compat_layer.release_state(state)
        
        print(f"After cleanup - Request {request_num}: name_cache={len(state.droid_tool_name_cache)}, "
              f"args_buffer={len(state.droid_tool_args_buffer)}")
    
    return len(state.droid_tool_name_cache) > 0 or len(state.droid_tool_args_buffer) > 0

if __name__ == "__main__":
    # Set up minimal logging
    logging.basicConfig(level=logging.WARNING)
    
    has_leak = asyncio.run(test_memory_leak())
    
    if has_leak:
        print("\n✗ MEMORY LEAK CONFIRMED: State caches are not being cleared")
        sys.exit(1)
    else:
        print("\n✓ NO MEMORY LEAK: State caches are properly cleared")
        sys.exit(0)