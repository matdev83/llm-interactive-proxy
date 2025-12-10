#!/usr/bin/env python3
"""Debug script to trace whitespace handling in the full streaming pipeline."""

import asyncio
import json


async def test_streaming_pipeline():
    """Test the full streaming pipeline with whitespace-only chunks."""
    from src.core.interfaces.response_processor_interface import ProcessedResponse
    from src.core.ports.sse_assembler import SSEAssembler
    from src.core.ports.streaming_contracts import StreamingContent
    from src.core.transport.fastapi.response_adapters import (
        _inject_reasoning_metadata,
    )

    print("=" * 70)
    print("Testing streaming pipeline with whitespace-only content")
    print("=" * 70)

    # Simulated backend chunks (like what Cline/OpenAI would send)
    backend_chunks = [
        # Chunk 1: newline
        ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "\n"},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-test",
                "model": "test-model",
                "created": 12345,
            },
            metadata={"stream_id": "test-stream"},
        ),
        # Chunk 2: dash
        ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "-"},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-test",
                "model": "test-model",
                "created": 12345,
            },
            metadata={"stream_id": "test-stream"},
        ),
        # Chunk 3: space
        ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": " "},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-test",
                "model": "test-model",
                "created": 12345,
            },
            metadata={"stream_id": "test-stream"},
        ),
        # Chunk 4: word
        ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": "Test"},
                        "finish_reason": None,
                    }
                ],
                "id": "gen-test",
                "model": "test-model",
                "created": 12345,
            },
            metadata={"stream_id": "test-stream"},
        ),
        # Chunk 5: done
        ProcessedResponse(
            content={
                "choices": [
                    {
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                    }
                ],
                "id": "gen-test",
                "model": "test-model",
                "created": 12345,
            },
            metadata={"stream_id": "test-stream", "finish_reason": "stop"},
        ),
    ]

    # Step 1: Test _inject_reasoning_metadata
    print("\n1. Testing _inject_reasoning_metadata:")
    for i, chunk in enumerate(backend_chunks[:-1]):  # Skip done chunk for this test
        payload = chunk.content
        metadata = chunk.metadata or {}
        enriched = _inject_reasoning_metadata(payload, metadata, streaming=True)
        delta_content = enriched.get("choices", [{}])[0].get("delta", {}).get("content")
        print(
            f"   Chunk {i}: content={delta_content!r}, enriched_type={type(enriched).__name__}"
        )

    # Step 2: Test StreamingContent creation
    print("\n2. Testing StreamingContent creation:")
    streaming_contents = []
    for i, chunk in enumerate(backend_chunks):
        payload = chunk.content
        metadata = chunk.metadata or {}
        enriched = _inject_reasoning_metadata(payload, metadata, streaming=True)

        # Check if this is a done chunk
        is_done = False
        finish_reason = (
            enriched.get("choices", [{}])[0].get("finish_reason")
            if isinstance(enriched, dict)
            else None
        )
        if finish_reason in ("stop", "tool_calls", "length"):
            is_done = True

        sc = StreamingContent(
            content=enriched,
            metadata=metadata,
            is_done=is_done,
        )
        streaming_contents.append(sc)
        delta_content = enriched.get("choices", [{}])[0].get("delta", {}).get("content")
        print(
            f"   Chunk {i}: content={delta_content!r}, "
            f"is_empty={sc.is_empty}, is_done={sc.is_done}"
        )

    # Step 3: Test SSEAssembler
    print("\n3. Testing SSEAssembler:")

    async def stream_generator():
        for sc in streaming_contents:
            yield sc

    assembler = SSEAssembler()
    sse_chunks = []
    async for sse_bytes in assembler.assemble_stream(stream_generator(), format="sse"):
        sse_chunks.append(sse_bytes)
        # Parse content from SSE
        text = sse_bytes.decode("utf-8", errors="replace")
        if text.strip().startswith("data: {"):
            try:
                json_part = text.strip()[6:].strip()
                parsed = json.loads(json_part)
                delta_content = (
                    parsed.get("choices", [{}])[0].get("delta", {}).get("content")
                )
                print(f"   Output chunk: content={delta_content!r}")
            except Exception:
                print(f"   Output chunk: {text[:100]!r}")
        elif text.strip() == "data: [DONE]":
            print("   Output chunk: [DONE]")
        else:
            print(f"   Output chunk: {text[:100]!r}")

    print(f"\n   Total input chunks: {len(streaming_contents)}")
    print(f"   Total output chunks: {len(sse_chunks)}")

    # Verify all content is preserved
    input_contents = []
    for chunk in backend_chunks:
        delta_content = (
            chunk.content.get("choices", [{}])[0].get("delta", {}).get("content", "")
        )
        input_contents.append(delta_content)

    output_contents = []
    for sse_bytes in sse_chunks:
        text = sse_bytes.decode("utf-8", errors="replace")
        if text.strip().startswith("data: {"):
            try:
                json_part = text.strip()[6:].strip()
                parsed = json.loads(json_part)
                delta_content = (
                    parsed.get("choices", [{}])[0].get("delta", {}).get("content", "")
                )
                output_contents.append(delta_content)
            except Exception:
                pass

    print(f"\n   Input contents: {input_contents}")
    print(f"   Output contents: {output_contents}")

    # Check for missing whitespace
    input_text = "".join(input_contents)
    output_text = "".join(output_contents)
    print(f"\n   Input text: {input_text!r}")
    print(f"   Output text: {output_text!r}")

    if input_text == output_text:
        print("\n   SUCCESS: All content preserved correctly!")
    else:
        print("\n   FAIL: Content mismatch detected!")
        print(f"   Missing: {set(input_text) - set(output_text)!r}")


if __name__ == "__main__":
    asyncio.run(test_streaming_pipeline())
