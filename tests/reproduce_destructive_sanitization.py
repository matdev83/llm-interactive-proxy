
import json
import logging
from src.core.ports.streaming_contracts import StreamingContent

def test_destructive_sanitization():
    # Simulate a tool call with extra_content
    original_dict = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "function": {"name": "foo", "arguments": "{}"},
                            "extra_content": {"important": "data"}
                        }
                    ]
                }
            }
        ]
    }
    
    chunk = StreamingContent(
        content=original_dict,
        metadata={"finish_reason": "tool_calls"},
        is_done=True
    )

    print("Before to_bytes:")
    print(json.dumps(original_dict, indent=2))
    
    # Serialize (trigger sanitization)
    chunk.to_bytes()
    
    print("\nAfter to_bytes:")
    print(json.dumps(original_dict, indent=2))
    
    # Check if extra_content is gone from ORIGINAL dict
    tc = original_dict["choices"][0]["delta"]["tool_calls"][0]
    if "extra_content" not in tc:
        print("\nFAIL: extra_content removed from original object!")
    else:
        print("\nPASS: extra_content preserved in original object.")

if __name__ == "__main__":
    test_destructive_sanitization()
