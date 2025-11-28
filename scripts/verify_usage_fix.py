"""Verify usage chunk leak fix using captured CBOR data.

This script:
1. Loads the CBOR capture file with the problematic session
2. Extracts the backend responses (stop chunks with usage)
3. Simulates processing them through the streaming pipeline
4. Verifies the output doesn't contain leaked/stringified usage data
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import cbor2
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
    UsageChunkLeakError,
)


def load_cbor_entries(capture_file: Path) -> list[dict]:
    """Load entries from CBOR capture file."""
    objects = []
    with open(capture_file, "rb") as f:
        decoder = cbor2.CBORDecoder(f)
        try:
            while True:
                obj = decoder.decode()
                objects.append(obj)
        except Exception:
            pass
    return objects


def extract_stop_chunks_with_usage(objects: list[dict]) -> list[dict]:
    """Extract stop chunks that have usage data from backend responses."""
    stop_chunks = []
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        direction = obj.get("dir")
        # Direction 3 = BACKEND_TO_PROXY
        if direction != 3:
            continue
        data = obj.get("data", b"")
        if isinstance(data, bytes):
            data_str = data.decode("utf-8", errors="ignore")
        else:
            data_str = str(data)

        # Look for stop chunks with usage
        if '"finish_reason": "stop"' in data_str and '"usage":' in data_str:
            # Parse the SSE data
            for line in data_str.split("\n"):
                if line.startswith("data: ") and line != "data: [DONE]":
                    try:
                        parsed = json.loads(line[6:])
                        if "usage" in parsed and "choices" in parsed:
                            stop_chunks.append(parsed)
                    except json.JSONDecodeError:
                        pass
    return stop_chunks


def simulate_connector_output(stop_chunk: dict) -> ProcessedResponse:
    """Simulate what the connector would yield for this stop chunk.

    This mimics the gemini_oauth_base.py connector behavior:
    - Wrapping the stop chunk with StopChunkWithUsage
    - Yielding as ProcessedResponse
    """
    # The connector wraps the stop chunk with usage in StopChunkWithUsage
    wrapped = StopChunkWithUsage(stop_chunk)
    return ProcessedResponse(
        content=wrapped,
        metadata={
            "finish_reason": "stop",
            "id": stop_chunk.get("id"),
            "model": stop_chunk.get("model"),
            "created": stop_chunk.get("created"),
        },
        usage=stop_chunk.get("usage"),
    )


def verify_streaming_content_serialization(
    proc_resp: ProcessedResponse,
) -> tuple[bool, str]:
    """Verify that StreamingContent correctly serializes the ProcessedResponse.

    Returns (success, message)
    """
    # Create StreamingContent from ProcessedResponse (mimics from_raw)
    sc = StreamingContent(
        content=proc_resp.content,
        is_done=False,
        metadata=proc_resp.metadata or {},
        usage=proc_resp.usage,
    )

    try:
        # Convert to bytes (this is what gets sent to client)
        result_bytes = sc.to_bytes()
        result_str = result_bytes.decode("utf-8")
    except UsageChunkLeakError as e:
        return False, f"UsageChunkLeakError raised: {e}"

    # Parse the SSE output
    for line in result_str.split("\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                parsed = json.loads(line[6:])
            except json.JSONDecodeError as e:
                return False, f"Invalid JSON in output: {e}"

            # Check 1: Usage should be at top level
            if "usage" not in parsed:
                return False, "Usage not found at top level of output"

            # Check 2: Usage should NOT be stringified in delta.content
            choices = parsed.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                # If there's content in delta, it should NOT contain usage JSON
                if content and (
                    "prompt_tokens" in content or "completion_tokens" in content
                ):
                    return False, f"Usage leaked into delta.content: {content[:100]}..."

            return True, "OK"

    return False, "No SSE data line found in output"


def test_str_protection():
    """Test that StopChunkWithUsage raises error on str() conversion."""
    chunk = StopChunkWithUsage(
        {
            "id": "test",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100},
        }
    )

    try:
        str(chunk)
        return False, "str() should have raised UsageChunkLeakError"
    except UsageChunkLeakError:
        return True, "str() correctly raises UsageChunkLeakError"


def main():
    print("=" * 70)
    print("USAGE CHUNK LEAK FIX VERIFICATION")
    print("=" * 70)

    # Test 1: StopChunkWithUsage protection
    print("\n[Test 1] StopChunkWithUsage str() protection:")
    success, msg = test_str_protection()
    print(f"  {'PASS' if success else 'FAIL'}: {msg}")
    if not success:
        print("  CRITICAL: StopChunkWithUsage protection not working!")
        return 1

    # Test 2: Load and process captured data
    capture_files = list(Path("var/wire_captures_cbor").glob("*.cbor"))
    if not capture_files:
        print("\n[Test 2] No CBOR capture files found - skipping replay test")
        print("  (Run the proxy with a client to generate capture files)")
        return 0

    latest_capture = max(capture_files, key=lambda p: p.stat().st_mtime)
    print(f"\n[Test 2] Processing capture file: {latest_capture.name}")

    objects = load_cbor_entries(latest_capture)
    print(f"  Loaded {len(objects)} CBOR entries")

    stop_chunks = extract_stop_chunks_with_usage(objects)
    print(f"  Found {len(stop_chunks)} stop chunks with usage data")

    if not stop_chunks:
        print("  No stop chunks with usage found in capture - skipping")
        return 0

    # Test 3: Verify each stop chunk serializes correctly
    print(
        f"\n[Test 3] Verifying streaming serialization for {len(stop_chunks)} chunks:"
    )
    all_passed = True
    for i, chunk in enumerate(stop_chunks):
        proc_resp = simulate_connector_output(chunk)
        success, msg = verify_streaming_content_serialization(proc_resp)
        status = "PASS" if success else "FAIL"
        chunk_id = chunk.get("id", "unknown")[:30]
        usage = chunk.get("usage", {})
        tokens = usage.get("total_tokens", "?")
        print(f"  [{status}] Chunk {i+1}: {chunk_id}... ({tokens} tokens) - {msg}")
        if not success:
            all_passed = False

    print()
    print("=" * 70)
    if all_passed:
        print("ALL TESTS PASSED - Usage leak fix is working correctly!")
        print("=" * 70)
        return 0
    else:
        print("SOME TESTS FAILED - Usage leak may still occur!")
        print("=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
