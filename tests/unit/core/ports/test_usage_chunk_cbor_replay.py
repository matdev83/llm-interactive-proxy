"""Regression tests using captured CBOR data to verify usage chunk handling.

This test module replays real captured CBOR data from actual sessions to verify
that the usage chunk leak fix is working correctly. It detects issues where
usage data gets stringified into delta.content instead of being properly
serialized at the top level of the SSE response.

Reference: Real-world issue discovered with KiloCode + gemini-oauth backends
where usage chunks like:
    {"id": "chatcmpl-gemini-usage-xxx", "choices": [], "usage": {...}}
were being stringified and leaked into message content.
"""

from __future__ import annotations

import json
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
    UsageChunkLeakError,
)


def _extract_first_sse_payload(result_str: str) -> dict[str, Any] | None:
    """Return the first JSON payload from SSE output, if present."""
    for line in result_str.split("\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            return cast(dict[str, Any], json.loads(line[6:]))
    return None


def get_cbor_capture_files() -> list[Path]:
    """Get all CBOR capture files from the wire captures directory."""
    captures_dir = Path("var/wire_captures_cbor")
    if not captures_dir.exists():
        return []
    return list(captures_dir.glob("*.cbor"))


def load_cbor_entries(capture_file: Path) -> list[dict[str, Any]]:
    """Load entries from CBOR capture file."""
    try:
        import cbor2
    except ImportError:
        pytest.skip("cbor2 not installed")

    objects: list[dict[str, Any]] = []
    with open(capture_file, "rb") as f:
        decoder = cbor2.CBORDecoder(f)
        try:
            while True:
                obj = decoder.decode()
                if isinstance(obj, dict):
                    objects.append(cast(dict[str, Any], obj))
        except Exception:
            pass
    return objects


def _stop_chunks_for_capture_file(capture_file: Path) -> list[dict[str, Any]]:
    """Decode one capture file and extract stop+usage chunks (worker for parallel I/O)."""

    return extract_stop_chunks_with_usage(load_cbor_entries(capture_file))


def _merge_chunks_by_capture_order(
    capture_files: list[Path],
    chunks_by_capture: dict[Path, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge decoded chunks following the original capture file order."""
    merged: list[dict[str, Any]] = []
    for capture_file in capture_files:
        merged.extend(chunks_by_capture.get(capture_file, []))
    return merged


def extract_stop_chunks_with_usage(
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract stop chunks that have usage data from backend responses."""
    stop_chunks: list[dict[str, Any]] = []
    for obj in objects:
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


def simulate_connector_output(stop_chunk: dict[str, Any]) -> ProcessedResponse:
    """Simulate what the connector would yield for this stop chunk.

    This mimics the gemini_oauth_base.py connector behavior:
    - Wrapping the stop chunk with StopChunkWithUsage
    - Yielding as ProcessedResponse
    """
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


def verify_no_usage_leak(proc_resp: ProcessedResponse) -> tuple[bool, str]:
    """Verify that StreamingContent correctly serializes without leaking usage.

    Returns (success, error_message)
    """
    if proc_resp.content is None:
        return False, "ProcessedResponse content is None"

    sc = StreamingContent(
        content=proc_resp.content,
        is_done=False,
        metadata=proc_resp.metadata or {},
        usage=proc_resp.usage,
    )

    try:
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
                if content and (
                    "prompt_tokens" in content or "completion_tokens" in content
                ):
                    return False, f"Usage leaked into delta.content: {content[:100]}..."

            return True, ""

    return False, "No SSE data line found in output"


class TestCBORChunkMergeOrder:
    """Tests for deterministic merge order across parallel decode results."""

    def test_merge_chunks_preserves_capture_file_order(self) -> None:
        """Merged chunks should follow capture_files order, not completion order."""
        file_a = Path("a.cbor")
        file_b = Path("b.cbor")
        file_c = Path("c.cbor")

        chunks_by_capture = {
            file_b: [{"id": "b-1"}],
            file_a: [{"id": "a-1"}, {"id": "a-2"}],
            file_c: [{"id": "c-1"}],
        }

        merged = _merge_chunks_by_capture_order(
            [file_a, file_b, file_c],
            chunks_by_capture,
        )
        assert [chunk["id"] for chunk in merged] == ["a-1", "a-2", "b-1", "c-1"]


class TestStopChunkWithUsageProtection:
    """Tests for StopChunkWithUsage stringification protection."""

    def test_str_raises_usage_chunk_leak_error(self) -> None:
        """Converting StopChunkWithUsage to string should raise UsageChunkLeakError."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        with pytest.raises(UsageChunkLeakError) as exc_info:
            str(chunk)

        assert "chatcmpl-test" in str(exc_info.value)

    def test_dict_conversion_safe(self) -> None:
        """Converting to plain dict should work for legitimate serialization."""
        original = {
            "id": "chatcmpl-test",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100},
        }
        chunk = StopChunkWithUsage(original)

        # dict() should work without raising
        plain_dict = dict(chunk)
        assert plain_dict == original

    def test_json_dumps_with_dict_conversion(self) -> None:
        """json.dumps(dict(chunk)) should work for legitimate serialization."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100},
            }
        )

        # This is the correct way to serialize
        result = json.dumps(dict(chunk))
        parsed = json.loads(result)
        assert parsed["usage"]["prompt_tokens"] == 100


@pytest.fixture(scope="session")
def cbor_stop_chunks() -> list[dict[str, Any]]:
    """Load stop chunks from available CBOR captures (once per pytest worker)."""
    capture_files = get_cbor_capture_files()
    if not capture_files:
        pytest.skip("No CBOR capture files available for replay testing")

    # Decode captures in parallel: bounded workers avoid thread overhead on Windows.
    max_workers = min(8, max(1, len(capture_files)))
    chunks_by_capture: dict[Path, list[dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures_by_capture: dict[Path, Future[list[dict[str, Any]]]] = {
            p: pool.submit(_stop_chunks_for_capture_file, p) for p in capture_files
        }

        for capture_file in capture_files:
            chunks_by_capture[capture_file] = futures_by_capture[capture_file].result()

    all_chunks = _merge_chunks_by_capture_order(capture_files, chunks_by_capture)

    if not all_chunks:
        pytest.skip("No stop chunks with usage found in captures")

    return all_chunks


class TestUsageChunkSerializationWithCBORData:
    """Regression tests using real captured CBOR data."""

    def test_stop_chunks_serialize_without_leak(
        self, cbor_stop_chunks: list[dict[str, Any]]
    ) -> None:
        """Verify all captured stop chunks serialize correctly without leaking usage."""
        failures: list[str] = []

        for chunk in cbor_stop_chunks:
            proc_resp = simulate_connector_output(chunk)
            success, error_msg = verify_no_usage_leak(proc_resp)
            if not success:
                chunk_id = chunk.get("id", "unknown")
                tokens = chunk.get("usage", {}).get("total_tokens", "?")
                failures.append(f"Chunk {chunk_id} ({tokens} tokens): {error_msg}")

        if failures:
            pytest.fail(
                f"Usage leak detected in {len(failures)} chunks:\n"
                + "\n".join(failures[:10])  # Show first 10 failures
            )

    def test_usage_at_top_level_in_output(
        self, cbor_stop_chunks: list[dict[str, Any]]
    ) -> None:
        """Verify usage data appears at top level in SSE output, not in delta.content."""
        for chunk in cbor_stop_chunks[:5]:  # Test first 5 to keep fast
            proc_resp = simulate_connector_output(chunk)
            assert proc_resp.content is not None
            sc = StreamingContent(
                content=proc_resp.content,
                is_done=False,
                metadata=proc_resp.metadata or {},
                usage=proc_resp.usage,
            )

            result_bytes = sc.to_bytes()
            result_str = result_bytes.decode("utf-8")
            parsed = _extract_first_sse_payload(result_str)
            assert (
                parsed is not None
            ), f"No SSE data line found in output for {chunk['id']}"

            # Verify usage at top level
            assert "usage" in parsed, f"Missing top-level usage in {chunk['id']}"
            assert "prompt_tokens" in parsed["usage"]
            assert "completion_tokens" in parsed["usage"]

            # Verify no leak in delta.content
            choices = parsed.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                assert (
                    "prompt_tokens" not in content
                ), f"Usage leaked to delta.content in {chunk['id']}"


class TestSyntheticUsageChunkSerialization:
    """Tests using synthetic data (always run, no CBOR required)."""

    @pytest.mark.parametrize(
        "total_tokens",
        [100, 1000, 10000, 50000, 100000],
    )
    def test_various_token_counts(self, total_tokens: int) -> None:
        """Verify serialization works correctly for various token counts."""
        prompt_tokens = total_tokens // 2
        completion_tokens = total_tokens - prompt_tokens

        chunk = {
            "id": f"chatcmpl-test-{total_tokens}",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "test-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
            },
        }

        proc_resp = simulate_connector_output(chunk)
        success, error_msg = verify_no_usage_leak(proc_resp)

        assert success, f"Failed for {total_tokens} tokens: {error_msg}"

    def test_chunk_with_reasoning_content(self) -> None:
        """Verify chunks with reasoning_content don't leak usage."""
        chunk = {
            "id": "chatcmpl-with-reasoning",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "reasoning_content": "thinking..."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
        }

        proc_resp = simulate_connector_output(chunk)
        success, error_msg = verify_no_usage_leak(proc_resp)
        assert success, error_msg

    def test_chunk_with_tool_calls(self) -> None:
        """Verify chunks with tool_calls don't leak usage."""
        chunk = {
            "id": "chatcmpl-with-tools",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "test", "arguments": "{}"},
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
        }

        proc_resp = simulate_connector_output(chunk)
        success, error_msg = verify_no_usage_leak(proc_resp)
        assert success, error_msg
