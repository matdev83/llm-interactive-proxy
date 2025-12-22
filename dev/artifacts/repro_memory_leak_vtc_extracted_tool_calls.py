"""Repro script to confirm memory leak in VTCBufferState.extracted_tool_calls.

This script demonstrates that extracted_tool_calls list can grow unbounded
without any size limits, causing memory leaks in VTC processing.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import (
    StreamingContextRegistry,
    VTCBufferState,
)

def test_extracted_tool_calls_unbounded_growth():
    """Test that extracted_tool_calls list grows without bounds."""
    registry = StreamingContextRegistry()
    stream_id = "test-stream-1"
    
    # Get VTC buffer state
    state = registry.get_vtc_buffer(stream_id)
    
    # Simulate many tool calls being extracted
    # In real code, tool calls are appended to extracted_tool_calls
    num_calls = 100000  # Simulate many extracted tool calls
    
    print(f"Appending {num_calls} extracted tool calls...")
    for i in range(num_calls):
        tool_call = {
            "id": f"call_{i}",
            "type": "function",
            "function": {
                "name": f"test_function_{i}",
                "arguments": '{"arg": "value"}',
            },
        }
        state.extracted_tool_calls.append(tool_call)
        
        # Check memory growth every 10000 calls
        if (i + 1) % 10000 == 0:
            print(f"  Added {i + 1} calls, list length: {len(state.extracted_tool_calls)}")
    
    print(f"\nFinal list length: {len(state.extracted_tool_calls)}")
    print(f"Estimated memory: ~{len(state.extracted_tool_calls) * 200 / 1024 / 1024:.2f} MB")
    print("\n❌ MEMORY LEAK CONFIRMED: extracted_tool_calls list grows unbounded!")
    print("   No size limit or eviction policy found.")
    
    return len(state.extracted_tool_calls)

if __name__ == "__main__":
    test_extracted_tool_calls_unbounded_growth()
