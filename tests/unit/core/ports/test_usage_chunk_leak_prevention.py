"""Tests for usage chunk leak prevention.

This test module ensures that internal usage/billing data is properly transmitted
to clients and not leaked into message content.

The correct behavior (per OpenRouter API spec):
- Usage data should be included in the FINAL stop chunk at the top level
- NOT as a separate usage-only chunk with choices: []
- NOT stringified into delta.content

Reference: Real-world issue discovered with KiloCode + gemini-oauth backends
"""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest
from src.core.ports.streaming_contracts import (
    StopChunkWithUsage,
    StreamingContent,
    UsageChunkLeakError,
)


class TestUsageInFinalChunk:
    """Tests to ensure usage is properly included in final stop chunk."""

    def test_final_chunk_with_usage_serializes_correctly(self) -> None:
        """Final stop chunk should include usage at top level in SSE output."""
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            # Create a final stop chunk with usage (the new correct format)
            final_chunk = {
                "id": f"chatcmpl-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "gemini-3-pro-high",
                "choices": [
                    {
                        "index": 0,
                        "delta": {},  # Empty delta for stop chunk
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 14803,
                    "completion_tokens": 18,
                    "total_tokens": 14821,
                },
            }

            # Create StreamingContent with the final chunk
            streaming_content = StreamingContent(
                content=final_chunk,
                is_done=True,
                metadata={},
                usage=final_chunk.get("usage"),
            )

            # Convert to bytes (SSE format)
            result_bytes = streaming_content.to_bytes()
            result_str = result_bytes.decode("utf-8")

            # Parse the SSE data (should have data: chunk and data: [DONE])
            assert result_str.startswith(
                "data: "
            ), f"Expected SSE format, got: {result_str}"

            # Extract just the JSON part - SSE format is "data: {...}\n\ndata: [DONE]\n\n"
            # Find the first JSON object
            data_prefix = "data: "
            first_data_end = result_str.find("\n\n")
            json_line = result_str[len(data_prefix) : first_data_end].strip()
            parsed = json.loads(json_line)

            # Verify structure matches OpenRouter spec
            assert "id" in parsed, "Result should have id"
            assert "choices" in parsed, "Result should have choices"
            assert (
                parsed["choices"][0]["finish_reason"] == "stop"
            ), "Should be stop chunk"
            assert "usage" in parsed, "Usage should be at top level"
            assert parsed["usage"]["prompt_tokens"] == 14803
            assert parsed["usage"]["completion_tokens"] == 18
            assert parsed["usage"]["total_tokens"] == 14821

            # Verify [DONE] is appended for final chunk
            assert "data: [DONE]" in result_str, "Final chunk should have [DONE] marker"

    def test_usage_not_in_delta_content(self) -> None:
        """Usage data should NOT appear in delta.content."""
        base_time = 1000.0
        with patch("time.time", return_value=base_time):
            final_chunk = {
                "id": "chatcmpl-test",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "test-model",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            }

            streaming_content = StreamingContent(
                content=final_chunk,
                is_done=True,
                metadata={},
                usage=final_chunk.get("usage"),
            )

            result_bytes = streaming_content.to_bytes()
            result_str = result_bytes.decode("utf-8")

            # Parse the first data line - SSE format is "data: {...}\n\n..."
            data_prefix = "data: "
            first_data_end = result_str.find("\n\n")
            json_part = result_str[len(data_prefix) : first_data_end].strip()
            parsed = json.loads(json_part)

            # Check delta.content does NOT contain usage data
            delta = parsed["choices"][0].get("delta", {})
            content = delta.get("content", "")

            # Content should be empty or not contain usage JSON
            if content:
                assert "prompt_tokens" not in content, "Usage should not be in content"
                assert (
                    "completion_tokens" not in content
                ), "Usage should not be in content"

    def test_regular_content_chunk_still_works(self) -> None:
        """Regular content chunks should still be processed correctly."""
        content_chunk = {
            "id": "chatcmpl-12345",
            "object": "chat.completion.chunk",
            "created": 12345,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": "Hello, world!"},
                    "finish_reason": None,
                }
            ],
        }

        streaming_content = StreamingContent(
            content=content_chunk,
            is_done=False,
            metadata={},
        )

        result_bytes = streaming_content.to_bytes()
        result_str = result_bytes.decode("utf-8")

        json_part = result_str.replace("data: ", "").replace("\n\n", "").strip()
        parsed = json.loads(json_part)

        # Regular content should pass through correctly
        assert parsed.get("choices"), "Choices should be preserved"
        assert parsed["choices"][0]["delta"]["content"] == "Hello, world!"

    def test_from_raw_preserves_final_chunk_with_usage(self) -> None:
        """StreamingContent.from_raw() should preserve final chunk with usage."""
        final_chunk = {
            "id": "chatcmpl-test-12345",
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

        streaming_content = StreamingContent.from_raw(final_chunk)

        # Usage should be extracted
        assert (
            streaming_content.usage == final_chunk["usage"]
        ), "Usage should be extracted"

        # Content should preserve structure
        assert isinstance(streaming_content.content, dict)
        if "choices" in streaming_content.content:
            assert (
                "usage" in streaming_content.content
            ), "Usage should be in content dict"

        # Convert to bytes and verify correct serialization
        result_bytes = streaming_content.to_bytes()
        result_str = result_bytes.decode("utf-8")
        json_part = result_str.split("\n")[0].replace("data: ", "").strip()
        parsed = json.loads(json_part)

        assert "usage" in parsed, "Usage should be in serialized output"


class TestUsageLeakDetection:
    """Tests for detecting usage data leaks in message content."""

    def test_usage_leak_pattern_detection(self) -> None:
        """Test that we can detect usage chunk patterns in content leaks."""
        # This pattern indicates leaked usage chunk (the old bug)
        leaked_content = (
            '{"id": "chatcmpl-gemini-usage-1764320087", "object": "chat.completion.chunk", '
            '"created": 1764320087, "model": "gemini-3-pro-high", "choices": [], '
            '"usage": {"prompt_tokens": 14803, "completion_tokens": 18, "total_tokens": 14821}}'
        )

        # Pattern that indicates a usage-only chunk leaked as content
        # This should NOT happen with the new architecture
        usage_leak_patterns = [
            "chatcmpl-gemini-usage-",  # Old usage chunk ID pattern
            '"choices": []',  # Empty choices (usage-only chunk marker)
            '"usage": {',  # Usage data
        ]

        # If ALL of these patterns appear together, it's a leaked usage chunk
        matches = sum(1 for p in usage_leak_patterns if p in leaked_content)
        assert matches == len(
            usage_leak_patterns
        ), "Test data should match all leak patterns"

        # Normal content should not trigger false positives
        proper_content = "Here is some normal assistant response text"
        matches = sum(1 for p in usage_leak_patterns if p in proper_content)
        assert matches == 0, "Normal content should not match leak patterns"

    def test_detection_function_catches_leaked_usage(self) -> None:
        """Verify that our detection function correctly identifies leaked usage chunks."""

        def has_leaked_usage_chunk(content: str) -> bool:
            """Check if content contains a leaked usage chunk (the old bug pattern)."""
            if not isinstance(content, str):
                return False
            # Look for the distinctive pattern of a leaked usage-only chunk
            # This pattern should NOT appear with the new architecture
            return (
                "chatcmpl-gemini-usage-" in content
                and '"choices": []' in content
                and '"usage": {' in content
            )

        # Test data with leaked usage chunk (the old bug)
        leaked_content = (
            "<read_file><path>docs/file.md</path></read_file>"
            '{"id": "chatcmpl-gemini-usage-1764320087", "object": "chat.completion.chunk", '
            '"created": 1764320087, "model": "gemini-3-pro-high", "choices": [], '
            '"usage": {"prompt_tokens": 14803, "completion_tokens": 18, "total_tokens": 14821}}'
        )

        # Test data with normal content (no leak)
        normal_content = "<read_file><path>docs/file.md</path></read_file>"

        # The detection function should catch the leaked content
        assert has_leaked_usage_chunk(
            leaked_content
        ), "Detection function should identify leaked usage chunk"

        # The detection function should NOT flag normal content
        assert not has_leaked_usage_chunk(
            normal_content
        ), "Detection function should not flag normal content"

    @pytest.mark.parametrize(
        "content,should_detect",
        [
            (
                '{"id": "chatcmpl-gemini-usage-123", "choices": [], "usage": {"prompt_tokens": 1}}',
                True,
            ),
            ("Here is some normal text", False),
            ('{"choices": [{"delta": {"content": "hello"}}]}', False),
            (
                '<tool_call>{"name": "test"}</tool_call>{"id": "chatcmpl-gemini-usage-123", "choices": [], "usage": {}}',
                True,
            ),
            # Final stop chunk with usage should NOT be detected as leak
            # (it's properly formatted with non-empty choices)
            (
                '{"id": "chatcmpl-123", "choices": [{"finish_reason": "stop"}], "usage": {"total_tokens": 100}}',
                False,
            ),
        ],
    )
    def test_usage_leak_detection_patterns(
        self, content: str, should_detect: bool
    ) -> None:
        """Test that usage leak detection works for various patterns."""
        # The leak pattern is specifically: usage-only chunk with empty choices
        has_leak = (
            "chatcmpl-gemini-usage-" in content
            and '"choices": []' in content
            and '"usage":' in content
        )
        assert (
            has_leak == should_detect
        ), f"Detection mismatch for content: {content[:50]}..."


class TestStreamingContentUsageHandling:
    """Tests for StreamingContent handling of usage data."""

    def test_usage_passed_through_properly(self) -> None:
        """Usage data should be accessible on StreamingContent."""
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}

        sc = StreamingContent(
            content="test",
            is_done=True,
            metadata={},
            usage=usage,
        )

        assert sc.usage == usage, "Usage should be stored on StreamingContent"

    def test_usage_from_content_dict(self) -> None:
        """Usage should be extractable from content dict."""
        chunk = {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

        sc = StreamingContent.from_raw(chunk)

        assert sc.usage is not None, "Usage should be extracted"
        assert sc.usage["total_tokens"] == 15


class TestStopChunkWithUsage:
    """Tests for the StopChunkWithUsage protective wrapper class."""

    def test_str_raises_error(self) -> None:
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
        assert "stringify" in str(exc_info.value).lower()

    def test_repr_is_safe(self) -> None:
        """repr() should work without raising error (for debugging)."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        # repr should not raise
        result = repr(chunk)
        assert "StopChunkWithUsage" in result
        assert "chatcmpl-test" in result

    def test_dict_conversion_works(self) -> None:
        """Converting to plain dict should work for legitimate serialization."""
        original = {
            "id": "chatcmpl-test",
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
        chunk = StopChunkWithUsage(original)

        # dict() should work
        plain_dict = dict(chunk)
        assert plain_dict == original

        # to_plain_dict() should also work
        plain_dict2 = chunk.to_plain_dict()
        assert plain_dict2 == original

    def test_json_dumps_with_dict_conversion_works(self) -> None:
        """json.dumps(dict(chunk)) should work for legitimate serialization."""
        chunk = StopChunkWithUsage(
            {
                "id": "chatcmpl-test",
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            }
        )

        # This is the correct way to serialize
        result = json.dumps(dict(chunk))
        parsed = json.loads(result)

        assert parsed["id"] == "chatcmpl-test"
        assert parsed["usage"]["prompt_tokens"] == 100

    def test_wrap_method(self) -> None:
        """StopChunkWithUsage.wrap() should only wrap chunks with usage."""
        # Should wrap - has both usage and choices
        chunk_with_usage = {
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 100},
        }
        wrapped = StopChunkWithUsage.wrap(chunk_with_usage)
        assert isinstance(wrapped, StopChunkWithUsage)

        # Should NOT wrap - no usage
        chunk_without_usage = {
            "choices": [{"delta": {"content": "hello"}}],
        }
        not_wrapped = StopChunkWithUsage.wrap(chunk_without_usage)
        assert not isinstance(not_wrapped, StopChunkWithUsage)
        assert isinstance(not_wrapped, dict)

        # Should NOT wrap - no choices
        chunk_no_choices = {
            "usage": {"prompt_tokens": 100},
        }
        not_wrapped2 = StopChunkWithUsage.wrap(chunk_no_choices)
        assert not isinstance(not_wrapped2, StopChunkWithUsage)

    def test_streaming_content_to_bytes_handles_stop_chunk(self) -> None:
        """StreamingContent.to_bytes() should correctly serialize StopChunkWithUsage."""
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

        sc = StreamingContent(
            content=chunk,
            is_done=False,
            metadata={},
            usage=chunk.get("usage"),
        )

        # This should NOT raise - it should handle StopChunkWithUsage correctly
        result = sc.to_bytes()
        result_str = result.decode("utf-8")

        # Verify the output is correct SSE format with usage at top level
        assert "data: " in result_str
        # The output format is: "data: {json}\n\ndata: [DONE]\n\n"
        # Split by "data: " and filter out empty strings and [DONE]
        parts = [p.strip() for p in result_str.split("data: ") if p.strip()]
        # First part should be the JSON, second should be [DONE]
        assert len(parts) >= 1, f"Expected at least 1 data part, got: {parts}"
        json_part = parts[0].replace("\n\n", "").strip()
        parsed = json.loads(json_part)

        assert parsed["id"] == "chatcmpl-test"
        assert "usage" in parsed
        assert parsed["usage"]["prompt_tokens"] == 100
        # Usage should NOT be in delta.content
        delta = parsed["choices"][0].get("delta", {})
        assert "content" not in delta or not delta.get("content")
