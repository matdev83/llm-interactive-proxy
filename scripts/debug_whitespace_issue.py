#!/usr/bin/env python3
"""Debug script to trace whitespace handling in streaming pipeline."""

import json
from src.core.ports.streaming_contracts import StreamingContent
from src.core.ports.openai_normalizer import OpenAIStreamNormalizer

def test_whitespace_content():
    """Test that whitespace-only content is preserved."""
    print("=" * 60)
    print("Testing whitespace handling in streaming pipeline")
    print("=" * 60)
    
    # Simulated OpenAI chunk with newline content
    newline_chunk = {
        "choices": [{
            "delta": {
                "role": "assistant", 
                "content": "\n"
            }, 
            "finish_reason": None
        }], 
        "id": "gen-test", 
        "model": "test-model", 
        "created": 12345
    }
    
    # Simulated OpenAI chunk with dash content
    dash_chunk = {
        "choices": [{
            "delta": {
                "role": "assistant",
                "content": "-"
            },
            "finish_reason": None
        }],
        "id": "gen-test",
        "model": "test-model",
        "created": 12345
    }
    
    print("\n1. Testing newline chunk:")
    print(f"   Input: {json.dumps(newline_chunk)}")
    
    # Create StreamingContent directly
    content = newline_chunk["choices"][0]["delta"]["content"]
    print(f"   Extracted content: {repr(content)}")
    print(f"   content.strip(): {repr(content.strip())}")
    print(f"   bool(content): {bool(content)}")
    print(f"   bool(content.strip()): {bool(content.strip())}")
    
    # Create StreamingContent with explicit is_empty=False
    streaming_content = StreamingContent(
        content=content,
        metadata={},
        is_done=False,
        is_empty=False,  # Explicitly set
        stream_id="test-stream"
    )
    print(f"   StreamingContent.is_empty (explicit False): {streaming_content.is_empty}")
    print(f"   StreamingContent.content: {repr(streaming_content.content)}")
    
    # Create StreamingContent with is_empty=None (auto-compute)
    streaming_content_auto = StreamingContent(
        content=content,
        metadata={},
        is_done=False,
        is_empty=None,  # Auto-compute
        stream_id="test-stream"
    )
    print(f"   StreamingContent.is_empty (auto-computed): {streaming_content_auto.is_empty}")
    
    # Test _compute_is_empty explicitly
    print("\n2. Testing _compute_is_empty:")
    test_contents = [
        "\n",
        " ",
        "\t",
        "  ",
        "\n\n",
        "-",
        "test",
        "",
    ]
    for tc in test_contents:
        sc = StreamingContent(content=tc, metadata={})
        print(f"   Content {repr(tc)}: is_empty={sc.is_empty}")
    
    # Test to_bytes for whitespace content
    print("\n3. Testing to_bytes for whitespace content:")
    whitespace_content = StreamingContent(
        content="\n",
        metadata={
            "id": "test-id",
            "model": "test-model",
            "created": 12345,
            "role": "assistant",
        },
        is_done=False,
    )
    output_bytes = whitespace_content.to_bytes()
    print(f"   Input content: {repr(whitespace_content.content)}")
    print(f"   Output bytes: {output_bytes}")
    print(f"   Decoded: {output_bytes.decode('utf-8')}")
    
    # Parse the output to verify content is preserved
    if output_bytes.startswith(b"data: "):
        json_part = output_bytes.decode("utf-8").strip()[6:].strip()
        parsed = json.loads(json_part)
        delta_content = parsed.get("choices", [{}])[0].get("delta", {}).get("content")
        print(f"   Parsed delta.content: {repr(delta_content)}")
        if delta_content == "\n":
            print("   SUCCESS: Newline preserved in to_bytes output!")
        else:
            print(f"   FAIL: Expected '\\n', got {repr(delta_content)}")
    
    # Test with dict content (OpenAI format passthrough)
    print("\n4. Testing dict content passthrough:")
    dict_content = StreamingContent(
        content=newline_chunk,  # Full OpenAI chunk as content
        metadata={},
        is_done=False,
    )
    dict_output = dict_content.to_bytes()
    print(f"   Output bytes: {dict_output}")
    if b'"content": "\\n"' in dict_output or b'"content":"\\n"' in dict_output:
        print("   SUCCESS: Newline preserved in dict passthrough!")
    else:
        # Check if we can parse and verify
        parsed = json.loads(dict_output.decode("utf-8").strip()[6:])
        dc = parsed.get("choices", [{}])[0].get("delta", {}).get("content")
        print(f"   Parsed delta.content: {repr(dc)}")
        if dc == "\n":
            print("   SUCCESS: Newline preserved!")
        else:
            print(f"   FAIL: Content not preserved properly")

if __name__ == "__main__":
    test_whitespace_content()

