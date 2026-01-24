
import pydantic
import logging
from src.core.domain.streaming.streaming_content import StreamingContent
from src.core.domain.chat import ToolCall

# Configure logging to see the warning
logging.basicConfig(level=logging.INFO)

def test_repro():
    # Partial tool call chunk as seen in the logs
    partial_tc = {
        'index': 0, 
        'id': 'call_123', 
        'type': 'function', 
        'function': {'arguments': '{"pattern": "src/**'}
    }
    
    # Create StreamingContent with this partial tool call in metadata
    content = StreamingContent(
        content="",
        metadata={"tool_calls": [partial_tc]}
    )
    
    print("Attempting to convert to typed chunk...")
    typed_chunk = content.to_typed_chunk()
    
    # Check if tool_calls in metadata are present or empty
    tool_calls = typed_chunk.metadata.tool_calls
    if tool_calls is None or len(tool_calls) == 0:
        print("FAILURE: tool_calls list is empty or None in typed chunk")
    else:
        print(f"SUCCESS: Found {len(tool_calls)} tool calls in typed chunk")
        for i, tc in enumerate(tool_calls):
            print(f"Tool call {i}: {tc}")

if __name__ == "__main__":
    test_repro()
