
import json
import pytest
from unittest.mock import MagicMock
from src.core.domain.chat import CanonicalChatRequest, ChatMessage
from src.core.domain.translators.gemini.request import from_domain_to_gemini_request
from src.core.domain.translators.code_assist.streaming import code_assist_to_domain_stream_chunk

def test_gemini_request_parallel_tool_calling_flag():
    # 1. Verify explicit flag passing
    req = CanonicalChatRequest(
        model="gemini-2.0-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        parallel_tool_calls=True
    )
    translated = from_domain_to_gemini_request(req)
    assert translated["generationConfig"]["parallelToolCalling"] is True

    req_disabled = CanonicalChatRequest(
        model="gemini-2.0-pro",
        messages=[ChatMessage(role="user", content="Hello")],
        parallel_tool_calls=False
    )
    translated_disabled = from_domain_to_gemini_request(req_disabled)
    assert translated_disabled["generationConfig"]["parallelToolCalling"] is False

    # 2. Verify default for Gemini 3
    req_g3 = CanonicalChatRequest(
        model="gemini-3-pro",
        messages=[ChatMessage(role="user", content="Hello")]
    )
    translated_g3 = from_domain_to_gemini_request(req_g3)
    assert translated_g3["generationConfig"]["parallelToolCalling"] is True

def test_gemini_request_preserves_assistant_text_with_tools():
    # Regression test for: assistant text being stripped when tool calls are present
    req = CanonicalChatRequest(
        model="gemini-2.0-pro",
        messages=[
            ChatMessage(
                role="assistant", 
                content="I will read the files now.",
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "read_file", "arguments": '{"path": "test.txt"}'}
                }]
            )
        ]
    )
    translated = from_domain_to_gemini_request(req)
    
    # Check that both text and functionCall parts are present in the same content item
    parts = translated["contents"][0]["parts"]
    has_text = any("text" in p and p["text"] == "I will read the files now." for p in parts)
    has_tool = any("functionCall" in p for p in parts)
    
    assert has_text, "Assistant text content was stripped"
    assert has_tool, "Tool call was stripped"

def test_code_assist_streaming_finish_reason_wait():
    # Regression test for: premature finish_reason stopping stream accumulation
    
    # Chunk 1: Tool call but NO finishReason from backend
    chunk1 = {
        "response": {
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "read_file",
                            "args": {"path": "file1.txt"},
                            "id": "call_1"
                        }
                    }]
                }
            }]
        }
    }
    
    # Chunk 2: Another tool call AND finishReason from backend
    chunk2 = {
        "response": {
            "candidates": [{
                "content": {
                    "parts": [{
                        "functionCall": {
                            "name": "read_file",
                            "args": {"path": "file2.txt"},
                            "id": "call_2"
                        }
                    }]
                },
                "finishReason": "STOP"
            }]
        }
    }
    
    translated1 = code_assist_to_domain_stream_chunk(chunk1)
    translated2 = code_assist_to_domain_stream_chunk(chunk2)
    
    # Chunk 1 should have NO finish_reason, allowing clients to continue reading
    assert translated1["choices"][0]["finish_reason"] is None
    
    # Chunk 2 should have "tool_calls" (mapped from Gemini STOP when tool calls are present)
    assert translated2["choices"][0]["finish_reason"] == "tool_calls"

if __name__ == "__main__":
    # Allow running directly for quick verification
    try:
        test_gemini_request_parallel_tool_calling_flag()
        test_gemini_request_preserves_assistant_text_with_tools()
        test_code_assist_streaming_finish_reason_wait()
        print("All regression tests PASSED")
    except Exception as e:
        print(f"Regression tests FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
