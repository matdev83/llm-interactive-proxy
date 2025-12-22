"""Verify that memory leak fixes are working correctly."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.services.streaming.stream_context_registry import (
    StreamBufferState,
    StreamingContextRegistry,
    ToolCallBufferState,
    VTCBufferState,
)

def test_reasoning_chunks_limit():
    """Test that reasoning_chunks deque respects size limit."""
    registry = StreamingContextRegistry()
    stream_id = "test-stream-1"
    
    state = registry.get_content_state(stream_id)
    
    # Try to add more than the limit
    num_chunks = 2000  # More than _MAX_REASONING_CHUNKS (1000)
    
    print(f"Appending {num_chunks} reasoning chunks (limit: 1000)...")
    for i in range(num_chunks):
        reasoning_text = f"Reasoning chunk {i}: " + "x" * 100
        state.append_reasoning_chunk(reasoning_text)
        
        if (i + 1) % 500 == 0:
            print(f"  Added {i + 1} chunks, deque length: {len(state.reasoning_chunks)}")
    
    print(f"\nFinal deque length: {len(state.reasoning_chunks)}")
    assert len(state.reasoning_chunks) <= 1000, f"Expected max 1000 chunks, got {len(state.reasoning_chunks)}"
    print("[OK] reasoning_chunks limit enforced correctly!")

def test_detected_calls_limit():
    """Test that detected_calls list respects size limit."""
    registry = StreamingContextRegistry()
    stream_id = "test-stream-1"
    
    state = registry.get_tool_call_buffer(stream_id)
    
    # Try to add more than the limit
    num_calls = 2000  # More than _MAX_DETECTED_TOOL_CALLS (1000)
    
    print(f"\nAppending {num_calls} detected tool calls (limit: 1000)...")
    for i in range(num_calls):
        tool_call = {
            "id": f"call_{i}",
            "type": "function",
            "function": {
                "name": f"test_function_{i}",
                "arguments": '{"arg": "value"}',
            },
        }
        state.append_detected_call(tool_call)
        
        if (i + 1) % 500 == 0:
            print(f"  Added {i + 1} calls, list length: {len(state.detected_calls)}")
    
    print(f"\nFinal list length: {len(state.detected_calls)}")
    assert len(state.detected_calls) <= 1000, f"Expected max 1000 calls, got {len(state.detected_calls)}"
    print("[OK] detected_calls limit enforced correctly!")

def test_extracted_tool_calls_limit():
    """Test that extracted_tool_calls list respects size limit."""
    registry = StreamingContextRegistry()
    stream_id = "test-stream-1"
    
    state = registry.get_vtc_buffer(stream_id)
    
    # Try to add more than the limit
    num_calls = 2000  # More than _MAX_EXTRACTED_TOOL_CALLS (1000)
    
    print(f"\nAppending {num_calls} extracted tool calls (limit: 1000)...")
    for i in range(num_calls):
        tool_call = {
            "id": f"call_{i}",
            "type": "function",
            "function": {
                "name": f"test_function_{i}",
                "arguments": '{"arg": "value"}',
            },
        }
        state.append_extracted_call(tool_call)
        
        if (i + 1) % 500 == 0:
            print(f"  Added {i + 1} calls, list length: {len(state.extracted_tool_calls)}")
    
    print(f"\nFinal list length: {len(state.extracted_tool_calls)}")
    assert len(state.extracted_tool_calls) <= 1000, f"Expected max 1000 calls, got {len(state.extracted_tool_calls)}"
    print("[OK] extracted_tool_calls limit enforced correctly!")

if __name__ == "__main__":
    test_reasoning_chunks_limit()
    test_detected_calls_limit()
    test_extracted_tool_calls_limit()
    print("\n" + "="*60)
    print("All memory leak fixes verified successfully!")
    print("="*60)
