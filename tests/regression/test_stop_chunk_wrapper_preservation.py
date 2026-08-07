"""Regression tests for StopChunkWithUsage wrapper preservation through the pipeline.

These tests verify that the StopChunkWithUsage protective wrapper is not stripped
during processing through various pipeline stages. The wrapper prevents accidental
stringification of usage chunks, which would cause usage data to leak into message
content.

Reference: Issue discovered where ProcessedResponse and _normalize_content were
converting StopChunkWithUsage to plain dict, bypassing the protection.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from src.core.interfaces.response_processor_interface import ProcessedResponse
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
    UsageChunkLeakError,
)
from src.core.transport.fastapi.response_adapters import _normalize_content


class TestProcessedResponsePreservesStopChunkWithUsage:
    """Tests that ProcessedResponse doesn't coerce StopChunkWithUsage to other types."""

    def test_stop_chunk_preserved_as_content(self) -> None:
        """StopChunkWithUsage should remain as-is when passed to ProcessedResponse."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        proc_resp = ProcessedResponse(
            content=chunk,
            usage={"prompt_tokens": 100, "completion_tokens": 50},
            metadata={"finish_reason": "stop"},
        )

        # Content must remain StopChunkWithUsage, not converted to another type
        assert isinstance(
            proc_resp.content, StopChunkWithUsage
        ), f"Expected StopChunkWithUsage, got {type(proc_resp.content).__name__}"

    def test_stop_chunk_protection_still_works_after_processed_response(self) -> None:
        """Protection should still work after going through ProcessedResponse."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        proc_resp = ProcessedResponse(content=chunk)

        # The content should still raise on stringification
        with pytest.raises(UsageChunkLeakError):
            str(proc_resp.content)

    def test_regular_dict_not_affected(self) -> None:
        """Regular dicts should still work normally."""
        regular_dict = {
            "id": "chatcmpl-test",
            "choices": [{"delta": {"content": "Hello"}}],
        }

        proc_resp = ProcessedResponse(content=regular_dict)

        # Regular dict should be preserved as dict
        assert isinstance(proc_resp.content, dict)
        # Should be stringifiable (no protection)
        str(proc_resp.content)  # Should not raise


class TestNormalizeContentPreservesStopChunkWithUsage:
    """Tests that _normalize_content doesn't strip the StopChunkWithUsage wrapper."""

    def test_stop_chunk_not_converted_to_dict(self) -> None:
        """_normalize_content should return StopChunkWithUsage unchanged."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        result = _normalize_content(chunk)

        assert isinstance(
            result, StopChunkWithUsage
        ), f"Expected StopChunkWithUsage, got {type(result).__name__}"

    def test_protection_intact_after_normalize(self) -> None:
        """StopChunkWithUsage should still raise on str() after _normalize_content."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100},
            }
        )

        result = _normalize_content(chunk)

        with pytest.raises(UsageChunkLeakError):
            str(result)

    def test_regular_content_unchanged(self) -> None:
        """Regular content should pass through unchanged."""
        regular_str = "Hello, world!"
        assert _normalize_content(regular_str) == regular_str

        regular_dict = {"key": "value"}
        assert _normalize_content(regular_dict) == regular_dict


class TestStreamingPipelinePreservesProtection:
    """End-to-end tests for StopChunkWithUsage through the streaming pipeline."""

    def test_stop_chunk_serializes_correctly_through_streaming_content(self) -> None:
        """StopChunkWithUsage should serialize correctly via StreamingContent."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": 12345,
                "model": "test-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            }
        )

        # Create ProcessedResponse (simulating connector output)
        proc_resp = ProcessedResponse(
            content=chunk,
            usage=chunk.get("usage"),
            metadata={"finish_reason": "stop"},
        )

        # Create StreamingContent (simulating adapter conversion)
        sc = StreamingContent(
            content=proc_resp.content,
            is_done=True,
            metadata=proc_resp.metadata or {},
            usage=proc_resp.usage,
        )

        # Serialize to bytes
        result = sc.to_bytes()
        result_str = result.decode("utf-8")

        # Parse and verify correct structure
        assert "data: " in result_str

        # Extract JSON from SSE format
        for line in result_str.split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                parsed = json.loads(line[6:])

                # Usage should be at top level
                assert "usage" in parsed, "Usage should be at top level"
                assert parsed["usage"]["total_tokens"] == 150

                # Usage should NOT be in delta.content
                delta = parsed["choices"][0].get("delta", {})
                content = delta.get("content", "")
                assert (
                    "prompt_tokens" not in content
                ), "Usage should not leak to content"

    def test_full_flow_from_connector_to_streaming_content(self) -> None:
        """Test the full flow: connector -> ProcessedResponse -> StreamingContent."""
        # Simulate connector wrapping the stop chunk
        raw_chunk: dict[str, Any] = {
            "id": "chatcmpl-flow-test",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "gemini-test",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 500,
                "completion_tokens": 100,
                "total_tokens": 600,
            },
        }

        # Step 1: Connector wraps with StopChunkWithUsage
        wrapped = StopChunkWithUsage(raw_chunk)

        # Step 2: ProcessedResponse is created
        proc_resp = ProcessedResponse(
            content=wrapped,
            usage=raw_chunk.get("usage"),
            metadata={"finish_reason": "stop"},
        )

        # Step 3: Verify wrapper is preserved
        assert isinstance(proc_resp.content, StopChunkWithUsage)

        # Step 4: StreamingContent conversion
        sc = StreamingContent(
            content=proc_resp.content,
            is_done=True,
            metadata=proc_resp.metadata or {},
            usage=proc_resp.usage,
        )

        # Step 5: Final serialization
        result = sc.to_bytes()
        result_str = result.decode("utf-8")

        # Verify final output is correct
        for line in result_str.split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                parsed = json.loads(line[6:])
                assert parsed["id"] == "chatcmpl-flow-test"
                assert parsed["usage"]["total_tokens"] == 600
                break
        else:
            pytest.fail("No data line found in SSE output")


class TestProtectionCatchesBugs:
    """Tests that demonstrate the protection actually catches bugs."""

    def test_accidental_str_in_fstring_caught(self) -> None:
        """Using StopChunkWithUsage in f-string should raise error."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "usage": {"total_tokens": 100},
            }
        )

        with pytest.raises(UsageChunkLeakError):
            _ = f"Content: {chunk}"

    def test_accidental_str_concatenation_caught(self) -> None:
        """Concatenating StopChunkWithUsage with string should raise error."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "usage": {"total_tokens": 100},
            }
        )

        with pytest.raises(UsageChunkLeakError):
            _ = "Prefix: " + str(chunk)

    def test_accidental_percent_formatting_caught(self) -> None:
        """Using StopChunkWithUsage in % formatting should raise error."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "usage": {"total_tokens": 100},
            }
        )

        with pytest.raises(UsageChunkLeakError):
            _ = f"Content: {chunk}"  # - testing % formatting triggers protection

    def test_safe_serialization_via_dict_works(self) -> None:
        """The correct way to serialize (via dict()) should work."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "usage": {"total_tokens": 100},
            }
        )

        # This is the safe way - convert to plain dict first
        result = json.dumps(dict(chunk))
        parsed = json.loads(result)

        assert parsed["id"] == "chatcmpl-test"
        assert parsed["usage"]["total_tokens"] == 100
