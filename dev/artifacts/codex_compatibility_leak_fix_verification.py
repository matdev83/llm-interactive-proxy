#!/usr/bin/env python3
"""
Memory leak fix verification script for OpenAI Codex compatibility state.

This script verifies that the memory leak fix is working properly.
"""

import asyncio
import logging
import sys
import os

# Add src to path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.join(current_dir, '..', '..')
sys.path.insert(0, src_path)

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

async def test_memory_leak_fix():
    """Test that compatibility state caches are properly cleaned up."""
    
    print("Testing memory leak fix in CompatibilityState...")
    
    # Create compatibility layer
    compat_layer = CompatibilityLayer(
        session_detector=MockDetector(),
        droid_detector=None,
        kilo_translator=None,
        droid_translator=None,
        tool_execution_service=None,
    )
    
    print("=== Testing release_state method (FIXED) ===")
    
    for request_num in range(10):
        state = compat_layer.create_state()
        
        # Add entries to caches
        for i in range(5):
            tc_id = f"call_clean_{request_num}_{i}"
            state.droid_tool_name_cache[tc_id] = f"tool_{i}"
            state.droid_tool_args_buffer[tc_id] = f'{{"arg": {i}}}'
        
        print(f"Before cleanup - Request {request_num}: name_cache={len(state.droid_tool_name_cache)}, "
              f"args_buffer={len(state.droid_tool_args_buffer)}")
        
        # Call release_state (this is the fix)
        compat_layer.release_state(state)
        
        print(f"After cleanup - Request {request_num}: name_cache={len(state.droid_tool_name_cache)}, "
              f"args_buffer={len(state.droid_tool_args_buffer)}")
        
        # Verify caches are empty
        if len(state.droid_tool_name_cache) > 0 or len(state.droid_tool_args_buffer) > 0:
            print(f"✗ LEAK DETECTED: Caches not properly cleared for request {request_num}")
            return False
    
    print("✓ SUCCESS: All caches properly cleared after release_state call")
    
    print("\n=== Testing multiple cleanup calls (idempotent) ===")
    
    state = compat_layer.create_state()
    state.droid_tool_name_cache["test"] = "tool"
    state.droid_tool_args_buffer["test"] = "{}"
    
    print(f"Before first cleanup: name_cache={len(state.droid_tool_name_cache)}, "
          f"args_buffer={len(state.droid_tool_args_buffer)}")
    
    compat_layer.release_state(state)
    print(f"After first cleanup: name_cache={len(state.droid_tool_name_cache)}, "
          f"args_buffer={len(state.droid_tool_args_buffer)}")
    
    # Call cleanup again - should be safe
    compat_layer.release_state(state)
    print(f"After second cleanup: name_cache={len(state.droid_tool_name_cache)}, "
          f"args_buffer={len(state.droid_tool_args_buffer)}")
    
    return True

if __name__ == "__main__":
    # Set up minimal logging
    logging.basicConfig(level=logging.WARNING)
    
    try:
        success = asyncio.run(test_memory_leak_fix())
        
        if success:
            print("\n✓ MEMORY LEAK FIX VERIFIED: State caches are properly cleared")
            sys.exit(0)
        else:
            print("\n✗ MEMORY LEAK FIX FAILED: Caches are not being cleared")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ ERROR during testing: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)